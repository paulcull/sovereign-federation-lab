"""Pilot adapter into the existing single authoritative business coordinator."""
import json
import time
import uuid

from fastapi import APIRouter, Header, HTTPException

import operational_core as core
from customer_mdm import CustomerMDM
from pilot_common import (authenticated, digest, remote, tls_client, uuid_text,
                          live_configuration, registered_principal, require_command, processing_countries)
from pilot_projection import envelope


class PilotOwner:
    def __init__(self, runtime, config):
        self.runtime, self.config = runtime, config
        self.http = tls_client(config, timeout=5)
        self.mdm = CustomerMDM(runtime)
        runtime.pilot_transport = self

    def deliver(self, model, scope, destination, event_id, plan):
        binding = self.runtime.entities[destination]['store_id']
        peer = live_configuration(self.config)['peers'].get(binding)
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
            # Expiry reconciliation needs scope metadata, never every business row.
            scopes = c.execute('SELECT doc FROM sovereignty.scope WHERE owner_entity_id=%s',
                               (core.SPEC['owner_entity_id'],)).fetchall()
            for (s,) in scopes:
                expired = sorted(f"{e}:{g['expires_at']}" for e,g in s['policy']['grants'].items() if g['expires_at'] <= time.time())
                if expired != s['expired_seen']:
                    s['expired_seen'] = expired; s['decision_revision'] += 1
                    self.runtime.write_scope(c,s); self.runtime.enqueue(c,s)
            tasks = c.execute("SELECT id,scope_id,destination_entity_id,created_at FROM "
                "(SELECT id,scope_id,destination_entity_id,created_at,attempts,ROW_NUMBER() OVER "
                "(PARTITION BY scope_id,destination_entity_id ORDER BY created_at DESC,id DESC) AS priority "
                "FROM sovereignty.outbox WHERE status IN ('queued','retry')) "
                "WHERE priority=1 ORDER BY attempts,created_at,id LIMIT 15").fetchall()
        unavailable = set()
        for event, sid, destination, cutoff in tasks:
            try:
                binding = self.runtime.entities[destination]['store_id']
                if binding in unavailable:
                    # One failed transport probe per store/batch. Keep every intent
                    # durable and rotate deferred processing attempts as retries.
                    raise HTTPException(503,'Recipient unavailable in this batch')
                with self.runtime.stores[self.runtime.home].connect() as c:
                    model = self.runtime.load_scope(c,str(sid))
                s = core.next_scope(model,str(sid))
                # Neither source OPA nor peer transport owns the coordination lock.
                relay_principal = dict(entity_id=destination,
                    processing_country=self.runtime.store_info[self.runtime.home]['country'])
                pin = self.state_pin(model,s,relay_principal)
                plan = self.runtime.plan(model,s,destination)
                with self.runtime.lock, self.runtime.stores[self.runtime.home].connect() as c:
                    current_model = self.runtime.load_scope(c,str(sid))
                    current = core.next_scope(current_model,str(sid))
                    if pin != self.state_pin(current_model,current,relay_principal):
                        raise HTTPException(409,'Source changed during export admission')
                    s = current
                    if not plan['rows'] and destination not in s['contacted']:
                        status='blocked'
                    else:
                        status=None
                        if self.runtime.paused[binding]:
                            raise HTTPException(503,'Recipient ingress paused')
                        if plan['rows'] and destination not in s['contacted']:
                            s['contacted'].append(destination)
                            self.runtime.write_scope(c,s)
                if status is None:
                    try:
                        status=self.deliver(model,s,destination,event,plan)
                    except HTTPException as failure:
                        if failure.status_code == 503:
                            unavailable.add(binding)
                        raise
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
            except Exception as failure:
                if isinstance(failure, HTTPException) and failure.status_code == 409 and failure.detail == {'code':'projection_receipt_conflict'}:
                    # A lost acknowledgement can leave this UUID bound to an older
                    # committed envelope. Retire only that intent and create one
                    # new identity for fresh admission; never fabricate a receipt.
                    with self.runtime.lock, self.runtime.stores[self.runtime.home].connect() as c:
                        retired = c.execute(
                            "UPDATE sovereignty.outbox SET status='superseded',reason='Recipient receipt conflict; fresh intent queued' "
                            "WHERE id=%s AND status IN ('queued','retry') RETURNING scope_id,destination_entity_id",
                            (event,)).fetchone()
                        if retired:
                            c.execute('INSERT INTO sovereignty.outbox (id,scope_id,destination_entity_id,created_at) VALUES (%s,%s,%s,%s)',
                                (str(uuid.uuid4()),retired[0],retired[1],time.time()))
                            self.runtime.audit(c,s,destination,'delivery_replanned','Fresh intent after durable receipt conflict')
                    continue
                # Failure text is deliberately fixed; no raw URL/exception enters diagnostics.
                with self.runtime.stores[self.runtime.home].connect() as c:
                    c.execute("UPDATE sovereignty.outbox SET status='retry',reason='Pilot peer delivery pending',attempts=attempts+1 WHERE id=%s",(event,))

    def state(self, sid):
        with self.runtime.stores[self.runtime.home].connect() as c:
            sid = uuid_text(sid)
            model = self.runtime.load_scope(c,sid)
        try:
            return model, core.next_scope(model, sid)
        except StopIteration:
            raise HTTPException(404, 'Scope not found')

    def principal(self, name):
        return registered_principal(self.config, name)

    def admit(self, model, scope, principal):
        owner = self.runtime.entities[scope['owner_entity_id']]
        store = self.runtime.store_info[owner['store_id']]
        if owner['store_id'] != scope['home_store_id'] or scope['home_store_id'] != self.runtime.home:
            raise HTTPException(409, 'Authoritative writer placement changed')
        if store['country'] not in owner['approved_countries'] or store['country'] not in scope['policy']['allowed_countries'] or store['country'] in scope['policy']['denied_countries']:
            raise HTTPException(403, 'Authoritative placement excluded')
        countries = processing_countries(live_configuration(self.config), principal)
        p = scope['policy']
        if any(country not in p['allowed_countries'] or country in p['denied_countries'] for country in countries):
            raise HTTPException(403, 'Processing location excluded')
        entity = principal['entity_id']
        if entity == scope['owner_entity_id']:
            plan = {'rows': [{'table': r['table'], 'row': r['row']} for r in core.resources(model, scope)]}
        else:
            try:
                plan = self.runtime.plan(model, scope, entity)
            except Exception:
                raise HTTPException(503, 'Current policy unavailable; fail closed')
        if not plan['rows']:
            raise HTTPException(403, 'No approved scope for this recipient')
        facts = {(r['table'],r['row']['id']):r for r in core.resources(model, scope)}
        for row in plan['rows']:
            fact = facts[(row['table'],row['row']['id'])]
            # Storage admission cannot establish the caller's processing permission.
            # Reject the whole scope to preserve dependency closure without disclosure.
            for geography in (fact['table_rule'],fact['rule']):
                if any(country not in geography['allowed_countries'] or country in geography['denied_countries'] for country in countries):
                    raise HTTPException(403, 'Processing location excluded')
        return plan

    def state_pin(self, model, scope, principal):
        # Contacted recipients are delivery bookkeeping; every authority-bearing
        # fact, business value and placement participates in the comparison.
        relevant = {k:v for k,v in model.items() if k in ('rows','rules','bindings','table_rules')}
        relevant['principal'] = principal
        relevant['processing_countries'] = sorted(processing_countries(live_configuration(self.config), principal))
        relevant['scope'] = {k:v for k,v in scope.items() if k != 'contacted'}
        relevant['owner'] = self.runtime.entities[scope['owner_entity_id']]
        relevant['destination'] = self.runtime.entities[principal['entity_id']]
        relevant['stores'] = {entity['store_id']:self.runtime.store_info[entity['store_id']]
                              for entity in (relevant['owner'], relevant['destination'])}
        return digest(relevant)

    def route(self, scope, principal, minimum):
        if type(minimum) is not int or minimum < 0:
            raise HTTPException(422, 'Invalid minimum data version')
        if minimum > scope['data_version']:
            raise HTTPException(409, 'Requested source version has not committed')
        return dict(owner_entity_id=scope['owner_entity_id'], scope_id=scope['id'],
            scope_kind=scope['scope_kind'],
            destination_entity_id=principal['entity_id'], data_version=scope['data_version'],
            policy_generation=scope['policy_generation'], decision_revision=scope['decision_revision'],
            source_placement_version=self.runtime.entities[scope['owner_entity_id']]['placement_version'],
            placement_version=self.runtime.entities[principal['entity_id']]['placement_version'],
            store_id=self.runtime.entities[principal['entity_id']]['store_id'])

    def admitted(self, sid, principal, minimum=0):
        """Fresh bounded SQL -> OPA -> SQL pin check, without the writer lock.

        The extra read detects business/policy changes during OPA I/O. No cached
        permission or distributed lease is introduced. A racing change is an
        explicit retry, never a return of an unchecked partial graph.
        """
        principal = self.principal(principal['id'])
        if 'read' not in principal['actions']:
            raise HTTPException(403, 'Read authority required')
        model, scope = self.state(sid)
        pin = self.state_pin(model, scope, principal)
        plan = self.admit(model, scope, principal)
        route = self.route(scope, principal, minimum)
        current_model, current_scope = self.state(sid)
        current_principal = self.principal(principal['id'])
        if pin != self.state_pin(current_model, current_scope, current_principal):
            raise HTTPException(409, 'Current source changed during admission; retry')
        return model, scope, plan, route, pin

    def routing(self, sid, principal, minimum=0):
        return self.admitted(sid, principal, minimum)[3]

    def read(self, sid, principal, freshness, minimum):
        # Neither source OPA nor peer HTTP can hold the shared writer lock.
        model, scope, plan, route, pin = self.admitted(sid, principal, minimum)
        if freshness == 'owner' or principal['entity_id'] == scope['owner_entity_id']:
            return {**route, 'served_from': 'owner', 'rows': plan['rows']}
        if freshness != 'projection':
            raise HTTPException(422, 'Choose owner or projection freshness')
        peer = live_configuration(self.config)['peers'].get(route['store_id'])
        if peer is None:
            raise HTTPException(503, 'No configured recipient peer')
        result = remote(self.http, 'POST', peer['url'] + '/internal/read', peer['import_token'],
                        dict(scope_id=sid, destination_entity_id=principal['entity_id'],
                             principal_id=principal['id'], minimum_data_version=minimum))
        # A restriction can commit while the peer is responding. Recheck source
        # policy and allowed fields before returning its payload to the caller.
        _, _, current_plan, current, _ = self.admitted(sid, principal, minimum)
        # Projection freshness permits older business values above the requested
        # minimum. Current authority, row membership and field rights still have
        # to match; a normal source update alone must not become a permission fence.
        self.validate_view(result,current_plan,current,minimum)
        return result

    def validate_view(self, result, plan, current, minimum):
        approved = {(row['table'],row['row']['id']):set(row['row']) for row in plan['rows']}
        if any(result.get(key) != value for key,value in current.items() if key != 'data_version'):
            raise HTTPException(409, 'Peer authority changed during read; retry')
        if type(result.get('data_version')) is not int or not minimum <= result['data_version'] <= current['data_version']:
            raise HTTPException(409, 'Peer data version outside requested authority')
        if result.get('served_from') == 'owner' and result['data_version'] != current['data_version']:
            raise HTTPException(409, 'Current owner view changed during assembly; retry')
        if not isinstance(result.get('rows'),list) or any(
            (row.get('table'),row.get('row',{}).get('id')) not in approved or
            not set(row.get('row',{})) <= approved[(row['table'],row['row']['id'])]
            for row in result['rows']):
            raise HTTPException(409, 'Peer graph requires current-policy reconciliation')

    def customer_view(self, gid, principal, freshness, minimum):
        gid = uuid_text(gid)
        with self.runtime.stores[self.runtime.home].connect() as c:
            row = c.execute('SELECT id FROM business.party WHERE owner_entity_id=%s AND global_party_id=%s',
                            (core.SPEC['owner_entity_id'], gid)).fetchone()
            if not row:
                raise HTTPException(404, 'Approved customer view not found')
            candidates = [str(r[0]) for r in c.execute('SELECT id FROM sovereignty.scope '
                'WHERE owner_entity_id=%s AND primary_party_id=%s ORDER BY root_type,id LIMIT 51',
                (core.SPEC['owner_entity_id'], row[0]))]
        if len(candidates) > 50:
            raise HTTPException(422, 'Customer exceeds bounded scope query')
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
        # An earlier scope may change while a later scope waits for a peer.
        # Revalidate the assembled result rather than returning stale permissions.
        for view in views:
            _, _, plan, route, _ = self.admitted(view['scope_id'],principal,minimum)
            self.validate_view(view,plan,route,minimum)
        return dict(global_party_id=gid, entity_id=principal['entity_id'], views=views,
                    freshness=freshness, minimum_data_version=minimum)


