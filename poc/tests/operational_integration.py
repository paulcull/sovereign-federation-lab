"""Real CockroachDB + OPA acceptance. Run on disposable local POC only; mutates synthetic fixture."""
import os,uuid
import psycopg
from integration import call,wait,check,denied

def op():return call('/operational')
def scope(sid):return next(s for s in op()['model']['scopes'] if s['id']==sid)
def command(sid,c,**kw):return call(f'/operational/scopes/{sid}/commands',dict(command=c,request_id=str(uuid.uuid4()),expected_version=scope(sid)['data_version'],**kw))
def settled():return wait(lambda state:not state['operational']['queue'],'operational outbox settlement')['operational']
def read(sid,d):return call(f'/operational/scopes/{sid}/read/{d}')
def run():
    scopes=op()['model']['scopes'];personal=next(s for s in scopes if s['scope_kind']=='relationship' and 'Personal' in s['name']);sid=personal['id'];party=next(s for s in scopes if s['scope_kind']=='party' and s['primary_party_id']==personal['primary_party_id'])
    call('/stores/STORE-GB-01/pause',{'paused':False});call('/stores/STORE-US-01/pause',{'paused':False})
    for c in ['restore_consent','classify_internal','table_contact_restore','restore_party_us']:command(sid,c)
    settled();rows=read(party['id'],'LE-US-01')['rows'];check(len(rows)==1 and set(rows[0]['row'])=={'id','global_party_id','party_type'},'US has party minimum only');denied(f'/operational/scopes/{sid}/read/LE-US-01')
    with psycopg.connect(os.environ['DB_US']) as c:
        assert c.execute('SELECT count(*) FROM projection.party WHERE scope_id=%s AND destination_entity_id=%s AND display_name IS NOT NULL',(party['id'],'LE-US-01')).fetchone()[0]==0
        assert c.execute('SELECT count(*) FROM projection.relationship WHERE scope_id=%s',(sid,)).fetchone()[0]==0
        assert c.execute('SELECT count(*) FROM projection.product_holding WHERE scope_id=%s',(sid,)).fetchone()[0]==0
    check(True,'US SQL contains eligible party identity without name, relationship or holding payload')
    body=dict(command='update_contact',request_id=str(uuid.uuid4()),expected_version=scope(sid)['data_version'],value='integration.aster@example.invalid');result=call(f'/operational/scopes/{sid}/commands',body);check(len(result['affected_scope_ids'])==2,'One contact update affects both relationship scopes')
    replay=call(f'/operational/scopes/{sid}/commands',body);check(replay['idempotent_replay'],'Request ID replay returns receipt')
    denied(f'/operational/scopes/{sid}/commands',{**body,'command':'log_contact'},status=409)
    settled();call('/stores/STORE-GB-01/pause',{'paused':True})
    try:
        command(sid,'withdraw_consent');denied(f'/operational/scopes/{sid}/read/LE-GB-02',status=409)
        p=next(p for p in op()['projections'] if p['scope_id']==sid and p['destination_entity_id']=='LE-GB-02');check(any(r['table']=='contact_info' for r in p['rows']),'Paused recipient still has old contact: purge is pending')
    finally:call('/stores/STORE-GB-01/pause',{'paused':False})
    settled();check(not any(r['table'] in ['contact_info','preference'] for r in read(sid,'LE-GB-02')['rows']),'Consent revocation removes contact fields and preferences')
    command(sid,'restore_consent');command(sid,'open_holding');command(sid,'classify_restricted');settled()
    s=op();tables=s['model']['tables']
    for p in s['projections']:
        keys={(r['table'],r['row']['id']) for r in p['rows']}
        for r in p['rows']:
            check('balance' not in r['row'],'Balance excluded')
            for fk in tables[r['table']]['parents']:
                if r['row'].get(fk['field']):assert (fk['table'],r['row'][fk['field']]) in keys
    command(sid,'table_contact_local');settled();check(not any(r['table']=='contact_info' for p in op()['projections'] for r in p['rows']),'Table policy removes all contact projections')
    command(party['id'],'exclude_party_us');denied(f"/operational/scopes/{party['id']}/read/LE-US-01");settled();check(not any(p['rows'] for p in op()['projections'] if p['scope_id']==party['id'] and p['destination_entity_id']=='LE-US-01'),'Party-key exclusion purges prior global minimum')
    for c in ['restore_consent','classify_internal','table_contact_restore','restore_party_us']:command(sid,c)
    settled();print('PASS operational database acceptance. Also inspect typed SQL rows and regional OTel traces as described in OPERATIONAL.md.')
if __name__=='__main__':run()
