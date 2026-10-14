"""Real CockroachDB, OPA, TLS peers and system/experience API acceptance."""
import json
import os
from pathlib import Path
import sys
import time
import uuid

import httpx
import psycopg

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'poc'))
import operational_core as core
from pilot_common import configuration, tls_client

config = json.loads((ROOT / '.pilot/api/config.json').read_text())
base = os.getenv('PILOT_URL', 'http://pilot-gateway:8080')
client = httpx.Client(base_url=base, timeout=25, trust_env=False)


def call(method, path, identity='crm-sg', body=None, status=200, headers=None):
    actual = {'Authorization': 'Bearer ' + config['principals'][identity]['token']} if identity else {}
    actual.update(headers or {})
    response = client.request(method, path, headers=actual, json=body)
    assert response.status_code == status, (method, path.split('?')[0], response.status_code, status)
    if status == 200:
        assert len(response.headers.get('X-Trace-ID', '')) == 32
    return response.json()


def eventually(path, identity, predicate, seconds=40):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        response = client.get(path, headers={'Authorization': 'Bearer ' + config['principals'][identity]['token']})
        if response.status_code == 200 and predicate(response.json()):
            return response.json()
        time.sleep(.4)
    raise AssertionError('Approved HTTP projection did not converge')


def sql(region, query, args=()):
    with psycopg.connect(f'postgresql://root@db-{region}:26257/defaultdb?sslmode=disable') as c:
        return c.execute(query, args).fetchall()


call('GET', '/pilot/api/v1/context', identity=None, status=401)
call('GET', '/pilot/api/v1/context', identity=None, headers={'Authorization': 'Bearer invalid'}, status=401)
assert client.get('/api/operational').status_code == 404
assert client.post('/internal/import', json={}).status_code == 404
call('GET', '/pilot/system/v1/customers/SYN-ASTER', 'uk-servicing', status=403)
context = call('GET', '/pilot/api/v1/context', 'uk-servicing', headers={'X-Entity-ID': 'LE-SG-01', 'X-Processing-Country': 'SG'})
assert context['entity_id'] == 'LE-GB-02' and context['processing_country'] == 'GB'
print('PASS credential, role, header-spoof and gateway bypass rejection')

reference = 'SYN-' + uuid.uuid4().hex.upper()
body = dict(request_id=str(uuid.uuid4()), expected_version=0, display_name='Synthetic Pilot Canary',
            party_type='PERSON', identity_profile='global_minimum')
customer = call('PUT', '/pilot/system/v1/customers/' + reference, body=body)
replay = call('PUT', '/pilot/system/v1/customers/' + reference, body=body)
assert replay['idempotent_replay'] and replay['global_party_id'] == customer['global_party_id']
call('PUT', '/pilot/system/v1/customers/' + reference, body={**body, 'display_name': 'Synthetic Conflicting Replay'}, status=409)
call('PUT', '/pilot/system/v1/customers/' + reference, body={**body, 'request_id': str(uuid.uuid4()), 'owner_entity_id': 'LE-GB-02'}, status=422)
source = call('GET', '/pilot/system/v1/customers/' + reference)
assert source['owner_entity_id'] == 'LE-SG-01'
assert sql('sg', 'SELECT count(*) FROM mdm.source_reference WHERE external_reference=%s', (reference,))[0][0] == 1
assert sql('sg', 'SELECT count(*) FROM mdm.request_receipt WHERE request_id=%s', (body['request_id'],))[0][0] == 1
assert sql('sg',"SELECT count(*) FROM sovereignty.audit WHERE doc->>'request_id'=%s AND doc->>'actor_id'='crm-sg'",(body['request_id'],))[0][0] >= 1
assert sql('sg', 'SELECT count(*) FROM sovereignty.audit WHERE doc->>\'record_id\'=%s', (customer['party_scope_id'],))[0][0] >= 1
assert sql('sg', 'SELECT count(*) FROM sovereignty.outbox WHERE scope_id=%s', (customer['party_scope_id'],))[0][0] >= 3
print('PASS real MDM source-reference, business row, audit, outbox and idempotent receipt')

relation_body = dict(request_id=str(uuid.uuid4()), expected_version=source['version'],
                     sharing_profile='uk_servicing_no_us', email='pilot.canary@example.invalid')
relation = call('POST', '/pilot/system/v1/customers/' + reference + '/relationships', body=relation_body)
assert call('POST', '/pilot/system/v1/customers/' + reference + '/relationships', body=relation_body)['idempotent_replay']
gid, sid = customer['global_party_id'], relation['scope_id']
customer_path = '/pilot/experience/v1/customers/' + gid
relationship_path = '/pilot/experience/v1/relationships/' + sid
uk = eventually(relationship_path, 'uk-servicing', lambda view: any(r['table'] == 'contact_info' for r in view['rows']))
assert uk['served_from'] == 'projection' and uk['scope_kind'] == 'relationship'
us = eventually(customer_path, 'us-reader', lambda view: bool(view['views']))
assert len(us['views']) == 1 and us['views'][0]['scope_kind'] == 'party'
assert len(us['views'][0]['rows']) == 1
assert set(us['views'][0]['rows'][0]['row']) == {'id', 'global_party_id', 'party_type'}
call('GET', relationship_path, 'us-reader', status=403)
call('GET', relationship_path, 'uk-from-us', status=403)
call('GET', relationship_path, 'uk-business', status=403)
assert sql('us', 'SELECT count(*) FROM sovereignty.manifest WHERE scope_id=%s', (sid,))[0][0] == 0
assert sql('us', 'SELECT count(*) FROM sovereignty.audit WHERE doc->>\'record_id\'=%s', (sid,))[0][0] == 0
assert sql('us', 'SELECT count(*) FROM projection.relationship WHERE scope_id=%s', (sid,))[0][0] == 0
print('PASS HTTP peer UK contact projection, exact US party minimum, independent relationship and processing exclusions')

