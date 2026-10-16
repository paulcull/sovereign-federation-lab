"""Actual CockroachDB identities, guarded operations and native backup/restore."""
import argparse
import json
import os
from pathlib import Path
import time
import uuid
import httpx
import psycopg
from psycopg.types.json import Jsonb

p = argparse.ArgumentParser()
p.add_argument('--phase', choices=['normal', 'paused', 'restart'], default='normal')
phase = p.parse_args().phase
h = httpx.Client(base_url=os.getenv('POC_URL', 'http://gateway:8080'), timeout=20, trust_env=False)
base = '/api/cluster-control'
headers = {'X-Lab-Control': '1'}
checkpoint = Path(os.getenv('TELEMETRY_DIR', '/tmp')) / 'cluster-control-acceptance.json'

def jobs(key):
    r = h.get(base + '/clusters/' + key + '/operations'); r.raise_for_status()
    assert r.json()['available']
    return r.json()['jobs']

def submit(key, kind):
    body = {'kind': kind, 'request_id': str(uuid.uuid4()), 'confirmation': key}
    r = h.post(base + '/clusters/' + key + '/operations', json=body, headers=headers)
    assert r.status_code == 202, r.text
    return r.json()['id'], body

def wait(key, jid):
    end = time.monotonic() + 65
    while time.monotonic() < end:
        job = next(j for j in jobs(key) if j['id'] == jid)
        if job['state'] not in ('queued', 'running'):
            assert job['state'] == 'succeeded', job
            assert all(s['state'] == 'succeeded' for s in job['steps'])
            return job
        time.sleep(.3)
    raise AssertionError('Operation did not finish')

r = h.get(base + '/clusters'); r.raise_for_status(); inventory = r.json()
assert inventory['mode'] == 'live'
clusters = {c['id']: c for c in inventory['clusters']}
assert set(clusters) == {'sg', 'uk', 'us', 'in'}
text = json.dumps(inventory)
for secret in ('postgresql://', 'addressField', 'sqlAddress', '"env"', '"args"', '"email"', '"password"'):
    assert secret not in text, secret

if phase == 'paused':
    assert clusters['in']['status'] == 'unreachable' and not clusters['in']['sql']
    assert all(clusters[k]['status'] == 'healthy' for k in ('sg', 'uk', 'us'))
    assert h.get(base + '/clusters/in/operations').json() == {'available': False, 'jobs': [], 'latest_recovery': None}
    r = h.post(base + '/clusters/in/operations', headers=headers, json={'kind': 'health_check', 'request_id': str(uuid.uuid4())})
    assert r.status_code == 503
    jid, _ = submit('uk', 'health_check'); wait('uk', jid)
    print('PASS actual paused India SQL: explicit unreachable status and failed journal; UK checks continue independently')
    raise SystemExit(0)

ids = []
for key, cluster in clusters.items():
    assert cluster['status'] == 'healthy' and cluster['locality_matches']
    assert not cluster['ha'] and not cluster['business_backup_configured']
    assert len(cluster['nodes']) == 1 and cluster['nodes'][0]['status'] == 'live'
    env = {'sg': 'SG', 'uk': 'UK', 'us': 'US', 'in': 'IN'}[key]
    with psycopg.connect(os.environ['DB_' + env]) as c:
        actual = c.execute('SELECT crdb_internal.cluster_id()::STRING').fetchone()[0]
    assert actual == cluster['cluster_id']; ids.append(actual)
assert len(set(ids)) == 4

if phase == 'restart':
    saved = json.loads(checkpoint.read_text())
    assert next(j for j in jobs('in') if j['id'] == saved['id']) == saved
    print('PASS four database identities and completed recovery journal persist across API restart')
    raise SystemExit(0)

url = base + '/clusters/in/operations'
body = {'kind': 'health_check', 'request_id': str(uuid.uuid4())}
assert h.post(url, json=body).status_code == 403
assert h.post(url, json=body, headers={**headers, 'Origin': 'https://untrusted.invalid'}).status_code == 403
assert h.post(url, json=body, headers={**headers, 'Sec-Fetch-Site': 'cross-site'}).status_code == 403
for invalid in ({**body, 'sql': 'DROP DATABASE defaultdb'}, {**body, 'kind': 'delete_cluster'}, {**body, 'kind': 'recovery_rehearsal', 'confirmation': 'sg'}):
    assert h.post(url, json=invalid, headers=headers).status_code == 422
