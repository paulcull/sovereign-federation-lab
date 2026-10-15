"""Real HTTP/CockroachDB/OPA conformance for an independently owned service.

Run via the Compose tools container after the pilot+case schemas/services start.
Faults touch only the new service's audit privilege and OPA package; finally
blocks restore both. No mocks, SQLite, core policy edits or container restarts.
"""
import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys
import uuid
from urllib.parse import quote

import httpx
import psycopg
from psycopg.errors import InsufficientPrivilege

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'poc'))
api = json.loads((ROOT / '.pilot/api/config.json').read_text())
service = json.loads((ROOT / '.pilot/servicing/config.json').read_text())
peer = json.loads((ROOT / '.pilot/peer-uk/config.json').read_text())
client = httpx.Client(base_url=os.getenv('PILOT_URL', 'http://pilot-gateway:8080'), timeout=25, trust_env=False)


def token(identity):
    for identities in (api['principals'], service['principals'], peer['servicing_principals']):
        if identity in identities:
            return identities[identity]['token']
    raise AssertionError('Unknown test identity')


def call(method, path, identity='case-owner', body=None, status=200):
    headers = {'Authorization': 'Bearer ' + token(identity)} if identity else {}
    response = client.request(method, path, headers=headers, json=body)
    assert response.status_code == status, (method, path.split('?')[0], response.status_code, status)
    return response.json()


def sql(query, args=(), region='sg', role='root'):
    with psycopg.connect(f'postgresql://{role}@db-{region}:26257/defaultdb?sslmode=disable') as connection:
        cursor = connection.execute(query, args)
        return cursor.fetchall() if cursor.description else []


def counts(case_id):
    result = {}
    for table, key in [('case_record', 'case_id'), ('aggregate_version', 'aggregate_id'),
                       ('state_outbox', 'aggregate_id'), ('transition_event', 'aggregate_id'),
                       ('transaction_audit', 'aggregate_id')]:
        result[table] = sql(f'SELECT count(*) FROM servicing.{table} WHERE {key}=%s', (case_id,))[0][0]
    result['request_receipt'] = sql("SELECT count(*) FROM servicing.request_receipt WHERE result->>'case_id'=%s", (case_id,))[0][0]
    return result


reference = 'SYN-CASE-' + uuid.uuid4().hex.upper()
customer = call('PUT', '/pilot/system/v1/customers/' + reference, 'crm-sg', dict(request_id=str(uuid.uuid4()),
    expected_version=0, display_name='Synthetic Independent Case Customer', party_type='PERSON', identity_profile='owner_only'))
relationship = call('POST', '/pilot/system/v1/customers/' + reference + '/relationships', 'crm-sg',
    dict(request_id=str(uuid.uuid4()), expected_version=customer['version'],
         sharing_profile='uk_servicing_no_us', email='independent.case@example.invalid'))
case_id = str(uuid.uuid4())
body = dict(request_id=str(uuid.uuid4()), case_id=case_id, expected_version=0,
            global_party_id=customer['global_party_id'], relationship_scope_id=relationship['scope_id'], category='CONTACT_REVIEW')
source_path = '/service/system/v1/cases/' + case_id
peer_path = '/service/experience/v1/cases/' + case_id

call('POST', '/service/system/v1/cases', identity=None, body=body, status=401)
call('POST', '/service/system/v1/cases', 'case-reader', body, status=403)
call('POST', '/service/system/v1/cases', body={**body, 'owner_entity_id': 'LE-US-01'}, status=422)
wrong_association = {**body, 'case_id': str(uuid.uuid4()), 'request_id': str(uuid.uuid4()), 'global_party_id': str(uuid.uuid4())}
call('POST', '/service/system/v1/cases', body=wrong_association, status=403)
assert all(value == 0 for value in counts(wrong_association['case_id']).values())

