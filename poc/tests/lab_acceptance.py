"""Container acceptance against actual CockroachDB, not SQLite or an HTTP mock.

Default resets only the isolated synthetic India migration. Original federation
and normalized-data acceptance live in integration.py / operational_integration.py.
"""
import argparse,json,os,time,uuid
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
    for region in ['SG','UK','US','IN']:assert 'CockroachDB' in sql(region,'SELECT version()')[0][0]
    assert state()['mode']=='persistent-cockroach' and state()['policy_engine']=='OPA'
    print('PASS gateway/static/API navigation, four actual CockroachDB identities and four OPA readiness decisions.')
smoke()
if args.smoke:raise SystemExit(0)
if not args.restart_check:
    post('reset',{'scenario':'synthetic-india'})
    for action in ['register','plan','start']:post(action)
    post('copy');post('write',{'kind':'create','request_id':str(uuid.uuid4())});post('write',{'kind':'update','request_id':'lab-retry'});post('write',{'kind':'delete'})
    post('pause',{'paused':True});post('copy',status=409);post('write');post('other');post('pause',{'paused':False})
    while state()['phase']=='COPYING':post('copy')
    while state()['delta_lag']:post('catchup')
    post('validate');post('write');assert state()['phase']=='CATCHING_UP'
    while state()['delta_lag']:post('catchup')
    post('validate');post('fence');post('write',status=409);post('other');post('activate')
    assert post('write',{'kind':'update','request_id':'lab-retry'})['replayed']
    assert post('write')['home']=='IN';post('write',{'store':'SG'},409);post('stale',status=409);post('rollback',status=409)
    post('deadline')
    while state()['phase']!='COMPLETE':post('cleanup')
assert state()['phase']=='COMPLETE' and state()['home']=='IN'
assert sql('SG','SELECT count(*) FROM mig_rows WHERE owner=%s',('LE-IN-01',))[0][0]==0
assert sql('US','SELECT count(*) FROM mig_rows WHERE owner=%s',('LE-IN-01',))[0][0]==0
assert sql('IN','SELECT count(*) FROM mig_rows WHERE owner=%s',('LE-IN-01',))[0][0]==61
assert sql('SG','SELECT writable FROM mig_authority WHERE owner=%s',('LE-IN-01',))[0][0]==0
assert sql('IN','SELECT epoch,writable FROM mig_authority WHERE owner=%s',('LE-IN-01',))[0]==(2,1)
assert post('write')['home']=='IN'
print('PASS actual SQL evidence: only India writable, 61 versioned envelopes, zero old SG/US live payload, idempotency and restart-compatible authority.')
