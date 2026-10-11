"""Bounded synthetic relocation slice. Four local stores; one coordinator process.

SQLite runs the durable demo without Docker. CockroachDB uses the same repository
contract via psycopg. This is not distributed control-plane consensus or CDC.
"""
import contextlib, copy, hashlib, json, os, sqlite3, threading, uuid
from pathlib import Path

OWNER='LE-IN-01'
OTHER='LE-SG-01'
STORES={'SG':{'name':'Singapore','country':'SG','lat':1.35,'lon':103.82},'UK':{'name':'London','country':'GB','lat':51.5,'lon':-.12},'US':{'name':'New York','country':'US','lat':40.71,'lon':-74},'IN':{'name':'Mumbai','country':'IN','lat':19.08,'lon':72.88}}
ORDER=['party','relationship','party_relationship','product_holding','contact_info','consent','preference','contact_history','party_alternate_id','relationship_alternate_id','holding_alternate_id','classification','sovereignty_policy']
def encode(x):return json.dumps(x,sort_keys=True,separators=(',',':'))
def digest(x):return hashlib.sha256(encode(x).encode()).hexdigest()
class Rejected(Exception):pass
def require(ok,message):
    if not ok:raise Rejected(message)

def fixture(n=4,offset=0):
    rows=[]
    for i in range(offset+1,offset+n+1):
        p=f'P-{i:03}';r=f'R-{i:03}';h=f'H-{i:03}'
        values=[('party',p,{'global_party_id':f'GLOBAL-{i:03}','party_type':'person','display_name':f'Synthetic India Party {i}'},[]),('relationship',r,{'status':'active','type':'retail'},[]),('party_relationship',f'PR-{i:03}',{'party_id':p,'relationship_id':r,'role':'holder'},[p,r]),('product_holding',h,{'relationship_id':r,'product':'deposit','balance':1000+i,'currency':'INR'},[r]),('contact_info',f'C-{i:03}',{'party_id':p,'channel':'EMAIL','value':f'person{i}@example.invalid'},[p]),('consent',f'CO-{i:03}',{'party_id':p,'relationship_id':r,'purpose':'servicing','active':True},[p,r]),('preference',f'PF-{i:03}',{'party_id':p,'channel':'EMAIL'},[p]),('contact_history',f'CH-{i:03}',{'party_id':p,'relationship_id':r,'event':'synthetic onboarding'},[p,r]),('party_alternate_id',f'PA-{i:03}',{'party_id':p,'value':f'SYNTHETIC-P-{i}'},[p]),('relationship_alternate_id',f'RA-{i:03}',{'relationship_id':r,'value':f'SYNTHETIC-R-{i}'},[r]),('holding_alternate_id',f'HA-{i:03}',{'holding_id':h,'value':f'SYNTHETIC-H-{i}'},[h]),('classification',f'CL-{i:03}',{'resource_id':h,'classification':'confidential'},[h])]
        for kind,rid,data,parents in values:rows.append({'id':rid,'kind':kind,'version':1,'deleted':False,'data':data,'parents':parents})
    return rows