created = call('POST', '/service/system/v1/cases', body=body)
assert created['status'] == 'OPEN' and created['data_version'] == 1
assert all(value == 1 for value in counts(case_id).values())
assert call('POST', '/service/system/v1/cases', body=body)['idempotent_replay']
call('POST', '/service/system/v1/cases', body={**body, 'category': 'DOCUMENT_REVIEW'}, status=409)
assert all(value == 1 for value in counts(case_id).values())
source = call('GET', source_path, 'case-reader')
assert source['mdm_owner_entity_id'] == 'LE-SG-01' and source['global_party_id'] == customer['global_party_id']
assert source['delivery'] == {'mode': 'explicit_recipient_refresh', 'pending_intents': 1}
assert sql('SELECT count(*) FROM sovereignty.scope WHERE id=%s', (case_id,))[0][0] == 0
print('PASS independent business schema, immutable owner-qualified MDM association, action delegation and atomic contract')

for query, role in [("UPDATE servicing.case_record SET status='CLOSED' WHERE case_id=%s", 'sfl_servicing_reader'),
                    ('SELECT id FROM business.party WHERE id=%s', 'sfl_servicing')]:
    try:
        sql(query, (case_id,), role=role)
    except InsufficientPrivilege:
        pass
    else:
        raise AssertionError('Unsupported service SQL access was permitted')
assert call('GET', source_path)['status'] == 'OPEN'
print('PASS SQL privilege boundaries for service and unsupported reader writes (insecure-cluster identity remains a lab limitation)')

call('GET', peer_path, 'case-uk-reader', status=409)
call('POST', peer_path + '/refresh', 'case-us-reader', status=403)
assert sql('SELECT count(*) FROM servicing_projection.case_state WHERE case_id=%s', (case_id,), region='uk')[0][0] == 0
refreshed = call('POST', peer_path + '/refresh', 'case-uk-reader')
assert set(refreshed['row']) == {'case_id', 'status', 'category', 'data_version'}
assert call('GET', peer_path, 'case-uk-reader') == refreshed
assert call('GET', source_path)['delivery']['pending_intents'] == 0
for table in ('case_state', 'inbox', 'import_audit'):
    assert sql(f'SELECT count(*) FROM servicing_projection.{table} WHERE case_id=%s', (case_id,), region='uk')[0][0] == 1
call('POST', peer_path + '/refresh', 'case-uk-reader')
assert sql('SELECT count(*) FROM servicing_projection.inbox WHERE case_id=%s', (case_id,), region='uk')[0][0] == 1
print('PASS explicit UK refresh, exact four-field source export, independent projection/inbox/audit, source acknowledgement and US exclusion')

close = dict(request_id=str(uuid.uuid4()), expected_version=1, command='close')
before = counts(case_id)
sql('REVOKE INSERT ON TABLE servicing.transaction_audit FROM sfl_servicing')
try:
    call('POST', source_path + '/commands', body=close, status=503)
    assert counts(case_id) == before
    assert sql('SELECT status,data_version FROM servicing.case_record WHERE case_id=%s', (case_id,))[0] == ('OPEN', 1)
finally:
    sql('GRANT INSERT ON TABLE servicing.transaction_audit TO sfl_servicing')
closed = call('POST', source_path + '/commands', body=close)
assert closed['status'] == 'CLOSED' and closed['data_version'] == 2
assert call('POST', source_path + '/commands', body=close)['idempotent_replay']
call('POST', source_path + '/commands', body={**close, 'request_id': str(uuid.uuid4())}, status=409)
call('GET', peer_path, 'case-uk-reader', status=409)
call('POST', source_path + '/commands', body=dict(request_id=str(uuid.uuid4()), expected_version=2, command='reopen'))
call('POST', source_path + '/commands', body=dict(request_id=str(uuid.uuid4()), expected_version=3, command='close'))
latest = call('POST', peer_path + '/refresh', 'case-uk-reader')
assert latest['row']['data_version'] == 4 and latest['row']['status'] == 'CLOSED'
assert sql('SELECT data_version FROM servicing.transition_event WHERE aggregate_id=%s ORDER BY data_version', (case_id,)) == [(1,), (2,), (3,), (4,)]
assert sql('SELECT data_version FROM servicing_projection.inbox WHERE case_id=%s ORDER BY data_version', (case_id,), region='uk') == [(1,), (4,)]
assert call('GET', source_path)['delivery']['pending_intents'] == 0
print('PASS mandatory-audit failure rollback, exact retry, stale-command rejection, current-state convergence and retained every-transition ledger')