def owner_router(owner):
    router = APIRouter(prefix='/api/pilot/internal', include_in_schema=False)

    def identity(header, role):
        _, value = authenticated(header, live_configuration(owner.config)['identities'])
        if value['role'] != role:
            raise HTTPException(403, 'Workload role rejected')
        return value

    @router.post('/system')
    def system(body: dict, authorization: str | None = Header(None)):
        identity(authorization, 'api')
        principal = owner.principal(body.get('principal_id'))
        if ('system' not in principal['actions'] or principal['entity_id'] != core.SPEC['owner_entity_id']
                or processing_countries(live_configuration(owner.config),principal) != {'SG'}):
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
        if payload['command'] == 'update_contact' and payload.get('value') is None:
            raise HTTPException(422, 'Contact update requires a value')
        # Policy I/O precedes the writer lock. The exact input is revalidated
        # inside the lock before the unchanged atomic business/audit/outbox hook.
        require_command(principal,payload)
        model, scope = owner.state(body.get('scope_id'))
        pin = owner.state_pin(model,scope,principal)
        owner.admit(model,scope,principal)
        def validate(connection):
            current_principal = owner.principal(body.get('principal_id'))
            require_command(current_principal,payload)
            current_model = owner.runtime.load_scope(connection,scope['id'])
            current_scope = core.next_scope(current_model,scope['id'])
            if pin != owner.state_pin(current_model,current_scope,current_principal):
                raise HTTPException(409,'Source authority changed before command; retry')
            if current_principal['entity_id'] != current_scope['owner_entity_id']:
                grant = current_scope['policy']['grants'].get(current_principal['entity_id'],{})
                if grant.get('active') is not True or grant.get('expires_at',0) <= time.time():
                    raise HTTPException(403,'Delegated scope grant expired before command')
        receipt = owner.runtime.command(scope['id'], {**payload,'pilot_actor':principal['id']},validate=validate)
        # Full receipt stays in CockroachDB. Never disclose other affected scopes
        # or owner-only history identifiers, including on an idempotent replay.
        result = {k:receipt[k] for k in ('request_id','scope_id','command','time',
            'idempotent_replay','source_transaction','replication')}
        result['scope_versions'] = {scope['id']:receipt['scope_versions'][scope['id']]}
        return result

    @router.post('/admission')
    def admission(body: dict, authorization: str | None = Header(None)):
        peer = identity(authorization, 'peer')
        destination = body.get('destination_entity_id')
        if destination not in owner.runtime.entities or owner.runtime.entities[destination]['store_id'] != peer['store_id']:
            raise HTTPException(403, 'Peer store binding rejected')
        if body.get('operation') == 'read':
            principal = owner.principal(body.get('principal_id'))
            if principal['entity_id'] != destination or 'read' not in principal['actions']:
                raise HTTPException(403, 'Recipient identity rejected')
            model, scope, plan, current, _ = owner.admitted(body.get('scope_id'), principal, body.get('minimum_data_version', 0))
            approved = envelope(owner.runtime, model, scope, destination, 'read-guard', plan)
            return {**current, 'policy': approved['policy'],
                    'facts': [{**r, 'source_fields': sorted(r['row']),
                               'row': {'id': r['row']['id']}} for r in approved['facts']]}
        if body.get('operation') != 'import':
            raise HTTPException(422, 'Invalid admission operation')
        model, scope = owner.state(body.get('scope_id'))
        import_principal = dict(entity_id=destination,
            processing_country=owner.runtime.store_info[owner.runtime.home]['country'])
        pin = owner.state_pin(model,scope,import_principal)
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
        current_model, current_scope = owner.state(scope['id'])
        if pin != owner.state_pin(current_model,current_scope,import_principal):
            raise HTTPException(409, 'Source changed during import admission')
        return dict(accepted=True, data_version=scope['data_version'],
                    policy_generation=scope['policy_generation'], decision_revision=scope['decision_revision'])

    return router
