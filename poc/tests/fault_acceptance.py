"""Real service-outage checks. Stop the named dependency before each mode.

Run only on the synthetic lab, after the main suite and without manual edits.
"""
import argparse
import os
import time
import uuid
import httpx
import psycopg

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('mode', choices=['telemetry', 'policy', 'recovered'])
args = parser.parse_args()
client = httpx.Client(base_url=os.getenv('POC_URL', 'http://gateway:8080'), timeout=30, trust_env=False)

def sql(region, query, values=()):
    with psycopg.connect(os.environ['DB_' + region]) as c:
        return c.execute(query, values).fetchall()

def unavailable(url):
    try:
        httpx.get(url, timeout=2, trust_env=False)
    except httpx.TransportError:
        return
    raise AssertionError('Dependency was not stopped: ' + url)

if args.mode == 'telemetry':
    unavailable('http://otel-collector:4318')
    assert client.get('/api/health/ready').status_code == 200
    model = client.get('/api/operational').json()['model']
    scope = next(s for s in model['scopes'] if s['scope_kind'] == 'relationship' and 'Personal' in s['name'])
    before = sql('SG', 'SELECT count(*) FROM business.contact_history')[0][0]
    audit_before = sql('SG', "SELECT count(*) FROM sovereignty.audit WHERE doc->>'status'='business_commit'")[0][0]
    request = str(uuid.uuid4())
    body = dict(command='log_contact', request_id=request, expected_version=scope['data_version'])
    response = client.post('/api/operational/scopes/' + scope['id'] + '/commands', json=body)
    assert response.status_code == 200, response.status_code
    assert sql('SG', 'SELECT count(*) FROM business.contact_history')[0][0] == before + 1
    assert sql('SG', "SELECT count(*) FROM sovereignty.audit WHERE doc->>'status'='business_commit'")[0][0] == audit_before + 1
    assert sql('SG', 'SELECT count(*) FROM sovereignty.command_receipt WHERE request_id=%s', (request,))[0][0] == 1
    replay = client.post('/api/operational/scopes/' + scope['id'] + '/commands', json=body)
    assert replay.status_code == 200 and replay.json()['idempotent_replay']
    print('PASS real Collector outage: business row, mandatory SQL audit and idempotency receipt commit together; readiness remains independent')
elif args.mode == 'policy':
    unavailable('http://opa-sg:8181')
    assert client.get('/api/health/ready').status_code == 503
    created = client.post('/api/generate', json={'count': 1, 'scenario': 'sg-uk-no-us'})
    assert created.status_code == 200
    record = created.json()['created'][0]
    deadline = time.monotonic() + 30
    while True:
        tasks = sql('SG', 'SELECT status,attempts FROM fe_outbox WHERE record_id=%s', (record['id'],))
        if tasks and all(status == 'retry' and attempts > 0 for status, attempts in tasks):
            break
        assert time.monotonic() < deadline, 'Missing durable retry after actual OPA outage'
        time.sleep(.2)
    for region in ['UK', 'US']:
        assert sql(region, 'SELECT count(*) FROM fe_replicas WHERE customer=%s', (record['global_customer_id'],))[0][0] == 0
        assert sql(region, 'SELECT count(*) FROM fe_fences WHERE customer=%s', (record['global_customer_id'],))[0][0] == 0
    assert client.get('/api/records/' + record['id'] + '/read/LE-GB-02').status_code == 503
    print('PASS real source OPA outage: exports and recipient read fail closed; no remote payload/fence; source outbox remains retryable')
else:
    assert client.get('/api/health/ready').status_code == 200
    deadline = time.monotonic() + 45
    while True:
        current = client.get('/api/state').json()
        if not current['queue']:
            break
        assert time.monotonic() < deadline, 'Outbox did not recover after dependency restart'
        time.sleep(.2)
    assert all(s['online'] for s in current['stores'])
    print('PASS actual OPA/Collector restart: SQL stores ready and durable outboxes drain')