assert h.get(base + '/clusters/unknown/operations').status_code == 404
assert h.post(base + '/clusters/unknown/operations', json=body, headers=headers).status_code == 404
jid, body = submit('in', 'health_check')
r = h.post(url, json=body, headers=headers)
assert r.status_code == 202 and r.json() == {'id': jid, 'replayed': True}
wait('in', jid)
assert h.post(url, json={**body, 'kind': 'recovery_rehearsal'}, headers=headers).status_code == 409
with psycopg.connect(os.environ['DB_IN']) as c:
    before = [r[0] for r in c.execute('SHOW DATABASES')]
jid, _ = submit('in', 'recovery_rehearsal'); job = wait('in', jid)
assert job['result']['verified_rows'] == 3 and not job['result']['business_backup']
assert job['result']['backup_scope'] == 'synthetic_canary'
with psycopg.connect(os.environ['DB_IN']) as c:
    assert before == [r[0] for r in c.execute('SHOW DATABASES')], 'Temporary database cleanup failed'
    native = c.execute('SELECT job_type,status FROM [SHOW JOBS] WHERE job_id IN (%s::INT8,%s::INT8)',
                       (job['result']['backup_job_id'], job['result']['restore_job_id'])).fetchall()
    assert ('BACKUP', 'succeeded') in native and ('RESTORE', 'succeeded') in native, native
    assert c.execute('SELECT count(*) FROM cluster_control.events WHERE job_id=%s', (jid,)).fetchone()[0] >= 12
# Metadata-only fixtures exercise a truncated history and lost completion write.
# They do not substitute for the native BACKUP/RESTORE evidence checked above.
fixture_ids = [uuid.uuid4() for _ in range(31)]
uncertain_id = uuid.uuid4()
try:
    with psycopg.connect(os.environ['DB_IN']) as c:
        c.cursor().executemany("INSERT INTO cluster_control.jobs (id,request_id,kind,state,created_at,updated_at,steps,result) VALUES (%s,%s,'health_check','succeeded',%s,%s,%s,%s)",
            [(i, uuid.uuid4(), time.time()+n+1, time.time()+n+1, Jsonb([]), Jsonb({})) for n,i in enumerate(fixture_ids)])
    history = h.get(base + '/clusters/in/operations').json()
    assert len(history['jobs']) == 30 and all(j['id'] != jid for j in history['jobs'])
    assert history['latest_recovery']['id'] == jid
    with psycopg.connect(os.environ['DB_IN']) as c:
        c.execute("INSERT INTO cluster_control.jobs (id,request_id,kind,state,created_at,updated_at,steps,result) VALUES (%s,%s,'recovery_rehearsal','running',%s,%s,%s,%s)",
                  (uncertain_id, uuid.uuid4(), time.time()+100, time.time()+100, Jsonb([{'label':'Restore and compare','state':'running'}]), Jsonb({'backup_job_id':'123'})))
    deadline = time.monotonic()+12
    while time.monotonic() < deadline:
        uncertain = next(j for j in jobs('in') if j['id'] == str(uncertain_id))
        if uncertain['state'] == 'interrupted': break
        time.sleep(.2)
    assert uncertain['state'] == 'interrupted' and uncertain['result']['backup_job_id'] == '123'
    assert h.post(url, headers=headers, json={'kind':'recovery_rehearsal','request_id':str(uuid.uuid4()),'confirmation':'in'}).status_code == 409
finally:
    with psycopg.connect(os.environ['DB_IN']) as c:
        c.execute('DELETE FROM cluster_control.events WHERE job_id = ANY(%s)', (fixture_ids+[uncertain_id],))
        c.execute('DELETE FROM cluster_control.jobs WHERE id = ANY(%s)', (fixture_ids+[uncertain_id],))
checkpoint.write_text(json.dumps(job, sort_keys=True))
deadline = time.monotonic()+20
while True:
    env = h.get(base + '/environment').json()
    if len(env['services']) == 6 and all(s['status'] == 'healthy' for s in env['services']): break
    if time.monotonic() >= deadline: raise AssertionError(env)
    time.sleep(.5)
assert env['host_count'] == 1 and not env['geography_attested']
assert len(env['services']) == 6 and all(s['status'] == 'healthy' for s in env['services'])
print('PASS actual cluster identities, sanitized metadata, cross-origin/arbitrary-operation rejection, UUID replay, native BACKUP/RESTORE, exact rows, cleanup, durable audit and separate environment probes')