# A privileged bypass can violate a business version contract. The recipient
# must fence it instead of overwriting a committed row/audit under the same version.
before_projection = sql('SELECT data_version,payload_hash,row_data FROM servicing_projection.case_state WHERE case_id=%s', (case_id,), region='uk')
before_imports = sql('SELECT data_version,payload_hash FROM servicing_projection.import_audit WHERE case_id=%s ORDER BY data_version', (case_id,), region='uk')
sql("UPDATE servicing.case_record SET status='OPEN' WHERE case_id=%s", (case_id,))
try:
    call('POST', peer_path + '/refresh', 'case-uk-reader', status=409)
    call('GET', peer_path, 'case-uk-reader', status=409)
    assert sql('SELECT data_version,payload_hash,row_data FROM servicing_projection.case_state WHERE case_id=%s', (case_id,), region='uk') == before_projection
    assert sql('SELECT data_version,payload_hash FROM servicing_projection.import_audit WHERE case_id=%s ORDER BY data_version', (case_id,), region='uk') == before_imports
finally:
    sql("UPDATE servicing.case_record SET status='CLOSED' WHERE case_id=%s", (case_id,))
print('PASS same-version different-content rejection preserves committed UK projection and import audit')

race_body = {**body, 'case_id': str(uuid.uuid4()), 'request_id': str(uuid.uuid4())}
call('POST', '/service/system/v1/cases', body=race_body)
race_path = '/service/system/v1/cases/' + race_body['case_id'] + '/commands'
def concurrent_close(_):
    return client.post(race_path, headers={'Authorization': 'Bearer ' + token('case-owner')},
        json=dict(request_id=str(uuid.uuid4()), expected_version=1, command='close')).status_code
with ThreadPoolExecutor(max_workers=2) as pool:
    statuses = sorted(pool.map(concurrent_close, range(2)))
assert statuses == [200, 409], statuses
assert sql('SELECT status,data_version FROM servicing.case_record WHERE case_id=%s', (race_body['case_id'],))[0] == ('CLOSED', 2)
assert sql('SELECT data_version FROM servicing.transition_event WHERE aggregate_id=%s ORDER BY data_version', (race_body['case_id'],)) == [(1,), (2,)]
print('PASS concurrent business commands serialize against current row/version and retain one committed transition')

# Remove/change only this service package in a real OPA server. Existing federation
# and operational packages remain untouched, and the original raw policy is restored.
for region, method, path, identity in [('sg', 'GET', source_path, 'case-owner'), ('uk', 'GET', peer_path, 'case-uk-reader')]:
    with httpx.Client(base_url=f'http://opa-{region}:8181', timeout=5, trust_env=False) as opa:
        policies = opa.get('/v1/policies').json()['result']
        selected = [p for p in policies if p['id'].endswith('servicing.rego')]
        assert len(selected) == 1
        policy_path = '/v1/policies/' + quote(selected[0]['id'], safe='/')
        original = opa.get(policy_path).json()['result']['raw']
        try:
            opa.put(policy_path, content='package servicing\nimport rego.v1\ndecision := {"allow": false, "revision": 2, "fields": []}\n').raise_for_status()
            call(method, path, identity, status=403)
            opa.delete(policy_path).raise_for_status()
            call(method, path, identity, status=503)
        finally:
            opa.put(policy_path, content=original).raise_for_status()
assert call('GET', peer_path, 'case-uk-reader')['row'] == latest['row']
print('PASS source and recipient real OPA deny/missing-policy fail closed; original package restored')
print('PASS independent servicing integration: real business transactions, MDM consumption and explicit UK materialization')