minimum_path = relationship_path + '?minimum_data_version=999999'
call('GET', minimum_path, 'uk-servicing', status=409)
latest = call('GET', relationship_path + '?freshness=owner', 'uk-servicing')
assert latest['served_from'] == 'owner' and all('balance' not in row['row'] for row in latest['rows'])
update = dict(request_id=str(uuid.uuid4()), expected_version=latest['data_version'],
              command='update_contact', value='updated.pilot@example.invalid')
result = call('POST', relationship_path + '/commands', 'uk-servicing', update)
assert call('POST', relationship_path + '/commands', 'uk-servicing', update)['idempotent_replay']
call('POST', relationship_path + '/commands', 'uk-servicing', {**update, 'request_id': str(uuid.uuid4())}, status=409)
version = result['scope_versions'][sid]
uk = eventually(relationship_path + '?minimum_data_version=' + str(version), 'uk-servicing',
    lambda view: any(r['table'] == 'contact_info' and r['row']['value'] == update['value'] for r in view['rows']))
assert sql('sg', 'SELECT count(*) FROM sovereignty.command_receipt WHERE request_id=%s', (update['request_id'],))[0][0] == 1
assert sql('sg',"SELECT count(*) FROM sovereignty.audit WHERE doc->>'request_id'=%s AND doc->>'actor_id'='uk-servicing'",(update['request_id'],))[0][0] >= 1
print('PASS routed owner command, exact replay, stale write rejection and minimum-version projection read')

withdraw = dict(request_id=str(uuid.uuid4()), expected_version=uk['data_version'], command='withdraw_consent')
withdrawn = call('POST', relationship_path + '/commands', 'uk-servicing', withdraw)
view = eventually(relationship_path, 'uk-servicing', lambda value: all(r['table'] not in ('contact_info','preference') for r in value['rows']))
assert not sql('uk', 'SELECT id FROM projection.contact_info WHERE scope_id=%s', (sid,))
restore = dict(request_id=str(uuid.uuid4()), expected_version=withdrawn['scope_versions'][sid], command='restore_consent')
call('POST', relationship_path + '/commands', 'uk-servicing', restore)
eventually(relationship_path, 'uk-servicing', lambda value: any(r['table'] == 'contact_info' for r in value['rows']))
print('PASS consent revocation, guarded reads, actual UK live-row removal and restoration')

# A valid API certificate does not grant importer authority; missing client cert fails TLS.
os.environ['PILOT_CONFIG'] = str(ROOT / '.pilot/api/config.json')
secure = tls_client(config)
response = secure.post('https://pilot-peer-uk:8443/internal/import', headers={'Authorization': 'Bearer ' + config['authority_token']}, json={})
assert response.status_code == 401
try:
    with httpx.Client(verify=str(ROOT / '.pilot/api/ca.crt'), trust_env=False, timeout=3) as anonymous:
        anonymous.get('https://pilot-peer-uk:8443/healthz')
except httpx.HTTPError:
    pass
else:
    raise AssertionError('Peer accepted a connection without a client certificate')
print('PASS mutual TLS and independent importer/workload credentials')

os.environ['PILOT_CONFIG'] = str(ROOT / '.pilot/peer-us/config.json')
us_config = json.loads((ROOT / '.pilot/peer-us/config.json').read_text())
peer_client = tls_client(us_config)
binding = peer_client.post('https://pilot-authority:8443/api/pilot/internal/admission',
    headers={'Authorization':'Bearer '+us_config['authority_token']},
    json=dict(operation='read',scope_id=sid,destination_entity_id='LE-GB-02',principal_id='uk-servicing'))
assert binding.status_code == 403
os.environ['PILOT_CONFIG'] = str(ROOT / '.pilot/peer-uk/config.json')
uk_config = json.loads((ROOT / '.pilot/peer-uk/config.json').read_text())
peer_client = tls_client(uk_config)
event = sql('sg',"SELECT id FROM sovereignty.outbox WHERE scope_id=%s AND destination_entity_id='LE-GB-02' LIMIT 1",(sid,))[0][0]
tamper = peer_client.post('https://pilot-authority:8443/api/pilot/internal/admission',
    headers={'Authorization':'Bearer '+uk_config['authority_token']},
    json=dict(operation='import',scope_id=sid,destination_entity_id='LE-GB-02',event_id=str(event),digest='0'*64))
assert tamper.status_code == 409
print('PASS authenticated cross-store peer spoof and tampered current-envelope rejection')

private_ref = 'SYN-PRIVATE-' + uuid.uuid4().hex.upper()
private = call('PUT','/pilot/system/v1/customers/'+private_ref,body=dict(request_id=str(uuid.uuid4()),
    expected_version=0,display_name='Synthetic Private Customer',party_type='PERSON'))
call('GET','/pilot/experience/v1/customers/'+private['global_party_id'],'us-reader',status=404)
assert sql('us','SELECT count(*) FROM projection.party WHERE id=%s',(private['party_id'],))[0][0] == 0
print('PASS new customer defaults to owner-only; source references do not grant global distribution')

print('PASS runnable synthetic MDM pilot: real SQL/OPA, system APIs, experience APIs and HTTP recipient peers')
