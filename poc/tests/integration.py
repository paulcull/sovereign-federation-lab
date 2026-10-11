"""Entity federation integration suite. Run against the real local v2 stack."""
import json,time,os,urllib.request,urllib.error
URL=os.getenv('POC_URL','http://127.0.0.1:8000')
def call(path,body=None,method=None):
    req=urllib.request.Request(URL+'/api'+path,data=json.dumps(body).encode() if body is not None else None,headers={'Content-Type':'application/json'},method=method or ('POST' if body is not None else 'GET'))
    with urllib.request.urlopen(req,timeout=60) as r:return json.load(r)
def wait(predicate,message,seconds=45):
    deadline=time.time()+seconds
    while time.time()<deadline:
        s=call('/state')
        if predicate(s):return s
        time.sleep(.3)
    raise AssertionError('Timeout: '+message)
def copies(s,rid):return [p for store in s['stores'] for p in store['replicas'] if p['record_id']==rid]
def check(value,message):
    assert value,message
    print('PASS',message,flush=True)
def settled(rid):return wait(lambda s:not any(q['record_id']==rid for q in s['queue']),'queue settlement')
def denied(path,body=None,method=None,status=403):
    try:call(path,body,method)
    except urllib.error.HTTPError as e:check(e.code==status,f'{status} rejected: {path}');return
    raise AssertionError('Expected rejection: '+path)
def generate(scenario):return call('/generate',{'count':1,'scenario':scenario})['created'][0]
def run():
    cat=call('/catalog');check(len(cat['entities'])==30 and len(cat['stores'])==3,'30 legal entities and 3 physical stores')
    c=generate('sg-uk-no-us');rid=c['id'];s=settled(rid);ps=copies(s,rid)
    check(len(ps)==1 and ps[0]['destination_entity_id']=='LE-GB-02' and ps[0]['store_id']=='STORE-GB-01','SG owner → UK Markets only; US excluded')
    check(set(ps[0]['fields'])=={'name','tier'},'Minimal fields; owner-only email/notes absent')
    denied(f'/records/{rid}/read/LE-US-01')
    denied(f'/records/{rid}/relationship',{'owner_entity_id':'LE-US-01'})
    sibling=call(f'/records/{rid}/relationship',{'owner_entity_id':'LE-GB-02'})
    check(sibling['global_customer_id']==c['global_customer_id'] and sibling['id']!=rid and not sibling['grants'] and sibling['denied_countries']==['US'],'Authorised new owner relationship; identity linked, rights independent, geography retained')
    c=call(f'/records/{rid}/touch',{});s=settled(rid)
    check(copies(s,rid)[0]['version']==2,'Owner update propagates')
    check(next(d for d in s['customers'] if d['id']==sibling['id'])['version']==1,'Other owner record remains unchanged')
    call('/stores/STORE-GB-01/pause',{'paused':True})
    try:
        c=call(f'/records/{rid}/policy',{'expected_generation':c['generation'],'denied_entities':['LE-GB-02']},'PATCH')
        s=wait(lambda s:any(q['record_id']==rid and 'purge pending' in q['reason'] for q in s['queue']),'purge pending')
        check(len(copies(s,rid))==1,'Paused store retains copy; purge not falsely acknowledged')
        denied(f'/records/{rid}/read/LE-GB-02')
    finally:call('/stores/STORE-GB-01/pause',{'paused':False})
    s=settled(rid);check(not copies(s,rid),'Resume purges recipient live copy')
    call(f'/records/{rid}/touch',{});s=settled(rid);check(not copies(s,rid),'Post-revocation write does not resurrect copy')
    denied(f'/records/{rid}/policy',{'expected_generation':1},'PATCH',409)
    for scenario in ['shared-store-isolation','multi-entity','geo-deny','placement-blocked','no-entitlement','expired','contact']:
        d=generate(scenario);s=settled(d['id']);ps=copies(s,d['id'])
        if scenario=='shared-store-isolation':check([p['destination_entity_id'] for p in ps]==['LE-GB-02'],'Co-location does not authorise excluded UK entity')
        if scenario=='multi-entity':check(len(ps)==3 and len({p['store_id'] for p in ps})==1,'Three recipient keys coexist in one physical store')
        if scenario=='geo-deny':check(not any(p['destination_entity_id']=='LE-CA-01' for p in ps),'Canadian entity denied at its physical US store')
        if scenario in ['placement-blocked','no-entitlement','expired']:check(not ps,scenario+' blocks all candidates')
        if scenario=='contact':check(set(ps[0]['fields'])=={'name','tier','email'},'Contact profile filters notes')
    plan=call('/entities/LE-GB-02/placement-plan',{'store_id':'STORE-US-01'})
    check(not plan['approved'] and not plan['applied'],'Invalid relocation rejected; directory unmodified')
    d=generate('short-lived');wait(lambda s:bool(copies(s,d['id'])),'initial short-lived projection')
    wait(lambda s:not copies(s,d['id']) and next(c for c in s['customers'] if c['id']==d['id'])['generation']>1,'expiry reconciliation',35)
    check(True,'Expiry purges without owner mutation')
    return rid
if __name__=='__main__':run()
