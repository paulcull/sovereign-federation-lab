"""Pilot adapter into the existing single authoritative business coordinator."""
import json
import time

from fastapi import APIRouter, Header, HTTPException

import operational_core as core
from customer_mdm import CustomerMDM
from pilot_common import authenticated, digest, remote, tls_client, uuid_text
from pilot_projection import envelope


class PilotOwner:
    def __init__(self, runtime, config):
        self.runtime, self.config = runtime, config
        self.http = tls_client(config, timeout=5)
        self.mdm = CustomerMDM(runtime)
        runtime.pilot_transport = self

    def deliver(self, model, scope, destination, event_id, plan):
        binding = self.runtime.entities[destination]['store_id']
        peer = self.config['peers'].get(binding)
        if peer is None:
            # Missing peer fails closed; never silently switch back to direct SQL.
            raise HTTPException(503, 'No configured recipient peer')
        message = envelope(self.runtime, model, scope, destination, event_id, plan)
        result = remote(self.http, 'POST', peer['url'] + '/internal/import', peer['import_token'], message)
        if result.get('status') not in ('replicated', 'purged', 'duplicate'):
            raise HTTPException(503, 'Recipient acknowledgement invalid')
        return result['status']

    def tick(self):
        """Bounded relay: no peer/WAN call holds the owner's coordination lock.

        Current source admission, monotonic recipient manifests and strict reads
        guard races. This is a single relay, not a distributed lease protocol.
        """
        with self.runtime.lock, self.runtime.stores[self.runtime.home].connect() as c:
            model = self.runtime.load(c)
            for s in model['scopes']:
                expired = sorted(f"{e}:{g['expires_at']}" for e,g in s['policy']['grants'].items() if g['expires_at'] <= time.time())
                if expired != s['expired_seen']:
                    s['expired_seen'] = expired; s['decision_revision'] += 1
                    self.runtime.write_controls(c,model,[s['id']]); self.runtime.enqueue(c,s)
            tasks = c.execute("SELECT id,scope_id,destination_entity_id,created_at FROM "
                "(SELECT id,scope_id,destination_entity_id,created_at,ROW_NUMBER() OVER "
                "(PARTITION BY scope_id,destination_entity_id ORDER BY created_at DESC,id DESC) AS priority "
                "FROM sovereignty.outbox WHERE status IN ('queued','retry')) "
                "WHERE priority=1 ORDER BY created_at LIMIT 15").fetchall()
        for event, sid, destination, cutoff in tasks:
            try:
                with self.runtime.lock:
                    with self.runtime.stores[self.runtime.home].connect() as c:
                        model = self.runtime.load(c)
                    s = core.next_scope(model,str(sid))
                    # Neither policy RPC nor peer transport runs inside a SQL transaction.
                    plan = self.runtime.plan(model,s,destination)
                    if not plan['rows'] and destination not in s['contacted']:
                        status='blocked'
                    else:
                        status=None
                        if self.runtime.paused[self.runtime.entities[destination]['store_id']]:
                            raise HTTPException(503,'Recipient ingress paused')
                        if plan['rows'] and destination not in s['contacted']:
                            s['contacted'].append(destination)
                            with self.runtime.stores[self.runtime.home].connect() as c:
                                self.runtime.write_controls(c,model,[s['id']])
                if status is None:
                    status=self.deliver(model,s,destination,event,plan)
                with self.runtime.lock, self.runtime.stores[self.runtime.home].connect() as c:
                    c.execute('UPDATE sovereignty.outbox SET status=%s,reason=%s,attempts=attempts+1 WHERE id=%s',
                              (status,'Pilot peer acknowledged' if status!='blocked' else 'Source policy blocked',event))
                    # Current-state projections can supersede older delivery intents, not audit.
                    # A restriction committed after selection stays queued beyond this cutoff.
                    c.execute("UPDATE sovereignty.outbox SET status='superseded',reason='Current authorised state superseded this intent' "
                        "WHERE scope_id=%s AND destination_entity_id=%s AND id!=%s AND status IN ('queued','retry') "
                        "AND (created_at<%s OR (created_at=%s AND id<=%s))",
                        (sid,destination,event,cutoff,cutoff,event))
                    self.runtime.audit(c,s,destination,status,'Pilot source decision or peer receipt')
            except Exception:
                # Failure text is deliberately fixed; no raw URL/exception enters diagnostics.
                with self.runtime.stores[self.runtime.home].connect() as c:
                    c.execute("UPDATE sovereignty.outbox SET status='retry',reason='Pilot peer delivery pending',attempts=attempts+1 WHERE id=%s",(event,))

    def state(self, sid):
        with self.runtime.stores[self.runtime.home].connect() as c:
            model = self.runtime.load(c)
        try:
            return model, core.next_scope(model, uuid_text(sid))
        except StopIteration:
            raise HTTPException(404, 'Scope not found')

    def principal(self, name):
        principal = self.config['principals'].get(name)
        if principal is None:
            raise HTTPException(403, 'Unknown pilot principal')
        return principal

    def admit(self, model, scope, principal):
        owner = self.runtime.entities[scope['owner_entity_id']]
        store = self.runtime.store_info[owner['store_id']]
        if owner['store_id'] != scope['home_store_id'] or scope['home_store_id'] != self.runtime.home:
            raise HTTPException(409, 'Authoritative writer placement changed')
        if store['country'] not in owner['approved_countries'] or store['country'] not in scope['policy']['allowed_countries'] or store['country'] in scope['policy']['denied_countries']:
            raise HTTPException(403, 'Authoritative placement excluded')
        country = principal['processing_country']
        p = scope['policy']
        if country not in p['allowed_countries'] or country in p['denied_countries']:
            raise HTTPException(403, 'Processing location excluded')
        entity = principal['entity_id']
        if entity == scope['owner_entity_id']:
            return {'rows': [{'table': r['table'], 'row': r['row']} for r in core.resources(model, scope)]}
        try:
            plan = self.runtime.plan(model, scope, entity)
        except Exception:
            raise HTTPException(503, 'Current policy unavailable; fail closed')
        if not plan['rows']:
            raise HTTPException(403, 'No approved scope for this recipient')
        return plan

    def routing(self, sid, principal, minimum=0):
        model, scope = self.state(sid)
        self.admit(model, scope, principal)
        if type(minimum) is not int or minimum < 0:
            raise HTTPException(422, 'Invalid minimum data version')
        if minimum > scope['data_version']:
            raise HTTPException(409, 'Requested source version has not committed')
        return dict(owner_entity_id=scope['owner_entity_id'], scope_id=scope['id'],
            scope_kind=scope['scope_kind'],
            destination_entity_id=principal['entity_id'], data_version=scope['data_version'],
            policy_generation=scope['policy_generation'], decision_revision=scope['decision_revision'],
            placement_version=self.runtime.entities[principal['entity_id']]['placement_version'],
            store_id=self.runtime.entities[principal['entity_id']]['store_id'])

    def read(self, sid, principal, freshness, minimum):
        # Current source facts are checked for every read; there is no offline lease.
        model, scope = self.state(sid)
        plan = self.admit(model, scope, principal)
        route = self.routing(sid, principal, minimum)
        if freshness == 'owner' or principal['entity_id'] == scope['owner_entity_id']:
            return {**route, 'served_from': 'owner', 'rows': plan['rows']}
        if freshness != 'projection':
            raise HTTPException(422, 'Choose owner or projection freshness')
        peer = self.config['peers'].get(route['store_id'])
        if peer is None:
            raise HTTPException(503, 'No configured recipient peer')
        return remote(self.http, 'POST', peer['url'] + '/internal/read', peer['import_token'],
                      dict(scope_id=sid, destination_entity_id=principal['entity_id'],
                           principal_id=principal['id'], minimum_data_version=minimum))

    def customer_view(self, gid, principal, freshness, minimum):
        gid = uuid_text(gid)
        with self.runtime.stores[self.runtime.home].connect() as c:
            row = c.execute('SELECT id FROM business.party WHERE owner_entity_id=%s AND global_party_id=%s',
                            (core.SPEC['owner_entity_id'], gid)).fetchone()
            if not row:
                raise HTTPException(404, 'Approved customer view not found')
            candidates = [str(r[0]) for r in c.execute('SELECT id FROM sovereignty.scope '
                'WHERE owner_entity_id=%s AND primary_party_id=%s ORDER BY root_type,id',
                (core.SPEC['owner_entity_id'], row[0]))]
        views = []
        for sid in candidates:
            try:
                views.append(self.read(sid, principal, freshness, minimum))
            except HTTPException as error:
                if error.status_code == 403:
                    continue  # Do not disclose existence or counts of forbidden relationships.
                raise
        if not views:
            raise HTTPException(404, 'Approved customer view not found')
        return dict(global_party_id=gid, entity_id=principal['entity_id'], views=views,
                    freshness=freshness, minimum_data_version=minimum)


