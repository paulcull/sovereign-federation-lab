"""Normalized business tables with a parallel sovereignty sidecar and transaction hook."""
import copy,json,time,uuid,hashlib
from decimal import Decimal
from pathlib import Path
from psycopg.types.json import Jsonb
from fastapi import HTTPException
import operational_core as core

def clean(value):
    if isinstance(value,(uuid.UUID,Decimal)):return str(value)
    if isinstance(value,dict):return {k:clean(v) for k,v in value.items()}
    if isinstance(value,(tuple,list)):return [clean(v) for v in value]
    return value
class OperationalRuntime:
    def __init__(self,stores,entities,store_info,lock,paused,tracer):
        self.stores=stores;self.entities=entities;self.store_info=store_info;self.lock=lock;self.paused=paused;self.tracer=tracer
        self.home=entities[core.SPEC['owner_entity_id']]['store_id']
    def initialize(self):
        ddl=(Path(__file__).with_name('operational_schema.sql')).read_text()
        for store in self.stores.values():
            with store.connect() as c:
                for sql in ddl.split(';'):
                    if sql.strip():c.execute(sql)
        with self.stores[self.home].connect() as c:
            if c.execute('SELECT count(*) FROM sovereignty.scope').fetchone()[0]==0:
                m=core.seed()
                for table in core.ORDER:
                    for row in m['rows'][table]:self.write_business(c,table,row)
                self.write_controls(c,m)
                for scope in m['scopes']:self.enqueue(c,scope);self.audit(c,scope,scope['owner_entity_id'],'business_commit','Seeded normalized party/relationship graph')
    def write_business(self,c,table,row):
        if table not in core.TABLES:raise ValueError('Unregistered dataset')
        columns=['owner_entity_id']+list(core.TABLES[table]['columns'])
        values=[core.SPEC['owner_entity_id']]+[row.get(k) for k in columns[1:]]
        c.execute(f"UPSERT INTO business.{table} ({','.join(columns)}) VALUES ({','.join(['%s']*len(columns))})",values)
    def write_controls(self,c,m,affected=None):
        for t,r in m['table_rules'].items():c.execute('UPSERT INTO sovereignty.table_rule VALUES (%s,%s,%s)',(m['owner_entity_id'],t,Jsonb(r)))
        for scope in m['scopes']:
            if affected is not None and scope['id'] not in affected:continue
            c.execute('UPSERT INTO sovereignty.scope VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',(scope['id'],scope['owner_entity_id'],scope['relationship_id'],scope['data_version'],scope['policy_generation'],scope['decision_revision'],Jsonb(scope),scope['root_type'],scope['root_id'],scope['primary_party_id']))
        for r in m['rules']:c.execute('UPSERT INTO sovereignty.resource_rule VALUES (%s,%s,%s,%s)',(m['owner_entity_id'],r['resource_type'],r['resource_id'],Jsonb(r)))
        for b in m['bindings']:c.execute('UPSERT INTO sovereignty.binding VALUES (%s,%s,%s,%s)',(m['owner_entity_id'],b['scope_id'],b['resource_type'],b['resource_id']))
    def load(self,c):
        m={**copy.deepcopy(core.SPEC),'scopes':[],'rows':{},'rules':[],'bindings':[]}
        for table in core.ORDER:
            cur=c.execute('SELECT '+','.join(core.TABLES[table]['columns'])+' FROM business.'+table+' WHERE owner_entity_id=%s',(m['owner_entity_id'],))
            cols=[d.name for d in cur.description];m['rows'][table]=[clean(dict(zip(cols,r))) for r in cur.fetchall()]
        m['scopes']=[r[0] for r in c.execute('SELECT doc FROM sovereignty.scope')]
        m['table_rules']={r[0]:r[1] for r in c.execute('SELECT resource_type,rule FROM sovereignty.table_rule')}
        m['rules']=[r[0] for r in c.execute('SELECT rule FROM sovereignty.resource_rule')]
        m['bindings']=[dict(scope_id=str(r[0]),resource_type=r[1],resource_id=str(r[2])) for r in c.execute('SELECT scope_id,resource_type,resource_id FROM sovereignty.binding')]
        return m
    def candidates(self,s):return sorted(set(s['policy']['allowed_entities'])|set(s['policy']['denied_entities'])|set(s['policy']['grants'])|set(s['contacted']))
    def enqueue(self,c,s):
        for dest in self.candidates(s):
            c.execute('INSERT INTO sovereignty.outbox (id,scope_id,destination_entity_id,created_at) VALUES (%s,%s,%s,%s)',(str(uuid.uuid4()),s['id'],dest,time.time()))
    def audit(self,c,s,dest,status,reason):
        d=dict(id=str(uuid.uuid4()),time=time.time(),record_id=s['id'],name=s['name'],owner_entity_id=s['owner_entity_id'],destination_entity_id=dest,source_store=s['home_store_id'],destination_store=self.entities[dest]['store_id'],status=status,reason=reason,dataset='party_relationship_graph',generation=s['policy_generation'],data_version=s['data_version'],decision_revision=s['decision_revision'],placement_version=self.entities[dest]['placement_version'])
        c.execute('INSERT INTO sovereignty.audit VALUES (%s,%s,%s)',(d['id'],d['time'],Jsonb(d)))
    def opa_input(self,m,s,dest,resources=None):
        e=self.entities[dest]
        return dict(customer=s['policy'],destination_entity=e,destination_store=self.store_info[e['store_id']],now=time.time(),resources=core.resources(m,s) if resources is None else resources)
    def evaluate(self,m,s,dest,store=None,resources=None):
        store=store or self.stores[s['home_store_id']]
        with self.tracer.start_as_current_span('operational.dataset_gate',attributes={'source.store':s['home_store_id'],'destination.entity':dest}):
            res=store.http.post(store.opa+'/v1/data/operational/decisions',json={'input':self.opa_input(m,s,dest,resources)})
            res.raise_for_status();result=res.json().get('result')
            if not isinstance(result,list) or len(result)!=len(core.resources(m,s) if resources is None else resources):raise RuntimeError('Dataset policy missing; fail closed')
            return result
    def plan(self,m,s,dest):return core.manifest(m,s,self.evaluate(m,s,dest))
    def command(self,sid,body):
        with self.tracer.start_as_current_span('operational.command',attributes={'source.store':self.home,'command.kind':body.get('command') if body.get('command') in core.COMMANDS else 'unknown'}), self.lock, self.stores[self.home].connect() as c:
            try:uuid.UUID(body.get('request_id',''))
            except (ValueError,TypeError):raise HTTPException(422,'A UUID request_id is required')
            hashed=hashlib.sha256(json.dumps({'scope_id':sid,**body},sort_keys=True).encode()).hexdigest()
            prior=c.execute('SELECT request_hash,result FROM sovereignty.command_receipt WHERE owner_entity_id=%s AND request_id=%s',(core.SPEC['owner_entity_id'],body['request_id'])).fetchone()
            if prior:
                if prior[0]!=hashed:raise HTTPException(409,'Idempotency key reused for different command')
                return {**prior[1],'idempotent_replay':True}
            m=self.load(c)
            try:updated,result=core.command(m,sid,body)
            except StopIteration:raise HTTPException(404,'Unknown operational scope')
            except ValueError as e:raise HTTPException(409 if 'Stale' in str(e) else 422,str(e))
            for ch in sorted(result['changed'],key=lambda ch:core.ORDER.index(ch['table'])):
                row=next(r for r in updated['rows'][ch['table']] if r['id']==ch['id']);self.write_business(c,ch['table'],row)
            # FK-dependent inserts are emitted in the declared source table order above.
            self.write_controls(c,updated,result['affected_scope_ids'])
            for scope in updated['scopes']:
                if scope['id'] in result['affected_scope_ids']:self.enqueue(c,scope);self.audit(c,scope,scope['owner_entity_id'],'business_commit',body['command']+' · local transaction + sovereignty hook')
            result.update(request_id=body['request_id'],scope_id=sid,time=time.time(),scope_versions={s['id']:s['data_version'] for s in updated['scopes'] if s['id'] in result['affected_scope_ids']},idempotent_replay=False)
            c.execute('INSERT INTO sovereignty.command_receipt VALUES (%s,%s,%s,%s)',(core.SPEC['owner_entity_id'],body['request_id'],hashed,Jsonb(result)))
            return result
    def deliver(self,m,s,dest,event_id,plan):
        ds=self.stores[self.entities[dest]['store_id']];key=(s['owner_entity_id'],s['id'],dest)
        # Only approved fields and required policy facts reach destination OPA.
        approved={(r['table'],r['row']['id']):r['row'] for r in plan['rows']}
        facts=[{**r,'row':approved[(r['table'],r['row']['id'])]} for r in core.resources(m,s) if (r['table'],r['row']['id']) in approved]
        if facts:
            recheck=self.evaluate(m,s,dest,ds,facts)
            if not all(d['allow'] for d in recheck):raise RuntimeError('Recipient dataset admission changed; retry')
        with self.tracer.start_as_current_span('operational.import',attributes={'destination.store':ds.id,'dataset.rows':len(plan['rows'])}), ds.connect() as c:
            if c.execute('SELECT event_id FROM sovereignty.inbox WHERE event_id=%s',(event_id,)).fetchone():return 'duplicate'
            prior=c.execute('SELECT data_version,policy_generation,decision_revision FROM sovereignty.manifest WHERE owner_entity_id=%s AND scope_id=%s AND destination_entity_id=%s',key).fetchone()
            if prior and (prior[1]>s['policy_generation'] or prior[2]>s['decision_revision'] or prior[0]>s['data_version']):raise RuntimeError('Stale business manifest fenced')
            for table in reversed(core.ORDER):c.execute(f'DELETE FROM projection.{table} WHERE owner_entity_id=%s AND scope_id=%s AND destination_entity_id=%s',key)
            for table in core.ORDER:
                for r in (r for r in plan['rows'] if r['table']==table):
                    cols=['owner_entity_id','scope_id','destination_entity_id']+list(r['row'])
                    c.execute(f"INSERT INTO projection.{table} ({','.join(cols)}) VALUES ({','.join(['%s']*len(cols))})",list(key)+list(r['row'].values()))
            c.execute('UPSERT INTO sovereignty.manifest VALUES (%s,%s,%s,%s,%s,%s,%s,%s)',key+(s['data_version'],s['policy_generation'],s['decision_revision'],self.entities[dest]['placement_version'],Jsonb({k:v for k,v in plan['row_counts'].items() if v})))
            c.execute('INSERT INTO sovereignty.inbox VALUES (%s,%s)',(event_id,time.time()))
            status='replicated' if plan['rows'] else 'purged'
            # Recipient receipt is scoped; no omitted row IDs or denial explanations are exported.
            c.execute('INSERT INTO sovereignty.audit VALUES (%s,%s,%s)',(str(uuid.uuid4()),time.time(),Jsonb(dict(id=str(uuid.uuid4()),time=time.time(),record_id=s['id'],owner_entity_id=s['owner_entity_id'],destination_entity_id=dest,status=status,dataset='party_relationship_graph',source_receipt=False))))
        return status
    def tick(self):
        with self.lock:
            try:
                with self.stores[self.home].connect() as c:
                    m=self.load(c)
                    for s in m['scopes']:
                        expired=sorted(f"{e}:{g['expires_at']}" for e,g in s['policy']['grants'].items() if g['expires_at']<=time.time())
                        if expired!=s['expired_seen']:s['expired_seen']=expired;s['decision_revision']+=1;self.write_controls(c,m,[s['id']]);self.enqueue(c,s)
                    tasks=c.execute("SELECT id,scope_id,destination_entity_id FROM sovereignty.outbox WHERE status IN ('queued','retry') ORDER BY created_at LIMIT 15").fetchall()
            except Exception:return
            for event,sid,dest in tasks:
                s=core.next_scope(m,str(sid))
                try:
                    plan=self.plan(m,s,dest)
                    if not plan['rows'] and dest not in s['contacted']:status='blocked';reason='No approved graph · never sent'
                    else:
                        if self.paused[self.entities[dest]['store_id']]:raise RuntimeError('Store ingress paused; business reconciliation pending')
                        if plan['rows'] and dest not in s['contacted']:
                            s['contacted'].append(dest)
                            with self.stores[self.home].connect() as c:self.write_controls(c,m,[s['id']])
                        status=self.deliver(m,s,dest,event,plan);reason=f"{len(plan['rows'])} approved business rows · graph v{s['data_version']}"
                    with self.stores[self.home].connect() as c:
                        c.execute('UPDATE sovereignty.outbox SET status=%s,reason=%s,attempts=attempts+1 WHERE id=%s',(status,reason,event));self.audit(c,s,dest,status,reason)
                except Exception as e:
                    with self.stores[self.home].connect() as c:c.execute("UPDATE sovereignty.outbox SET status='retry',reason=%s,attempts=attempts+1 WHERE id=%s",(str(e)[:150],event))
    def snapshot(self):
        with self.lock:
            with self.stores[self.home].connect() as c:
                model=self.load(c)
                events=[r[0] for r in c.execute('SELECT doc FROM sovereignty.audit ORDER BY ts DESC LIMIT 80')]
                queue=[dict(id=str(r[0]),record_id=str(r[1]),source_store=self.home,destination_entity_id=r[2],status=r[3],attempts=r[4],reason=r[5],dataset='party_relationship_graph') for r in c.execute("SELECT id,scope_id,destination_entity_id,status,attempts,reason FROM sovereignty.outbox WHERE status IN ('queued','retry')")]
                receipts=[r[0] for r in c.execute('SELECT result FROM sovereignty.command_receipt')][-10:]
            projections=[];unavailable=[]
            for sid,store in self.stores.items():
                try:
                    with store.connect() as c:
                        for x in c.execute('SELECT owner_entity_id,scope_id,destination_entity_id,data_version,policy_generation,decision_revision,placement_version,row_counts FROM sovereignty.manifest').fetchall():
                            p=dict(owner_entity_id=x[0],scope_id=str(x[1]),destination_entity_id=x[2],store_id=sid,data_version=x[3],policy_generation=x[4],decision_revision=x[5],placement_version=x[6],row_counts=x[7],rows=[])
                            for t in core.ORDER:
                                cols=list(core.TABLES[t]['columns']);cur=c.execute('SELECT '+','.join(cols)+f' FROM projection.{t} WHERE owner_entity_id=%s AND scope_id=%s AND destination_entity_id=%s',x[:3])
                                p['rows'] += [dict(table=t,row={k:v for k,v in clean(dict(zip(cols,r))).items() if k in core.TABLES[t]['export_fields']}) for r in cur.fetchall()]
                            projections.append(p)
                except Exception:unavailable.append(sid)
            return dict(model=model,projections=projections,events=events,queue=queue,transactions=receipts,unavailable_stores=unavailable)
    def preview(self,sid,dest):
        if dest not in self.entities:raise HTTPException(404,'Unknown recipient entity')
        with self.lock,self.stores[self.home].connect() as c:
            m=self.load(c)
            try:s=core.next_scope(m,sid)
            except StopIteration:raise HTTPException(404,'Unknown scope')
            return self.plan(m,s,dest)
    def read(self,sid,dest):
        snapshot=self.snapshot()
        if dest not in self.entities:raise HTTPException(404,'Unknown recipient entity')
        try:s=core.next_scope(snapshot['model'],sid)
        except StopIteration:raise HTTPException(404,'Unknown scope')
        if dest==s['owner_entity_id']:return dict(rows=[{'table':r['table'],'row':r['row']} for r in core.resources(snapshot['model'],s)],data_version=s['data_version'])
        # Base geography/entitlement check before consulting any stored graph.
        try:base=self.stores[self.home].decision(s['policy'],dest)
        except Exception:raise HTTPException(503,'Authority unavailable; fail closed')
        if not base['allow']:raise HTTPException(403,base['reason'])
        if not self.plan(snapshot['model'],s,dest)['rows']:raise HTTPException(403,'No approved business dataset for this scope')
        p=next((p for p in snapshot['projections'] if p['scope_id']==sid and p['destination_entity_id']==dest),None)
        if not p:raise HTTPException(404,'Operational projection not ready')
        if p['decision_revision']!=s['decision_revision'] or p['policy_generation']!=s['policy_generation'] or p['placement_version']!=self.entities[dest]['placement_version']:raise HTTPException(409,'Current business authorisation not yet reconciled; read blocked')
        return p