SCHEMA=[
'CREATE TABLE IF NOT EXISTS mig_rows (owner TEXT NOT NULL, id TEXT NOT NULL, kind TEXT NOT NULL, version BIGINT NOT NULL, doc TEXT NOT NULL, PRIMARY KEY(owner,id))',
'CREATE TABLE IF NOT EXISTS mig_authority (owner TEXT PRIMARY KEY, epoch BIGINT NOT NULL, writable BIGINT NOT NULL)',
'CREATE TABLE IF NOT EXISTS mig_clock (owner TEXT PRIMARY KEY, seq BIGINT NOT NULL)',
'CREATE TABLE IF NOT EXISTS mig_journal (owner TEXT NOT NULL, seq BIGINT NOT NULL, doc TEXT NOT NULL, PRIMARY KEY(owner,seq))',
'CREATE TABLE IF NOT EXISTS mig_receipts (owner TEXT NOT NULL, request_id TEXT NOT NULL, request_hash TEXT NOT NULL, result TEXT NOT NULL, PRIMARY KEY(owner,request_id))',
'CREATE TABLE IF NOT EXISTS mig_snapshot (job TEXT NOT NULL, ordinal BIGINT NOT NULL, doc TEXT NOT NULL, PRIMARY KEY(job,ordinal))',
'CREATE TABLE IF NOT EXISTS mig_control (id TEXT PRIMARY KEY, doc TEXT NOT NULL)']
class Store:
    def __init__(self,key,mode,folder):self.key=key;self.mode=mode;self.folder=folder
    @contextlib.contextmanager
    def tx(self):
        if self.mode=='sqlite':
            c=sqlite3.connect(self.folder/f'{self.key}.sqlite',timeout=10);c.execute('PRAGMA journal_mode=WAL');c.execute('BEGIN IMMEDIATE')
        else:
            import psycopg
            c=psycopg.connect(os.getenv('DB_'+self.key,f'postgresql://root@127.0.0.1:{26257+list(STORES).index(self.key)}/defaultdb?sslmode=disable'))
        def q(sql,args=()):return c.execute(sql if self.mode=='sqlite' else sql.replace('?', '%s'),args)
        try:yield q;c.commit()
        except Exception:c.rollback();raise
        finally:c.close()
    def initialize(self):
        with self.tx() as q:
            for ddl in SCHEMA:q(ddl)
    def rows(self,owner=OWNER):
        with self.tx() as q:return [json.loads(r[0]) for r in q('SELECT doc FROM mig_rows WHERE owner=? ORDER BY id',(owner,)).fetchall()]
    def head(self):
        with self.tx() as q:
            r=q('SELECT seq FROM mig_clock WHERE owner=?',(OWNER,)).fetchone();return r[0] if r else 0
    @staticmethod
    def put(q,row,owner=OWNER):
        old=q('SELECT version,doc FROM mig_rows WHERE owner=? AND id=?',(owner,row['id'])).fetchone()
        if old:
            if old[0]>row['version']:return False
            require(old[0]!=row['version'] or json.loads(old[1])==row,'Equal version has conflicting contents')
        q('INSERT INTO mig_rows VALUES (?,?,?,?,?) ON CONFLICT(owner,id) DO UPDATE SET kind=excluded.kind,version=excluded.version,doc=excluded.doc',(owner,row['id'],row['kind'],row['version'],encode(row)))
        return True

