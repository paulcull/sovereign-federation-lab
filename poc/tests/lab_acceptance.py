"""Container acceptance against actual CockroachDB, not SQLite or an HTTP mock.

Default resets only the isolated synthetic India migration. Original federation
and normalized-data acceptance live in integration.py / operational_integration.py.
"""
import argparse,hashlib,json,os,time,uuid
from pathlib import Path
import httpx,psycopg
p=argparse.ArgumentParser();p.add_argument('--smoke',action='store_true');p.add_argument('--restart-check',action='store_true');args=p.parse_args()
base=os.getenv('POC_URL','http://gateway:8080').rstrip('/');http=httpx.Client(base_url=base,timeout=60,trust_env=False)
def get(path):
    r=http.get(path);r.raise_for_status();return r.json()
def post(action,body=None,status=200):
    r=http.post('/api/migration/'+action,json=body or {});assert r.status_code==status,(action,r.status_code,r.text);return r.json()
def sql(region,query,values=()):
    with psycopg.connect(os.environ['DB_'+region],connect_timeout=3) as c:return c.execute(query,values).fetchall()
def state():return get('/api/migration')
def smoke():
    health=get('/api/health/ready');assert health['database']=='cockroach' and len(health['stores'])==4
    assert all(s['database'] and s['policy'] for s in health['stores'])
    assert get('/lab-config.json')['mode']=='live'
    for path in ['/','/monitor.html','/migration.html','/design/adr-register.html','/design/development-lab.html','/api-docs']:
        r=http.get(path);assert r.status_code==200,(path,r.status_code)
    for path in ['/lab-mode.mjs','/migration/app.mjs','/migration/engine.mjs','/isolation/app.mjs']:
        r=http.get(path);assert r.status_code==200 and r.headers['content-type'].split(';')[0] in ('application/javascript','text/javascript'),(path,r.status_code,r.headers.get('content-type'))
    for region in ['SG','UK','US','IN']:assert 'CockroachDB' in sql(region,'SELECT version()')[0][0]
    assert state()['mode']=='persistent-cockroach' and state()['policy_engine']=='OPA'
    print('PASS gateway/static/API navigation, four actual CockroachDB identities and four OPA readiness decisions.')
smoke()
if args.smoke:raise SystemExit(0)
if not args.restart_check:
    post('reset',{'scenario':'synthetic-india'})
    post('register');post('conflict',{'blocked':True});post('plan',status=409)
    post('conflict',{'blocked':False});post('plan');post('start')
    assert http.get('/api/migration/read/IN').status_code==409
    post('copy');post('write',{'kind':'create','request_id':str(uuid.uuid4())});post('write',{'kind':'update','request_id':'lab-retry'});post('write',{'kind':'delete'})
    post('pause',{'paused':True});post('copy',status=409);post('write');post('other');post('pause',{'paused':False})
    while state()['phase']=='COPYING':post('copy')
    while state()['delta_lag']:post('catchup')
    post('validate');post('write');assert state()['phase']=='CATCHING_UP'
    while state()['delta_lag']:post('catchup')
    post('validate');post('fence');post('write',status=409);post('other');post('activate')
    assert post('write',{'kind':'update','request_id':'lab-retry'})['replayed']
    assert post('write')['home']=='IN';post('write',{'store':'SG'},409);post('write',{'expected_epoch':1},409);post('stale',status=409);post('rollback',status=409)
    post('deadline')
    while state()['phase']!='COMPLETE':post('cleanup')
assert state()['phase']=='COMPLETE' and state()['home']=='IN'
assert sql('SG','SELECT count(*) FROM mig_rows WHERE owner=%s',('LE-IN-01',))[0][0]==0
for table in ['mig_journal','mig_receipts']:
    assert sql('SG',f'SELECT count(*) FROM {table} WHERE owner=%s',('LE-IN-01',))[0][0]==0
assert sql('SG','SELECT count(*) FROM mig_snapshot WHERE job=%s',(state()['job'],))[0][0]==0
assert sql('US','SELECT count(*) FROM mig_rows WHERE owner=%s',('LE-IN-01',))[0][0]==0
assert sql('IN','SELECT count(*) FROM mig_rows WHERE owner=%s',('LE-IN-01',))[0][0]==61
assert sql('SG','SELECT writable FROM mig_authority WHERE owner=%s',('LE-IN-01',))[0][0]==0
assert sql('IN','SELECT epoch,writable FROM mig_authority WHERE owner=%s',('LE-IN-01',))[0]==(2,1)
if not args.restart_check:
    assert post('write')['home']=='IN'
checkpoint=Path(os.getenv('TELEMETRY_DIR','/tmp'))/'acceptance-restart.json'
evidence={
    'india_contents':hashlib.sha256(json.dumps(sql('IN','SELECT id,version,doc FROM mig_rows WHERE owner=%s ORDER BY id',('LE-IN-01',)),sort_keys=True).encode()).hexdigest(),
    'masters':{region:sql(region,'SELECT record_id,doc FROM fe_masters ORDER BY record_id') for region in ['SG','UK','US']},
    'business_scopes':sql('SG','SELECT id,doc FROM sovereignty.scope ORDER BY id'),
    'command_receipts':sql('SG','SELECT request_id,result FROM sovereignty.command_receipt ORDER BY request_id'),
}
# Compare persisted business state, not only counts or an HTTP liveness response.
digest=hashlib.sha256(json.dumps(evidence,sort_keys=True,default=str).encode()).hexdigest()
if args.restart_check:
    assert checkpoint.read_text()==digest,'Business rows, command receipts or India contents changed across API restart'
    assert post('write',{'kind':'update','request_id':'lab-retry'})['replayed']
else:
    checkpoint.write_text(digest)
if args.restart_check:
    assert post('write')['home']=='IN'
print('PASS actual SQL evidence: only India writable, 61 versioned envelopes, zero old SG/US live payload, idempotency and restart-compatible authority.')