def owner_router(owner):
    router = APIRouter(prefix='/api/pilot/internal', include_in_schema=False)

    def identity(header, role):
        _, value = authenticated(header, owner.config['identities'])
        if value['role'] != role:
            raise HTTPException(403, 'Workload role rejected')
        return value

    @router.post('/system')
    def system(body: dict, authorization: str | None = Header(None)):
        identity(authorization, 'api')
        principal = owner.principal(body.get('principal_id'))
        if 'system' not in principal['actions'] or principal['entity_id'] != core.SPEC['owner_entity_id'] or principal['processing_country'] != 'SG':
            raise HTTPException(403, 'System API authority required')
        source = principal['source_system']
        operation = body.get('operation')
        reference = body.get('reference')
        if operation == 'get':
            return owner.mdm.get(source, reference)
        if operation == 'upsert':
            return owner.mdm.upsert(source, reference, body['payload'])
        if operation == 'relationship':
            return owner.mdm.relationship(source, reference, body['payload'])
        raise HTTPException(422, 'Unknown system operation')

    @router.post('/experience')
    def experience(body: dict, authorization: str | None = Header(None)):
        identity(authorization, 'api')
        principal = owner.principal(body.get('principal_id'))
        if 'read' not in principal['actions']:
            raise HTTPException(403, 'Read authority required')
        freshness = body.get('freshness', 'projection')
        minimum = body.get('minimum_data_version', 0)
        with owner.runtime.lock:
            if 'global_party_id' in body:
                return owner.customer_view(body['global_party_id'], principal, freshness, minimum)
            return owner.read(body.get('scope_id'), principal, freshness, minimum)

    @router.post('/command')
    def command(body: dict, authorization: str | None = Header(None)):
        identity(authorization, 'api')
        principal = owner.principal(body.get('principal_id'))
        if 'command' not in principal['actions']:
            raise HTTPException(403, 'Command authority required')
        payload = body.get('payload', {})
        if payload.get('command') not in ('update_contact', 'withdraw_consent', 'restore_consent'):
            raise HTTPException(403, 'Command outside pilot delegation')
        # Recheck within the same coordinator lock as the business transaction.
        with owner.runtime.lock:
            model, scope = owner.state(body.get('scope_id'))
            owner.admit(model, scope, principal)
            return owner.runtime.command(scope['id'], {**payload,'pilot_actor':principal['id']})

    @router.post('/admission')
    def admission(body: dict, authorization: str | None = Header(None)):
        peer = identity(authorization, 'peer')
        destination = body.get('destination_entity_id')
        if destination not in owner.runtime.entities or owner.runtime.entities[destination]['store_id'] != peer['store_id']:
            raise HTTPException(403, 'Peer store binding rejected')
        model, scope = owner.state(body.get('scope_id'))
        if body.get('operation') == 'read':
            principal = owner.principal(body.get('principal_id'))
            if principal['entity_id'] != destination or 'read' not in principal['actions']:
                raise HTTPException(403, 'Recipient identity rejected')
            current = owner.routing(scope['id'], principal, body.get('minimum_data_version', 0))
            plan = owner.runtime.plan(model, scope, destination)
            approved = envelope(owner.runtime, model, scope, destination, 'read-guard', plan)
            return {**current, 'policy': approved['policy'],
                    'facts': [{**r, 'row': {'id': r['row']['id']}} for r in approved['facts']]}
        if body.get('operation') != 'import':
            raise HTTPException(422, 'Invalid admission operation')
        with owner.runtime.stores[owner.runtime.home].connect() as c:
            task = c.execute('SELECT scope_id,destination_entity_id FROM sovereignty.outbox WHERE id=%s',
                             (uuid_text(body.get('event_id')),)).fetchone()
        if not task or str(task[0]) != scope['id'] or task[1] != destination:
            raise HTTPException(403, 'Unknown export intent')
        plan = owner.runtime.plan(model, scope, destination)
        if not plan['rows'] and destination not in scope['contacted']:
            raise HTTPException(403, 'Never-authorised route')
        expected = envelope(owner.runtime, model, scope, destination, body['event_id'], plan)
        if digest(expected) != body.get('digest'):
            raise HTTPException(409, 'Current authorised envelope changed')
        return dict(accepted=True, data_version=scope['data_version'],
                    policy_generation=scope['policy_generation'], decision_revision=scope['decision_revision'])

    return router
