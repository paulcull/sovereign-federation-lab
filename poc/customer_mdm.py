"""Base MDM: owner-qualified source references over the operational party model.

No second golden-record database, fuzzy matching or automatic merge of rights.
"""
import copy
import re
import time
import uuid

from fastapi import HTTPException
from psycopg.errors import SerializationFailure
from psycopg.types.json import Jsonb

import operational_core as core
from pilot_common import digest, uuid_text


PROFILES = {'owner_only', 'global_minimum', 'global_minimum_no_us'}


def policy(owner, kind, profile):
    recipients = [] if profile == 'owner_only' else ['LE-GB-02', 'LE-GB-03', 'LE-US-01'] if kind == 'party' else ['LE-GB-02', 'LE-US-01']
    purpose = 'identity_resolution' if kind == 'party' else 'servicing'
    return dict(owner_entity_id=owner, allowed_entities=recipients, denied_entities=[],
        allowed_countries=['SG', 'GB', 'US'], denied_countries=['US']
        if profile == 'global_minimum_no_us' or kind == 'relationship' else [], purpose=purpose,
        grants={entity: dict(active=True, expires_at=4102444800, profile='minimal'
                if kind == 'party' else 'contact', purpose=purpose) for entity in recipients})


def scope(runtime, party_id, kind, root_id, profile):
    return dict(id=str(uuid.uuid4()), name='Synthetic MDM ' + kind,
        owner_entity_id=core.SPEC['owner_entity_id'], primary_party_id=party_id,
        scope_kind=kind, root_type=kind, root_id=root_id,
        relationship_id=root_id if kind == 'relationship' else None,
        home_store_id=runtime.home, data_version=1, decision_revision=1, policy_generation=1,
        contacted=[], expired_seen=[], policy=policy(core.SPEC['owner_entity_id'], kind, profile))