class MigrationRuntime:
    def __init__(self,mode=None,folder=None,opa_url=None,tracer=None):
        self.mode=mode or os.getenv('MIGRATION_STORAGE','cockroach');require(self.mode in ('sqlite','cockroach'),'Unknown storage adapter')
        self.folder=Path(folder or os.getenv('MIGRATION_DIR','/tmp/sovereign-migration'));self.folder.mkdir(parents=True,exist_ok=True)
        self.stores={k:Store(k,self.mode,self.folder) for k in STORES};self.lock=threading.RLock();self.other_lock=threading.Lock();self.opa_url=opa_url if opa_url is not None else os.getenv('MIGRATION_OPA_URL','');self.tracer=tracer
    def control(self):
        with self.stores['SG'].tx() as q:return json.loads(q('SELECT doc FROM mig_control WHERE id=?',('india-demo',)).fetchone()[0])
    def save(self,c):
        with self.stores['SG'].tx() as q:q('INSERT INTO mig_control VALUES (?,?) ON CONFLICT(id) DO UPDATE SET doc=excluded.doc',('india-demo',encode(c)))
    def event(self,c,kind,message):
        c['events'].insert(0,{'at':c['elapsed'],'kind':kind,'message':message});c['events']=c['events'][:60]
    def initialize(self):
        for key in ['SG','UK','US']:self.stores[key].initialize()
        with self.stores['SG'].tx() as q:exists=q('SELECT doc FROM mig_control WHERE id=?',('india-demo',)).fetchone()
        if not exists:
            c={'phase':'DRAFT','job':'MIG-IN-001','home':'SG','epoch':1,'placement_version':1,'policy_revision':1,'elapsed':0,'deadline':600,'registered':False,'paused':False,'conflict':False,'cursor':0,'snapshot_count':0,'snapshot_seq':0,'applied_seq':0,'final_seq':None,'validation':None,'generated':4,'events':[],'other_writes':0,'cleanup_count':0,'retained_surfaces':'SQL live rows only; MVCC/WAL/backups and audit retention require separate disposal evidence.'}
            with self.stores['SG'].tx() as q:
                q('INSERT INTO mig_authority VALUES (?,?,?) ON CONFLICT(owner) DO NOTHING',(OWNER,1,1));q('INSERT INTO mig_clock VALUES (?,?) ON CONFLICT(owner) DO NOTHING',(OWNER,0))
                for row in fixture()+[{'id':'POLICY','kind':'sovereignty_policy','version':1,'deleted':False,'data':{'transition_countries':['SG','IN'],'future_countries':['IN'],'denied_countries':['US'],'synthetic_deadline':600},'parents':[]}]:Store.put(q,row)
                self.event(c,'seed','Synthetic transition: Singapore permitted before t=600; India required afterwards.');q('INSERT INTO mig_control VALUES (?,?)',('india-demo',encode(c)))
        c=self.control()
        if c['registered']:self.stores['IN'].initialize()
        # Recover a crash after source fencing but before coordinator checkpoint.
        with self.stores['SG'].tx() as q:a=q('SELECT writable FROM mig_authority WHERE owner=?',(OWNER,)).fetchone()
        if c['home']=='SG' and a and not a[0] and c['phase'] not in ('DRAFT','REGISTERED','PLANNED','CANCELLED'):
            c['phase']='FENCED';c['final_seq']=self.stores['SG'].head();self.save(c)
    def permit(self,c,operation,store='IN'):
        inp={'operation':operation,'country':STORES[store]['country'],'elapsed':c['elapsed'],'deadline':c['deadline'],'conflict':c['conflict'],'home':c['home'],'target':'IN','phase':c['phase']}
        if self.opa_url:
            import httpx
            try:
                target_url=os.getenv('MIGRATION_OPA_IN_URL',self.opa_url)
                urls=[self.opa_url,target_url] if operation=='transfer' else [target_url if store=='IN' else self.opa_url]
                allowed=True
                for url in dict.fromkeys(urls):
                    r=httpx.post(url.rstrip('/')+'/v1/data/bank/migration/allow',json={'input':inp},timeout=3,trust_env=False);r.raise_for_status();allowed=allowed and r.json().get('result') is True
            except Exception:raise Rejected('OPA unavailable or invalid: migration action denied')
        else:
            allowed=(operation=='register' and store=='IN') or (operation=='transfer' and store=='IN' and c['elapsed']<c['deadline'] and not c['conflict']) or (operation in ('read','write') and (store=='IN' or (store=='SG' and c['elapsed']<c['deadline'])) and not (store=='IN' and c['conflict'])) or (operation=='purge' and c['home']=='IN' and store=='SG')
        require(allowed,'Policy denies this operation: check transition deadline, geography and record conflict')
    def ready_target(self,c):require(c['registered'] and not c['paused'],'India target is unregistered or paused')
    def snapshot(self):
        with self.lock:
            c=self.control();out=copy.deepcopy(c);out['mode']='persistent-'+self.mode;out['policy_engine']='OPA' if self.opa_url else 'reference policy (OPA adapter available)';out['entity_id']=OWNER
            out['stores']=[];rows={}
            for key,info in STORES.items():
                data=self.stores[key].rows() if key!='IN' or c['registered'] else [];rows[key]=data
                out['stores'].append({'id':key,**info,'registered':key!='IN' or c['registered'],'live_rows':sum(not x['deleted'] for x in data),'stored_rows':len(data),'authoritative':c['home']==key,'paused':key=='IN' and c['paused']})
            out['source_head']=self.stores['SG'].head();out['delta_lag']=max(0,out['source_head']-c['applied_seq']) if c['home']=='SG' else 0
            with self.stores['UK'].tx() as q:
                other=q('SELECT version FROM mig_rows WHERE owner=? AND id=?',(OTHER,'unrelated-counter')).fetchone();out['other_writes']=other[0] if other else 0
            out['business_available']=c['phase'] not in ('FENCED','ACTIVATING') and (c['home']=='IN' or c['elapsed']<c['deadline']) and not(c['home']=='IN' and c['paused'])
            out['records']=[{'id':rid,'kind':next(x['kind'] for v in rows.values() for x in v if x['id']==rid),'SG':next((x['version'] for x in rows['SG'] if x['id']==rid and not x['deleted']),None),'IN':next((x['version'] for x in rows['IN'] if x['id']==rid and not x['deleted']),None)} for rid in sorted({x['id'] for v in rows.values() for x in v})][:120]
            return out
    def _business(self,c,body):
        home=body.get('store',c['home']);require(home==c['home'],'Stale route: old store cannot accept writes');require(c['phase'] not in ('FENCED','ACTIVATING'),'Entity writes paused at cutover')
        if home=='IN':self.ready_target(c)
        self.permit(c,'write',home);request=body.get('request_id') or str(uuid.uuid4());kind=body.get('kind','update');require(kind in ('update','create','delete'),'Unknown business command')
        fingerprint=digest({'kind':kind});db=self.stores[home]
        with db.tx() as q:
            receipt=q('SELECT request_hash,result FROM mig_receipts WHERE owner=? AND request_id=?',(OWNER,request)).fetchone()
            if receipt:require(receipt[0]==fingerprint,'Idempotency key conflicts with another command');return {**json.loads(receipt[1]),'replayed':True}
            a=q('SELECT epoch,writable FROM mig_authority WHERE owner=?'+(' FOR UPDATE' if self.mode=='cockroach' else ''),(OWNER,)).fetchone();require(a and a[1] and a[0]==c['epoch'],'Writer fenced')
            require(body.get('expected_epoch',c['epoch'])==a[0],'Stale writer epoch')
            if kind=='create':
                ids=q('SELECT id FROM mig_rows WHERE owner=? AND kind=?',(OWNER,'party')).fetchall();next_index=max(int(x[0].split('-')[1]) for x in ids)
                require(next_index<16,'Bounded fixture limit reached (16 relationships)');changes=fixture(1,next_index)
            else:
                rid='CH-001' if kind=='delete' else 'H-001';row=q('SELECT doc FROM mig_rows WHERE owner=? AND id=?',(OWNER,rid)).fetchone();require(row is not None,'Record missing');row=json.loads(row[0]);row['version']+=1
                if kind=='delete':row['deleted']=True;row['data']={}
                else:row['data']['balance']+=10
                changes=[row]
            seq=q('SELECT seq FROM mig_clock WHERE owner=?',(OWNER,)).fetchone()[0]
            for row in changes:
                Store.put(q,row);seq+=1;q('INSERT INTO mig_journal VALUES (?,?,?)',(OWNER,seq,encode(row)))
            q('UPDATE mig_clock SET seq=? WHERE owner=?',(seq,OWNER));result={'request_id':request,'home':home,'epoch':c['epoch'],'sequence':seq,'changed':len(changes),'replayed':False};q('INSERT INTO mig_receipts VALUES (?,?,?,?)',(OWNER,request,fingerprint,encode(result)))
        if kind=='create':c['generated']=next_index+1
        if c['phase']=='VALIDATED':c['phase']='CATCHING_UP';c['validation']=None
        self.event(c,'operational',f'{kind} committed at {home}; epoch {c["epoch"]}; migration did not own this transaction.');self.save(c);return result
    def _validate(self,c):
        self.ready_target(c);self.permit(c,'transfer');require(c['cursor']==c['snapshot_count'],'Initial copy is incomplete')
        source=self.stores['SG'].rows();target=self.stores['IN'].rows();require(c['applied_seq']==self.stores['SG'].head(),'Catch-up is not complete')
        require(source==target,'Source and target versions/content do not reconcile');alive={r['id'] for r in target if not r['deleted']}
        require(all(set(r['parents'])<=alive for r in target if not r['deleted']),'A live child has a missing parent')
        return {'sequence':self.stores['SG'].head(),'row_count':len(source),'digest':digest(source),'closure':True}
    def _apply_transfer(self,c,rows,source_epoch=1):
        require(c['phase'] in ('COPYING','CATCHING_UP','VALIDATED','FENCED') and c['home']=='SG' and c['epoch']==source_epoch,'Stale migration envelope: source authority or campaign phase changed')
        self.ready_target(c);self.permit(c,'transfer')
        with self.stores['IN'].tx() as q:
            a=q('SELECT epoch,writable FROM mig_authority WHERE owner=?'+(' FOR UPDATE' if self.mode=='cockroach' else ''),(OWNER,)).fetchone();require(a and a[0]==2 and not a[1],'Target is no longer a staging store')
            for row in rows:Store.put(q,row)
    def _step(self,c,action,body):
        phase=c['phase'];batch=body.get('batch',8);require(type(batch) is int and 1<=batch<=32,'Batch must be an integer in 1..32')
        if action=='register':
            require(phase in ('DRAFT','REGISTERED'),'Store already registered for this campaign');self.permit(c,'register');self.stores['IN'].initialize()
            with self.stores['IN'].tx() as q:q('INSERT INTO mig_authority VALUES (?,?,?) ON CONFLICT(owner) DO NOTHING',(OWNER,2,0));q('INSERT INTO mig_clock VALUES (?,?) ON CONFLICT(owner) DO NOTHING',(OWNER,0))
            c.update(registered=True,phase='REGISTERED');self.event(c,'guard','Mumbai registered; staging only, no business writer.')
        elif action=='plan':
            require(phase in ('REGISTERED','PLANNED'),'Register India first');self.permit(c,'transfer');self.ready_target(c);c['phase']='PLANNED';self.event(c,'plan','Owner graph eligible; US excluded; other entities keep their own ownership.')
        elif action=='start':
            require(phase=='PLANNED','An approved plan is required');self.permit(c,'transfer');self.ready_target(c)
            with self.stores['SG'].tx() as q:
                data=[json.loads(r[0]) for r in q('SELECT doc FROM mig_rows WHERE owner=? ORDER BY id',(OWNER,)).fetchall()];seq=q('SELECT seq FROM mig_clock WHERE owner=?',(OWNER,)).fetchone()[0]
                q('DELETE FROM mig_snapshot WHERE job=?',(c['job'],))
                for i,row in enumerate(data):q('INSERT INTO mig_snapshot VALUES (?,?,?)',(c['job'],i,encode(row)))
            c.update(phase='COPYING',cursor=0,snapshot_count=len(data),snapshot_seq=seq,applied_seq=seq);self.event(c,'bulk','Consistent snapshot captured; source writes remain enabled.')
        elif action=='copy':
            require(phase=='COPYING','Copy is not active');self.ready_target(c);self.permit(c,'transfer')
            with self.stores['SG'].tx() as q:batchrows=q('SELECT doc FROM mig_snapshot WHERE job=? AND ordinal>=? ORDER BY ordinal LIMIT ?',(c['job'],c['cursor'],batch)).fetchall()
            self._apply_transfer(c,[json.loads(row[0]) for row in batchrows])
            c['cursor']+=len(batchrows)
            if c['cursor']==c['snapshot_count']:c['phase']='CATCHING_UP'
            self.event(c,'bulk',f'Copied {len(batchrows)} snapshot rows; checkpoint {c["cursor"]}/{c["snapshot_count"]}.')
        elif action=='catchup':
            require(phase in ('CATCHING_UP','FENCED'),'Catch-up is not active');self.ready_target(c);self.permit(c,'transfer')
            with self.stores['SG'].tx() as q:changes=q('SELECT seq,doc FROM mig_journal WHERE owner=? AND seq>? ORDER BY seq LIMIT ?',(OWNER,c['applied_seq'],batch)).fetchall()
            self._apply_transfer(c,[json.loads(doc) for seq,doc in changes])
            if changes:c['applied_seq']=changes[-1][0]
            self.event(c,'catchup',f'Applied {len(changes)} committed changes, including versioned tombstones.')
        elif action=='validate':
            require(phase in ('CATCHING_UP','VALIDATED'),'Catch up before validation');c['validation']=self._validate(c);c['phase']='VALIDATED';self.event(c,'verify','Counts, contents, versions, tombstones and parent closure match. A later source write invalidates this gate.')
        elif action=='fence':
            require(phase in ('VALIDATED','FENCED'),'Validate before fencing');self._validate(c)
            with self.stores['SG'].tx() as q:q('UPDATE mig_authority SET writable=0 WHERE owner=?',(OWNER,));final=q('SELECT seq FROM mig_clock WHERE owner=?',(OWNER,)).fetchone()[0]
            c.update(phase='FENCED',final_seq=final);self.event(c,'guard','Old SG writer durably fenced. Only this entity is paused; ready to drain/activate.')
        elif action=='activate':
            require(phase in ('FENCED','ACTIVATING','ACTIVE','CLEANUP','COMPLETE'),'Fence the old writer before activation')
            if phase in ('ACTIVE','CLEANUP','COMPLETE'):return
            self.ready_target(c)
            if phase=='FENCED':
                c['validation']=self._validate(c)
                with self.stores['SG'].tx() as q:
                    a=q('SELECT writable FROM mig_authority WHERE owner=?',(OWNER,)).fetchone();require(a and not a[0],'Old writer is not fenced');receipts=q('SELECT request_id,request_hash,result FROM mig_receipts WHERE owner=?',(OWNER,)).fetchall()
                with self.stores['IN'].tx() as q:
                    for rid,h,res in receipts:q('INSERT INTO mig_receipts VALUES (?,?,?,?) ON CONFLICT(owner,request_id) DO NOTHING',(OWNER,rid,h,res))
                    q('UPDATE mig_clock SET seq=? WHERE owner=?',(c['final_seq'],OWNER))
                c.update(home='IN',epoch=2,placement_version=2,policy_revision=2,phase='ACTIVATING');self.save(c)
            # Routing is changed only after durable source fencing; a crash here is unavailable, not dual-writer.
            self.permit(c,'write','IN')
            with self.stores['IN'].tx() as q:q('UPDATE mig_authority SET writable=1,epoch=2 WHERE owner=?',(OWNER,))
            c['phase']='ACTIVE';self.event(c,'cutover','India is authoritative at placement v2 / writer epoch 2. Old SG requests reject; no routing flip-back.')
        elif action=='cleanup':
            require(phase in ('ACTIVE','CLEANUP','COMPLETE'),'India must be active before cleanup');self.permit(c,'purge','SG');c['phase']='CLEANUP'
            with self.stores['SG'].tx() as q:
                ids=q('SELECT id FROM mig_rows WHERE owner=? ORDER BY id LIMIT ?',(OWNER,batch)).fetchall()
                for (rid,) in ids:q('DELETE FROM mig_rows WHERE owner=? AND id=?',(OWNER,rid))
                c['cleanup_count']+=len(ids);remaining=q('SELECT count(*) FROM mig_rows WHERE owner=?',(OWNER,)).fetchone()[0]
                if not remaining:
                    q('DELETE FROM mig_journal WHERE owner=?',(OWNER,));q('DELETE FROM mig_receipts WHERE owner=?',(OWNER,));q('DELETE FROM mig_snapshot WHERE job=?',(c['job'],));c['phase']='COMPLETE'
            self.event(c,'purge','Old live rows cleaned in a bounded batch. Retained storage surfaces are not certified erased.')
        elif action=='pause':c['paused']=bool(body.get('paused',True));self.event(c,'fault','India transport '+('paused' if c['paused'] else 'resumed')+'.')
        elif action=='deadline':c['elapsed']=c['deadline'];self.event(c,'policy','Synthetic deadline reached. SG reads/writes/transfers fail closed; residual copies require remediation.')
        elif action=='conflict':require(phase in ('DRAFT','REGISTERED','PLANNED'),'Set record conflict before copying');c['conflict']=bool(body.get('blocked',True));c['phase']='REGISTERED' if c['registered'] else 'DRAFT';self.event(c,'policy','Synthetic record India exclusion '+('enabled' if c['conflict'] else 'removed')+'.')
        elif action=='stale':self._apply_transfer(c,fixture(1),source_epoch=0)
        elif action=='rollback':
            require(c['home']=='SG' and phase not in ('FENCED','ACTIVATING'),'Automatic flip-back is prohibited after source fencing/cutover');self.permit(c,'write','SG')
            if c['registered']:
                with self.stores['IN'].tx() as q:q('DELETE FROM mig_rows WHERE owner=?',(OWNER,))
            with self.stores['SG'].tx() as q:q('DELETE FROM mig_snapshot WHERE job=?',(c['job'],))
            c['phase']='CANCELLED';self.event(c,'cancel','Pre-cutover campaign cancelled; original authority unchanged.')
        else:raise Rejected('Unknown migration action')
        self.save(c)
    def command(self,action,body=None):
        body=body or {}
        if action=='other':
            # This workload has its own lock and regional transaction; never waits on the entity migration lock.
            with self.other_lock,self.stores['UK'].tx() as q:
                row=q('SELECT doc FROM mig_rows WHERE owner=? AND id=?',(OTHER,'unrelated-counter')).fetchone();v=json.loads(row[0])['version']+1 if row else 1;Store.put(q,{'id':'unrelated-counter','kind':'operational_probe','version':v,'deleted':False,'data':{'count':v},'parents':[]},OTHER)
            return {'other_writes':v,'home':'UK'}
        span=self.tracer.start_as_current_span('migration.'+action,attributes={'work.class':'operational' if action=='write' else 'guard' if action in ('fence','activate') else 'reconciliation'}) if self.tracer else contextlib.nullcontext()
        with span,self.lock:
            c=self.control()
            if action=='reset':
                require(body.get('scenario')=='synthetic-india','Only the synthetic India namespace may be reset')
                for key in ['IN','SG','UK','US']:
                    if key=='IN' and not c['registered']:continue
                    with self.stores[key].tx() as q:
                        for table in ['mig_rows','mig_journal','mig_receipts','mig_clock','mig_authority']:q(f'DELETE FROM {table} WHERE owner=?',(OWNER,))
                        q('DELETE FROM mig_snapshot WHERE job=?',(c['job'],))
                with self.stores['SG'].tx() as q:q('DELETE FROM mig_control WHERE id=?',('india-demo',))
                self.initialize();return self.snapshot()
            if action=='write':return self._business(c,body)
            self._step(c,action,body)
            return self.snapshot()
    def read(self,store):
        with self.lock:
            c=self.control();require(store==c['home'],'Store is staging or retired; use current authoritative route');require(c['phase']!='ACTIVATING','Activation incomplete');self.permit(c,'read',store)
            if store=='IN':self.ready_target(c)
            return {'home':store,'epoch':c['epoch'],'records':self.stores[store].rows()}

def make_router(runtime):
    from fastapi import APIRouter,HTTPException
    router=APIRouter(prefix='/api/migration')
    @router.get('')
    def status():return runtime.snapshot()
    @router.post('/{action}')
    def command(action:str,body:dict):
        try:return runtime.command(action,body)
        except Rejected as e:raise HTTPException(409,str(e))
    @router.get('/read/{store}')
    def read(store:str):
        try:return runtime.read(store)
        except Rejected as e:raise HTTPException(409,str(e))
    return router
