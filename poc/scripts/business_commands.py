"""Synthetic operational command generator. Uses v3 local API, never direct SQL."""
import argparse,json,time,uuid,urllib.request
p=argparse.ArgumentParser();p.add_argument('--url',default='http://127.0.0.1:8000');p.add_argument('--scope',help='Scope UUID; default first relationship');p.add_argument('--command',default='open_holding',choices=['update_contact','open_holding','log_contact','withdraw_consent','restore_consent','exclude_party_us','restore_party_us','table_contact_local','table_contact_restore']);p.add_argument('--count',type=int,default=1);p.add_argument('--interval',type=float,default=2);a=p.parse_args()
if not 1<=a.count<=100 or a.interval<0:p.error('Use count 1–100 and nonnegative interval')
def call(path,body=None):
    req=urllib.request.Request(a.url+'/api'+path,data=json.dumps(body).encode() if body else None,headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(req,timeout=30) as r:return json.load(r)
for i in range(a.count):
    m=call('/operational')['model'];s=next((s for s in m['scopes'] if s['id']==a.scope),None) if a.scope else next(s for s in m['scopes'] if s['scope_kind']=='relationship')
    if not s:p.error('Scope not found')
    result=call('/operational/scopes/'+s['id']+'/commands',dict(command=a.command,expected_version=s['data_version'],request_id=str(uuid.uuid4()),value=f'generated.{i}.{uuid.uuid4().hex[:6]}@example.invalid'))
    print(json.dumps(result),flush=True)
    if i+1<a.count:time.sleep(a.interval)
