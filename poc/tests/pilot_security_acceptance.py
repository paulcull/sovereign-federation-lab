"""Real TLS/API/SQL acceptance for identity lifecycle, delegation and topology.

Run sequentially: registered synthetic credentials are temporarily changed and
restored in finally blocks. Nothing is printed from private config or payloads.
"""
from contextlib import contextmanager
import copy
import json
import os
from pathlib import Path
import secrets
import sys
import time
import uuid

import httpx
import psycopg

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'poc'))
sys.path.insert(0, str(ROOT / 'scripts'))
from pilot_common import tls_client
from pilot_setup import write

PRIVATE = ROOT / '.pilot'
CONFIG = json.loads((PRIVATE / 'api/config.json').read_text())
BASE = os.getenv('PILOT_URL', 'http://pilot-gateway:8080')
HTTP = httpx.Client(base_url=BASE, timeout=25, trust_env=False)


def config(role):
    return json.loads((PRIVATE / role / 'config.json').read_text())


@contextmanager
def changed(role, change):
    path = PRIVATE / role / 'config.json'
    original = config(role)
    modified = copy.deepcopy(original)
    change(modified)
    write(path, modified)
    try:
        yield modified
    finally:
        write(path, original)


def call(method, path, identity='crm-sg', body=None, status=200, headers=None):
    response = HTTP.request(method, path, json=body, headers={
        'Authorization': 'Bearer ' + CONFIG['principals'][identity]['token'], **(headers or {})})
    assert response.status_code == status, (method, response.status_code, status)
    return response.json()


def sql(query, args=()):
    with psycopg.connect('postgresql://root@db-sg:26257/defaultdb?sslmode=disable') as connection:
        return connection.execute(query, args).fetchall()


reference = 'SYN-SECURITY-' + uuid.uuid4().hex.upper()
customer = call('PUT', '/pilot/system/v1/customers/' + reference,
    body=dict(request_id=str(uuid.uuid4()), expected_version=0, display_name='Synthetic Security Acceptance',
              party_type='PERSON', identity_profile='global_minimum_no_us'))
relationship = call('POST', '/pilot/system/v1/customers/' + reference + '/relationships',
    body=dict(request_id=str(uuid.uuid4()), expected_version=1, sharing_profile='uk_servicing_no_us',
              email='security.acceptance@example.invalid'))
scope = relationship['scope_id']
path = '/pilot/experience/v1/relationships/' + scope
owner_view = call('GET', path + '?freshness=owner', 'uk-contact-only')
command = dict(request_id=str(uuid.uuid4()), expected_version=owner_view['data_version'],
               command='update_contact', value='delegated.security@example.invalid')
result = call('POST', path + '/commands', 'uk-contact-only', command)
version = result['scope_versions'][scope]
for denied in ('withdraw_consent', 'restore_consent'):
    body = dict(request_id=str(uuid.uuid4()), expected_version=version, command=denied)
    call('POST', path + '/commands', 'uk-contact-only', body, status=403)
    assert not sql('SELECT request_id FROM sovereignty.command_receipt WHERE request_id=%s', (body['request_id'],))
assert call('GET', path + '?freshness=owner', 'uk-contact-only')['data_version'] == version
print('PASS explicit contact attribute delegation succeeds; read/contact rights cannot mutate consent or create receipts')

os.environ['PILOT_CONFIG'] = str(PRIVATE / 'api/config.json')
with tls_client(CONFIG) as secure:
    body = dict(principal_id='uk-contact-only', scope_id=scope, payload=dict(request_id=str(uuid.uuid4()),
                expected_version=version, command='withdraw_consent'))
    response = secure.post('https://pilot-authority:8443/api/pilot/internal/command', json=body,
                           headers={'Authorization': 'Bearer ' + CONFIG['authority_token']})
    assert response.status_code == 403
    assert not sql('SELECT request_id FROM sovereignty.command_receipt WHERE request_id=%s', (body['payload']['request_id'],))
print('PASS owner repeats command delegation enforcement even when the authenticated API workload bypasses its facade')

for mutation in ({'revoked': True}, {'expires_at': time.time() - 1}, {'not_before': time.time() + 600}):
    with changed('api', lambda value: value['principals']['uk-contact-only'].update(mutation)):
        call('GET', '/pilot/api/v1/context', 'uk-contact-only', status=401)
    call('GET', '/pilot/api/v1/context', 'uk-contact-only')
with changed('owner', lambda value: value['principals']['uk-contact-only'].update(revoked=True)):
    call('GET', '/pilot/api/v1/context', 'uk-contact-only')
    call('GET', path + '?freshness=owner', 'uk-contact-only', status=403)
call('GET', path + '?freshness=owner', 'uk-contact-only')
print('PASS revoked, expired and future identities reject immediately; owner revocation rejects independently; recovery needs no restart')

with changed('owner', lambda value: value['identities']['api'].update(revoked=True)):
    call('GET', '/pilot/system/v1/customers/' + reference, status=401)
call('GET', '/pilot/system/v1/customers/' + reference)
new_token = secrets.token_urlsafe(32)
with changed('owner', lambda value: value['identities']['api'].update(token=new_token)):
    call('GET', '/pilot/system/v1/customers/' + reference, status=401)
    with changed('api', lambda value: value.update(authority_token=new_token)):
        call('GET', '/pilot/system/v1/customers/' + reference)
call('GET', '/pilot/system/v1/customers/' + reference)
print('PASS API workload revocation and receiver-first rotation fail closed, then recover with live outbound-token reload')

peer = config('peer-uk')
os.environ['PILOT_CONFIG'] = str(PRIVATE / 'api/config.json')
with tls_client(CONFIG) as secure:
    with changed('peer-uk', lambda value: value['import_credential'].update(revoked=True)):
        response = secure.post('https://pilot-peer-uk:8443/internal/import', json={},
                               headers={'Authorization': 'Bearer ' + peer['import_token']})
        assert response.status_code == 401
    response = secure.post('https://pilot-peer-uk:8443/internal/import', json={},
                           headers={'Authorization': 'Bearer ' + peer['import_token']})
    assert response.status_code == 422
    service = config('servicing')
    with changed('servicing', lambda value: value['export_identities']['peer-uk'].update(revoked=True)):
        response = secure.get('https://pilot-servicing:8443/service/internal/v1/cases/' + str(uuid.uuid4()) + '/export',
                              headers={'Authorization': 'Bearer ' + service['export_identities']['peer-uk']['token']})
        assert response.status_code == 401
print('PASS importer and independent case-export credentials revoke independently before payload or record processing')

for change in (lambda value: value.update(deployment={'processing_countries': ['US']}),
               lambda value: value.update(mode='production')):
    with changed('api', change):
        call('GET', '/pilot/api/v1/context', 'uk-contact-only', status=503,
             headers={'X-Processing-Country': 'SG', 'X-Entity-ID': 'LE-SG-01'})
    call('GET', '/pilot/api/v1/context', 'uk-contact-only')
print('PASS unsupported processing topology and requested production mode fail closed; caller geography headers cannot repair registration')
print('PASS real pilot identity/delegation/lifecycle acceptance; private fixtures restored')
