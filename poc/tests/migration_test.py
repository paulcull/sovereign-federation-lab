"""Actual durable repository tests; SQLite adapter. No CockroachDB claim."""
import sys,tempfile,threading,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from migration import MigrationRuntime,OWNER,Store,Rejected,fixture

def deny(fn):
    try:fn()
    except Rejected:return
    raise AssertionError('Expected rejection')
def new(folder,opa=''):
    r=MigrationRuntime(mode='sqlite',folder=folder,opa_url=opa);r.initialize();return r
def copy_all(r):
    while r.control()['phase']=='COPYING':r.command('copy',{'batch':7})
def catch_all(r):
    while r.snapshot()['delta_lag']:r.command('catchup',{'batch':5})
def writers(r):
    result=[]
    for key in ['SG','IN']:
        if key=='IN' and not r.control()['registered']:continue
        with r.stores[key].tx() as q:
            a=q('SELECT epoch,writable FROM mig_authority WHERE owner=?',(OWNER,)).fetchone()
            if a and a[1]:result.append(key)
    return result

def run(opa=''):
 with tempfile.TemporaryDirectory() as folder:
    r=new(folder,opa);assert len(r.read('SG')['records'])==49;assert writers(r)==['SG'];deny(lambda:r.command('activate'))
    r.command('register');deny(lambda:r.read('IN'));r.command('conflict',{'blocked':True});deny(lambda:r.command('plan'));r.command('conflict',{'blocked':False});r.command('plan');r.command('start');r.command('copy',{'batch':8})
    first=r.command('write',{'request_id':'exact-retry','kind':'update'});assert first['home']=='SG';r.command('write',{'kind':'create'});r.command('write',{'kind':'delete'})
    r.command('pause',{'paused':True});deny(lambda:r.command('copy'));r.command('write',{'kind':'update'});r.command('other');r.command('pause',{'paused':False})
    r=new(folder,opa);assert r.control()['cursor']==8;copy_all(r);deny(lambda:r.command('validate'));catch_all(r);r.command('validate')
    r.command('write',{'kind':'update'});assert r.control()['phase']=='CATCHING_UP';deny(lambda:r.command('fence'));catch_all(r);r.command('validate')
    # Outdated snapshot must not overwrite a newer delta, even on retry.
    row=next(x for x in fixture(1) if x['id']=='H-001')
    with r.stores['IN'].tx() as q:assert not Store.put(q,row)
    r.command('fence');assert writers(r)==[];deny(lambda:r.command('write',{'kind':'update'}));r.command('other')
    # A second request can commit to UK while the entity-specific lock is held.
    result=[]
    with r.lock:
        t=threading.Thread(target=lambda:result.append(r.command('other')));t.start();t.join(2);assert not t.is_alive()
    assert result
    r=new(folder,opa);assert r.control()['phase']=='FENCED';r.command('activate');assert writers(r)==['IN'];r.command('activate')
    assert r.command('write',{'request_id':'exact-retry','kind':'update'})['replayed'];assert r.command('write',{'kind':'update'})['home']=='IN'
    deny(lambda:r.command('write',{'kind':'update','store':'SG'}));deny(lambda:r.command('write',{'kind':'update','expected_epoch':1}));deny(lambda:r.command('stale'));deny(lambda:r.command('rollback'));deny(lambda:r.read('SG'))
    r.command('deadline');assert r.command('write',{'kind':'update'})['home']=='IN'
    while r.control()['phase']!='COMPLETE':r.command('cleanup',{'batch':7})
    assert not r.stores['SG'].rows();assert not r.stores['US'].rows();assert len(r.read('IN')['records'])==61
    with r.stores['SG'].tx() as q:
        for table in ['mig_journal','mig_receipts']:assert q(f'SELECT count(*) FROM {table} WHERE owner=?',(OWNER,)).fetchone()[0]==0
        assert q('SELECT count(*) FROM mig_snapshot').fetchone()[0]==0
    assert writers(new(folder,opa))==['IN']
 with tempfile.TemporaryDirectory() as folder:
    r=new(folder,opa);r.command('register');r.command('plan');r.command('start');r.command('deadline');deny(lambda:r.command('write'));deny(lambda:r.command('copy'));deny(lambda:r.command('rollback'));r.command('other')
 with tempfile.TemporaryDirectory() as folder:
    r=new(folder,opa);r.command('register');r.command('plan');r.command('start');r.command('copy');r.command('rollback');assert writers(r)==['SG'];assert not r.stores['IN'].rows()
 print('PASS durable relocation: copy/catch-up, concurrent writes, tombstones, conflicts, pause/resume, restart, validation invalidation, writer fencing, receipt handoff, independent UK work, stale replay, deadline, cancellation and live cleanup. Adapter=SQLite; policy='+('OPA' if opa else 'reference'))
if __name__=='__main__':run(sys.argv[1] if len(sys.argv)>1 else '')
