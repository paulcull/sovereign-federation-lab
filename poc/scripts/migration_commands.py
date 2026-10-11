"""Synthetic traffic and complete migration acceptance against a running local API.

The walkthrough requires a fresh DRAFT scenario and does not reset data implicitly.
"""
import argparse,json,time,uuid,urllib.request,urllib.error
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--base-url',default='http://127.0.0.1:8001')
p.add_argument('--kind',choices=['update','create','delete'],default='update')
p.add_argument('--count',type=int,default=10)
p.add_argument('--interval',type=float,default=.5)
p.add_argument('--walkthrough',action='store_true')
a=p.parse_args()
def call(action=None,body=None):
    req=urllib.request.Request(a.base_url.rstrip('/')+'/api/migration'+('/'+action if action else ''),data=json.dumps(body or {}).encode() if action else None,headers={'Content-Type':'application/json'})
    try:
        with urllib.request.urlopen(req,timeout=15) as r:return json.load(r)
    except urllib.error.HTTPError as e:raise SystemExit(f'{action} rejected ({e.code}): '+e.read().decode())
def write():
    result=call('write',{'kind':a.kind,'request_id':str(uuid.uuid4())});print(json.dumps(result));return result
if a.walkthrough:
    initial=call();assert initial['phase']=='DRAFT','Reset the synthetic scenario explicitly in the UI first'
    print('Runtime:',initial['mode'],'Policy:',initial['policy_engine'])
    for action in ['register','plan','start']:call(action)
    call('copy',{'batch':8});write();call('write',{'kind':'create'});call('write',{'kind':'delete'});call('other')
    while call()['phase']=='COPYING':call('copy')
    while call()['delta_lag']:call('catchup')
    for action in ['validate','fence','activate']:call(action)
    assert write()['home']=='IN'
    while call()['phase']!='COMPLETE':call('cleanup')
    result=call();stores={s['id']:s for s in result['stores']}
    assert stores['SG']['stored_rows']==0 and stores['US']['stored_rows']==0 and result['home']=='IN'
    print('PASS live API walkthrough: source writes, bounded copy, catch-up, cutover, India write and live-source cleanup.')
else:
    for i in range(a.count):
        write();call('other')
        if i+1<a.count:time.sleep(max(0,a.interval))