class CustomerMDM:
    def __init__(self, runtime):
        self.runtime = runtime

    def initialize(self):
        with self.runtime.stores[self.runtime.home].connect() as c:
            c.execute('CREATE SCHEMA IF NOT EXISTS mdm')
            c.execute('CREATE TABLE IF NOT EXISTS mdm.source_reference ('
                'owner_entity_id STRING NOT NULL, source_system STRING NOT NULL, external_reference STRING NOT NULL, '
                'party_id UUID NOT NULL, PRIMARY KEY(owner_entity_id,source_system,external_reference), '
                'FOREIGN KEY(owner_entity_id,party_id) REFERENCES business.party(owner_entity_id,id))')
            c.execute('CREATE TABLE IF NOT EXISTS mdm.request_receipt ('
                'owner_entity_id STRING NOT NULL, request_id UUID NOT NULL, request_hash STRING NOT NULL, '
                'result JSONB NOT NULL, PRIMARY KEY(owner_entity_id,request_id))')
            for reference, party in zip(('SYN-ASTER', 'SYN-TRADING'), core.SPEC['rows']['party']):
                c.execute('INSERT INTO mdm.source_reference VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING',
                    (core.SPEC['owner_entity_id'], 'crm-sg', reference, party['id']))

    def reference(self, value):
        if not isinstance(value, str) or not re.fullmatch(r'SYN-[A-Z0-9-]{1,64}', value):
            raise HTTPException(422, 'Use a synthetic SYN- source reference')
        return value

    def customer(self, c, source, reference):
        row = c.execute('SELECT p.id,p.global_party_id,p.party_type,p.display_name,s.data_version,s.id '
            'FROM mdm.source_reference r JOIN business.party p ON p.owner_entity_id=r.owner_entity_id AND p.id=r.party_id '
            "JOIN sovereignty.scope s ON s.owner_entity_id=p.owner_entity_id AND s.root_type='party' AND s.root_id=p.id "
            'WHERE r.owner_entity_id=%s AND r.source_system=%s AND r.external_reference=%s',
            (core.SPEC['owner_entity_id'], source, self.reference(reference))).fetchone()
        if not row:
            raise HTTPException(404, 'Source reference not found')
        return dict(party_id=str(row[0]), global_party_id=str(row[1]), party_type=row[2],
                    display_name=row[3], version=row[4], party_scope_id=str(row[5]),
                    owner_entity_id=core.SPEC['owner_entity_id'], source_system=source,
                    external_reference=reference)

    def get(self, source, reference):
        with self.runtime.stores[self.runtime.home].connect() as c:
            return self.customer(c, source, reference)

    def transaction(self, operation, body, action):
        request_id = uuid_text(body.get('request_id'))
        fingerprint = digest(dict(operation=operation, body=body))
        for attempt in range(3):
            try:
                with self.runtime.lock, self.runtime.stores[self.runtime.home].connect() as c:
                    prior = c.execute('SELECT request_hash,result FROM mdm.request_receipt '
                        'WHERE owner_entity_id=%s AND request_id=%s',
                        (core.SPEC['owner_entity_id'], request_id)).fetchone()
                    if prior:
                        if prior[0] != fingerprint:
                            raise HTTPException(409, 'Request ID reused with different input')
                        return {**prior[1], 'idempotent_replay': True}
                    result = {**action(c), 'request_id': request_id, 'idempotent_replay': False}
                    c.execute('INSERT INTO mdm.request_receipt VALUES (%s,%s,%s,%s)',
                        (core.SPEC['owner_entity_id'], request_id, fingerprint, Jsonb(result)))
                return result
            except SerializationFailure:
                if attempt == 2:
                    raise HTTPException(503, 'Transaction contention; retry the same request ID')
                time.sleep(.02 * (attempt + 1))

    def upsert(self, source, reference, body):
        if set(body) - {'request_id','expected_version','display_name','party_type','identity_profile'}:
            raise HTTPException(422, 'Unknown system customer fields')
        reference = self.reference(reference)
        name = body.get('display_name')
        if not isinstance(name, str) or not name.startswith('Synthetic ') or len(name) > 120:
            raise HTTPException(422, 'Use a Synthetic display name of at most 120 characters')
        if body.get('party_type') not in ('PERSON', 'ORGANISATION'):
            raise HTTPException(422, 'Invalid party type')
        profile = body.get('identity_profile', 'owner_only')
        if profile not in PROFILES or type(body.get('expected_version')) is not int:
            raise HTTPException(422, 'Invalid identity profile or expected version')

        def apply(c):
            model = self.runtime.load(c)
            try:
                existing = self.customer(c, source, reference)
            except HTTPException as error:
                if error.status_code != 404:
                    raise
                existing = None
            if existing:
                if existing['version'] != body['expected_version']:
                    raise HTTPException(409, 'Stale customer version')
                party = next(r for r in model['rows']['party'] if r['id'] == existing['party_id'])
                party_scope = core.next_scope(model, existing['party_scope_id'])
                # Policy changes are explicit; existing identity profile cannot silently broaden.
                current = 'owner_only' if not party_scope['policy']['grants'] else 'global_minimum_no_us' if 'US' in party_scope['policy']['denied_countries'] else 'global_minimum'
                if profile != current or party['party_type'] != body['party_type']:
                    raise HTTPException(409, 'Identity profile or party type requires separate governed change')
                party['display_name'] = name
                affected = [s for s in model['scopes'] if any(b['scope_id'] == s['id'] and
                    b['resource_type'] == 'party' and b['resource_id'] == party['id'] for b in model['bindings'])]
                for s in affected:
                    s['data_version'] += 1
            else:
                if body['expected_version'] != 0:
                    raise HTTPException(409, 'A new source reference requires version zero')
                party = dict(id=str(uuid.uuid4()), global_party_id=str(uuid.uuid4()),
                             party_type=body['party_type'], display_name=name)
                model['rows']['party'].append(party)
                party_scope = scope(self.runtime, party['id'], 'party', party['id'], profile)
                model['scopes'].append(party_scope)
                model['rules'].append(dict(resource_type='party', resource_id=party['id'],
                    allowed_countries=['SG', 'GB', 'US'], denied_countries=['US']
                    if profile == 'global_minimum_no_us' else [], allowed_profiles=['minimal', 'contact'], sensitivity='INTERNAL'))
                model['bindings'].append(dict(scope_id=party_scope['id'], resource_type='party', resource_id=party['id']))
                affected = [party_scope]
            self.runtime.write_business(c, 'party', party)
            self.runtime.write_controls(c, model, [s['id'] for s in affected])
            c.execute('UPSERT INTO mdm.source_reference VALUES (%s,%s,%s,%s)',
                (core.SPEC['owner_entity_id'], source, reference, party['id']))
            for s in affected:
                self.runtime.enqueue(c, s)
                self.runtime.audit(c, s, s['owner_entity_id'], 'business_commit', 'MDM customer and atomic export intent',actor_id=source,request_id=body['request_id'])
            return self.customer(c, source, reference)
        return self.transaction('customer:' + source + ':' + reference, body, apply)

    def relationship(self, source, reference, body):
        if set(body) - {'request_id','expected_version','sharing_profile','email'}:
            raise HTTPException(422, 'Unknown relationship fields')
        profile = body.get('sharing_profile', 'owner_only')
        if profile not in ('owner_only', 'uk_servicing_no_us'):
            raise HTTPException(422, 'Invalid relationship sharing profile')
        email = body.get('email')
        if not isinstance(email, str) or len(email) > 254 or not email.endswith('@example.invalid'):
            raise HTTPException(422, 'Use a synthetic example.invalid email')
        if type(body.get('expected_version')) is not int:
            raise HTTPException(422, 'Expected customer version required')

        def apply(c):
            customer = self.customer(c, source, reference)
            if customer['version'] != body['expected_version']:
                raise HTTPException(409, 'Stale customer version')
            model = self.runtime.load(c)
            party = next(r for r in model['rows']['party'] if r['id'] == customer['party_id'])
            relationship = dict(id=str(uuid.uuid4()), relationship_type='PERSONAL_BANKING', status='ACTIVE')
            s = scope(self.runtime, party['id'], 'relationship', relationship['id'], profile)
            additions = dict(relationship=relationship,
                party_relationship=dict(id=str(uuid.uuid4()), party_id=party['id'], relationship_id=relationship['id'], role='HOLDER'),
                contact_info=dict(id=str(uuid.uuid4()), party_id=party['id'], channel='EMAIL', value=email, is_primary=True),
                consent=dict(id=str(uuid.uuid4()), party_id=party['id'], relationship_id=relationship['id'], channel='EMAIL', purpose='servicing', status='GRANTED'),
                preference=dict(id=str(uuid.uuid4()), party_id=party['id'], relationship_id=relationship['id'], channel='EMAIL', language='en', contact_window='09:00–17:00'))
            # Reuse the owner's contact rather than creating ambiguous duplicate EMAIL resources.
            contact = next((r for r in model['rows']['contact_info'] if r['party_id'] == party['id'] and r['channel'] == 'EMAIL'), None)
            if contact:
                additions['contact_info'] = contact
                if contact['value'] != email:
                    raise HTTPException(409, 'Update the shared contact through its existing business command')
            model['scopes'].append(s)
            for table, row in additions.items():
                if not any(r['id'] == row['id'] for r in model['rows'][table]):
                    model['rows'][table].append(row)
                    model['rules'].append(dict(resource_type=table, resource_id=row['id'],
                        allowed_countries=['SG', 'GB'], denied_countries=['US'],
                        allowed_profiles=['minimal', 'contact'], sensitivity='INTERNAL'))
                model['bindings'].append(dict(scope_id=s['id'], resource_type=table, resource_id=row['id']))
            model['bindings'].append(dict(scope_id=s['id'], resource_type='party', resource_id=party['id']))
            for table in core.ORDER:
                if table in additions:
                    self.runtime.write_business(c, table, additions[table])
            self.runtime.write_controls(c, model, [s['id']])
            self.runtime.enqueue(c, s)
            self.runtime.audit(c, s, s['owner_entity_id'], 'business_commit', 'MDM relationship and atomic export intent',actor_id=source,request_id=body['request_id'])
            return dict(global_party_id=party['global_party_id'], relationship_id=relationship['id'],
                        scope_id=s['id'], version=1, sharing_profile=profile)
        return self.transaction('relationship:' + source + ':' + self.reference(reference), body, apply)
