"""Single-process synthetic-data harness; adapters are the regional extension points."""
import os, json, time, uuid, threading, hashlib
from pathlib import Path
from contextlib import asynccontextmanager
import httpx, psycopg
from psycopg.types.json import Jsonb
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, SpanExporter, SpanExportResult
from opentelemetry.sdk.resources import Resource
from seed import make_record, SCENARIOS, REGIONS, CATALOG, ENTITIES, STORE_INFO, placement

LOCK = threading.RLock()  # Single harness serializes policy edits and delivery. Not a distributed fence.
STOP = threading.Event()
PAUSED = {r: False for r in STORE_INFO}
HEALTH = {r: True for r in REGIONS}
class LocalTraceExporter(SpanExporter):
    def export(self, spans):
        folder = Path(os.getenv("TELEMETRY_DIR", "/tmp/sovereign-telemetry")); folder.mkdir(parents=True, exist_ok=True)
        with (folder / "traces.jsonl").open("a") as f:
            for s in spans:
                f.write(json.dumps({"trace_id": f"{s.context.trace_id:032x}", "span": s.name, "attributes": dict(s.attributes or {}), "duration_ms": (s.end_time-s.start_time)/1e6}) + "\n")
        return SpanExportResult.SUCCESS
provider = TracerProvider(resource=Resource.create({"service.name": "sovereign-poc-harness"}))
provider.add_span_processor(SimpleSpanProcessor(LocalTraceExporter()))
if os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"):
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
trace.set_tracer_provider(provider)
TRACER = trace.get_tracer("sovereign.federation")

class RegionStore:
    """Physical store adapter; entity rows remain distinct even on a shared node."""
    def __init__(self, info, index):
        self.info=info; self.id=info['id']; region=info['region']
        self.dsn=os.getenv(f'DB_{region}',f'postgresql://root@127.0.0.1:{26257+index}/defaultdb?sslmode=disable')
        self.opa=os.getenv(f'OPA_{region}',f'http://127.0.0.1:{8181+index}')
        self.http=httpx.Client(timeout=2,trust_env=False)
    def connect(self):return psycopg.connect(self.dsn,connect_timeout=2)
    def initialize(self):
        with self.connect() as c:
            c.execute('CREATE TABLE IF NOT EXISTS fe_config (id STRING PRIMARY KEY, value STRING NOT NULL)')
            digest=hashlib.sha256(json.dumps(CATALOG,sort_keys=True).encode()).hexdigest()
            prior=c.execute("SELECT value FROM fe_config WHERE id='catalog'").fetchone()
            if prior and prior[0]!=digest:raise RuntimeError('Catalog binding changed; controlled migration required')
            if not prior:c.execute("INSERT INTO fe_config VALUES ('catalog',%s)",(digest,))
            c.execute('CREATE TABLE IF NOT EXISTS fe_masters (owner STRING, customer STRING, record_id STRING UNIQUE NOT NULL, doc JSONB NOT NULL, PRIMARY KEY(owner,customer))')
            c.execute('CREATE TABLE IF NOT EXISTS fe_replicas (owner STRING, customer STRING, destination STRING, doc JSONB NOT NULL, PRIMARY KEY(owner,customer,destination))')
            c.execute('CREATE TABLE IF NOT EXISTS fe_fences (owner STRING, customer STRING, destination STRING, generation INT NOT NULL, PRIMARY KEY(owner,customer,destination))')
            c.execute('CREATE TABLE IF NOT EXISTS fe_inbox (id STRING PRIMARY KEY, received_at FLOAT NOT NULL)')
            c.execute("CREATE TABLE IF NOT EXISTS fe_outbox (id STRING PRIMARY KEY, record_id STRING NOT NULL, destination STRING NOT NULL, status STRING NOT NULL, attempts INT NOT NULL DEFAULT 0, reason STRING NOT NULL DEFAULT '', created_at FLOAT NOT NULL)")
            c.execute('CREATE TABLE IF NOT EXISTS fe_audit (id STRING PRIMARY KEY, ts FLOAT NOT NULL, doc JSONB NOT NULL)')
    def decision(self,customer,destination):
        entity=ENTITIES[destination];store=STORE_INFO[entity['store_id']]
        with TRACER.start_as_current_span('opa.entity_placement',attributes={'source.store':self.id,'destination.store':store['id'],'destination.entity':destination}) as span:
            res=self.http.post(self.opa+'/v1/data/federation/decision',json={'input':{'customer':customer,'destination_entity':entity,'destination_store':store,'now':time.time()}})
            res.raise_for_status();result=res.json().get('result')
            if not isinstance(result,dict) or not isinstance(result.get('allow'),bool):raise RuntimeError('OPA decision missing; fail closed')
            span.set_attribute('policy.allowed',result['allow']);return result
STORES={s['id']:RegionStore(s,i) for i,s in enumerate(CATALOG['stores'])}
from operational import OperationalRuntime
OPERATIONAL=OperationalRuntime(STORES,ENTITIES,STORE_INFO,LOCK,PAUSED,TRACER)

def source_store(d):return d.get('home_store_id',ENTITIES[d['owner_entity_id']]['store_id'])
def audit(c,d,destination,status,reason,payload_name=True):
    target=ENTITIES.get(destination)
    event=dict(id=str(uuid.uuid4()),time=time.time(),record_id=d['id'],global_customer_id=d['global_customer_id'],name=d.get('name','Projection') if payload_name else 'Projection',owner_entity_id=d['owner_entity_id'],destination_entity_id=destination,source_store=source_store(d),destination_store=target['store_id'] if target else source_store(d),status=status,reason=reason,generation=d.get('generation',1),placement_version=target['placement_version'] if target else 1)
    c.execute('INSERT INTO fe_audit VALUES (%s,%s,%s)',(event['id'],event['time'],Jsonb(event)))
def candidates(d):return sorted((set(d['allowed_entities'])|set(d['denied_entities'])|set(d['grants'])|set(d.get('contacted',[])))-{d['owner_entity_id']})
def enqueue(c,d):
    for dest in candidates(d):c.execute("INSERT INTO fe_outbox (id,record_id,destination,status,created_at) VALUES (%s,%s,%s,'queued',%s)",(str(uuid.uuid4()),d['id'],dest,time.time()))
def validate(d):
    for k in ['name','email','tier','notes','scenario','purpose']:
        if not isinstance(d.get(k),str) or len(d[k])>2000:raise HTTPException(422,f'Invalid {k}')
    owner=ENTITIES.get(d.get('owner_entity_id'))
    if not owner or not placement(owner):raise HTTPException(422,'Owner has no approved physical placement')
    for k in ['allowed_entities','denied_entities','allowed_countries','denied_countries']:
        if not isinstance(d.get(k),list) or any(not isinstance(v,str) for v in d[k]):raise HTTPException(422,f'Invalid {k}')
    if any(e not in ENTITIES for e in d['allowed_entities']+d['denied_entities']):raise HTTPException(422,'Unknown legal entity')
    if d['owner_entity_id'] in d['denied_entities']:raise HTTPException(422,'Owner exclusion requires migration; not supported')
    country=STORE_INFO[owner['store_id']]['country']
    if country in d['denied_countries'] or country not in d['allowed_countries']:raise HTTPException(422,'Policy excludes the authoritative physical store')
    if not isinstance(d.get('grants'),dict):raise HTTPException(422,'Invalid grants')
    for dest,g in d['grants'].items():
        if dest not in ENTITIES or not isinstance(g,dict) or not isinstance(g.get('active'),bool) or g.get('profile') not in ['minimal','contact'] or not isinstance(g.get('expires_at'),(float,int)) or g.get('purpose')!='servicing':raise HTTPException(422,'Invalid grant')
def persist(c,d):c.execute('UPDATE fe_masters SET doc=%s WHERE record_id=%s',(Jsonb(d),d['id']))
def create(d):
    validate(d)
    customer=d.get('global_customer_id',str(uuid.uuid4()))
    try:uuid.UUID(customer)
    except (ValueError,TypeError,AttributeError):raise HTTPException(422,'Global customer ID must be UUID')
    d={**d,'id':str(uuid.uuid4()),'global_customer_id':customer,'version':1,'generation':1,'contacted':[],'expired_seen':[],'created_at':time.time(),'home_store_id':ENTITIES[d['owner_entity_id']]['store_id'],'owner_placement_version':ENTITIES[d['owner_entity_id']]['placement_version']}
    with STORES[source_store(d)].connect() as c:
        if c.execute('SELECT record_id FROM fe_masters WHERE owner=%s AND customer=%s',(d['owner_entity_id'],customer)).fetchone():raise HTTPException(409,'Customer relationship already exists for this owner')
        c.execute('INSERT INTO fe_masters VALUES (%s,%s,%s,%s)',(d['owner_entity_id'],customer,d['id'],Jsonb(d)))
        enqueue(c,d);audit(c,d,d['owner_entity_id'],'committed','Entity-owned record + durable outbox')
    return d
def find_record(rid):
    for s in STORES.values():
        with s.connect() as c:row=c.execute('SELECT doc FROM fe_masters WHERE record_id=%s',(rid,)).fetchone()
        if row:return row[0]
    raise HTTPException(404,'Relationship record not found')
def deliver(dest,d,task,decision):
    store=STORES[ENTITIES[dest]['store_id']]
    facts={k:d[k] for k in ['id','global_customer_id','owner_entity_id','allowed_entities','denied_entities','allowed_countries','denied_countries','grants','generation','purpose']}
    confirm=store.decision(facts,dest)
    if confirm['allow']!=decision['allow']:raise RuntimeError('Admission changed; retry')
    key=(d['owner_entity_id'],d['global_customer_id'],dest)
    with store.connect() as c:
        if c.execute('SELECT id FROM fe_inbox WHERE id=%s',(task,)).fetchone():return 'duplicate'
        row=c.execute('SELECT generation FROM fe_fences WHERE owner=%s AND customer=%s AND destination=%s',key).fetchone()
        if row and row[0]>d['generation']:raise RuntimeError('Stale generation fenced')
        c.execute('UPSERT INTO fe_fences VALUES (%s,%s,%s,%s)',key+(d['generation'],))
        if confirm['allow']:
            projection=dict(record_id=d['id'],global_customer_id=d['global_customer_id'],owner_entity_id=d['owner_entity_id'],destination_entity_id=dest,store_id=store.id,version=d['version'],generation=d['generation'],placement_version=confirm['placement_version'],fields={k:d[k] for k in confirm['fields']},replicated_at=time.time())
            c.execute('UPSERT INTO fe_replicas VALUES (%s,%s,%s,%s)',key+(Jsonb(projection),));status='replicated'
        else:
            c.execute('DELETE FROM fe_replicas WHERE owner=%s AND customer=%s AND destination=%s',key);status='purged'
        c.execute('INSERT INTO fe_inbox VALUES (%s,%s)',(task,time.time()))
        audit(c,d,dest,status,confirm['reason'],False)
    return status
def tick():
    with LOCK:
        for sid,store in STORES.items():
            try:
                with store.connect() as c:
                    masters={x[0]:x[1] for x in c.execute('SELECT record_id,doc FROM fe_masters')}
                    for d in masters.values():
                        expired=sorted(f"{e}:{g['expires_at']}" for e,g in d['grants'].items() if g['expires_at']<=time.time())
                        if expired!=d.get('expired_seen',[]):d['expired_seen']=expired;d['generation']+=1;persist(c,d);enqueue(c,d)
                    tasks=c.execute("SELECT id,record_id,destination FROM fe_outbox WHERE status IN ('queued','retry') ORDER BY created_at LIMIT 30").fetchall()
            except Exception:continue
            for task,rid,dest in tasks:
                d=masters[rid]
                try:
                    with TRACER.start_as_current_span('federation.entity_transfer',attributes={'source.store':sid,'destination.entity':dest,'policy.generation':d['generation']}):
                        dec=store.decision(d,dest)
                        if not dec['allow'] and dest not in d['contacted']:
                            status='placement_blocked' if 'placement' in dec['reason'] else 'blocked';reason=dec['reason']+' · never sent'
                        else:
                            ds=ENTITIES[dest]['store_id']
                            if PAUSED[ds]:raise RuntimeError('Store ingress paused'+('; purge pending' if not dec['allow'] else ''))
                            if dec['allow'] and dest not in d['contacted']:
                                d['contacted'].append(dest)
                                with store.connect() as c:persist(c,d)
                            status=deliver(dest,d,task,dec);reason=dec['reason']
                        with store.connect() as c:
                            c.execute('UPDATE fe_outbox SET status=%s,reason=%s,attempts=attempts+1 WHERE id=%s',(status,reason,task));audit(c,d,dest,status,reason)
                except Exception as e:
                    with store.connect() as c:c.execute("UPDATE fe_outbox SET status='retry',reason=%s,attempts=attempts+1 WHERE id=%s",(str(e)[:150],task))
def worker():
    while not STOP.is_set():
        try:
            tick()
            OPERATIONAL.tick()
        except Exception as e:print('Worker retry:',type(e).__name__,flush=True)
        STOP.wait(.8)
@asynccontextmanager
async def lifespan(app):
    for attempt in range(60):
        try:
            for s in STORES.values():s.initialize()
            break
        except Exception:
            if attempt==59:raise
            time.sleep(1)
    with LOCK:
        count=0
        for s in STORES.values():
            with s.connect() as c:
                existing=[r[0] for r in c.execute('SELECT doc FROM fe_masters')]
                count+=len(existing)
                for d in existing:
                    e=ENTITIES[d['owner_entity_id']]
                    if d.get('home_store_id')!=s.id or e['store_id']!=s.id or d.get('owner_placement_version')!=e['placement_version']:
                        raise RuntimeError('Existing owner placement changed. Controlled migration required; refusing startup.')
        if not count:
            for i in range(33):create(make_record(i))
            # One person, two authoritative entity relationships: distinct data and policy.
            first=make_record(101,'home-only','LE-GB-01');create(first)
            second={**first,'owner_entity_id':'LE-GB-02','tier':'Business'};create(second)
    OPERATIONAL.initialize()
    if MIGRATION is not None:MIGRATION.initialize()
    STOP.clear();thread=threading.Thread(target=worker,daemon=True);thread.start()
    yield
    STOP.set();thread.join(timeout=5);provider.shutdown()
app=FastAPI(title='Sovereign Federation Lab · CockroachDB',lifespan=lifespan,docs_url='/api-docs',redoc_url=None)
from lab_health import router as health_router
app.include_router(health_router())
class Generate(BaseModel):
    count:int=Field(1,ge=1,le=100)
    scenario:str='mixed'
class Pause(BaseModel):paused:bool
@app.get('/api/state')
def state():
    with LOCK:
        records=[];events=[];queue=[];stores=[]
        for sid,s in STORES.items():
            try:
                with s.connect() as c:
                    local=[r[0] for r in c.execute('SELECT doc FROM fe_masters')];records+=local
                    projections=[r[0] for r in c.execute('SELECT doc FROM fe_replicas')]
                    events += [r[0] for r in c.execute('SELECT doc FROM fe_audit ORDER BY ts DESC LIMIT 80')]
                    queue += [dict(zip(['id','record_id','source_store','destination_entity_id','status','attempts','reason'],row)) for row in c.execute("SELECT id,record_id,%s,destination,status,attempts,reason FROM fe_outbox WHERE status IN ('queued','retry')",(sid,))]
                    stores.append({**s.info,'online':True,'paused':PAUSED[sid],'masters':len(local),'replicas':projections})
            except Exception:stores.append({**s.info,'online':False,'paused':PAUSED[sid],'masters':None,'replicas':[]})
        operational=OPERATIONAL.snapshot()
        events+=operational['events'];queue+=operational['queue']
        return dict(schema_version=3,operational=operational,mode='live',customers=sorted(records,key=lambda d:d['created_at'],reverse=True),stores=stores,entities=CATALOG['entities'],events=sorted(events,key=lambda e:e['time'],reverse=True)[:150],queue=queue,now=time.time())
@app.get('/api/catalog')
def catalog():return CATALOG
@app.post('/api/generate')
def generate(body:Generate):
    if body.scenario!='mixed' and body.scenario not in SCENARIOS:raise HTTPException(422,'Unknown scenario')
    with LOCK:return {'created':[create(make_record(int(time.time()*1000)%10000+i,None if body.scenario=='mixed' else body.scenario)) for i in range(body.count)]}
@app.post('/api/records')
def add_record(body:dict):
    with LOCK:return create(body)
@app.patch('/api/records/{rid}/policy')
def policy(rid:str,body:dict):
    with LOCK:
        d=find_record(rid)
        if body.get('expected_generation')!=d['generation']:raise HTTPException(409,'Policy changed; refresh before applying')
        for key in ['allowed_entities','denied_entities','allowed_countries','denied_countries','grants']:
            if key in body:d[key]=body[key]
        validate(d);d['generation']+=1
        with STORES[source_store(d)].connect() as c:persist(c,d);enqueue(c,d);audit(c,d,d['owner_entity_id'],'policy','Entity / geography policy changed')
        return d
@app.post('/api/records/{rid}/touch')
def touch(rid:str):
    with LOCK:
        d=find_record(rid);d['version']+=1;d['tier']='Premier' if d['tier']!='Premier' else 'Retail'
        with STORES[source_store(d)].connect() as c:persist(c,d);enqueue(c,d)
        return d
@app.post('/api/records/{rid}/relationship')
def relationship(rid:str,body:dict):
    with LOCK:
        d=find_record(rid)
        owner=body.get('owner_entity_id')
        if owner not in ENTITIES:raise HTTPException(422,'Unknown new owner')
        try:dec=STORES[source_store(d)].decision(d,owner)
        except Exception:raise HTTPException(503,'Identity disclosure authority unavailable')
        if not dec['allow']:raise HTTPException(403,'Cannot disclose the shared global ID: '+dec['reason'])
        fresh=make_record(int(time.time())%1000,'home-only',owner)
        fresh.update(global_customer_id=d['global_customer_id'],allowed_countries=d['allowed_countries'][:],denied_countries=d['denied_countries'][:])
        return create(fresh)
@app.post('/api/stores/{sid}/pause')
def pause(sid:str,body:Pause):
    if sid not in STORES:raise HTTPException(404,'Unknown physical store')
    with LOCK:PAUSED[sid]=body.paused
    return {'store_id':sid,'paused':body.paused}
@app.get('/api/records/{rid}/read/{entity}')
def read_record(rid:str,entity:str):
    if entity not in ENTITIES:raise HTTPException(404,'Unknown entity')
    with LOCK:
        d=find_record(rid)
        if entity==d['owner_entity_id']:return d
        try:dec=STORES[source_store(d)].decision(d,entity)
        except Exception:raise HTTPException(503,'Authority unavailable; fail closed')
        if not dec['allow']:raise HTTPException(403,dec['reason'])
        with STORES[ENTITIES[entity]['store_id']].connect() as c:row=c.execute('SELECT doc FROM fe_replicas WHERE owner=%s AND customer=%s AND destination=%s',(d['owner_entity_id'],d['global_customer_id'],entity)).fetchone()
        if not row:raise HTTPException(404,'Projection not ready')
        if row[0]['generation']!=d['generation'] or row[0]['placement_version']!=ENTITIES[entity]['placement_version']:raise HTTPException(409,'Projection awaiting current policy / placement')
        return row[0]
@app.post('/api/entities/{entity}/placement-plan')
def placement_plan(entity:str,body:dict):
    if entity not in ENTITIES or body.get('store_id') not in STORE_INFO:raise HTTPException(422,'Unknown entity or store')
    with LOCK:
        e=ENTITIES[entity];target=STORE_INFO[body['store_id']];snapshot=state()
        affected=[d for d in snapshot['customers'] if d['owner_entity_id']==entity or entity in candidates(d)]
        conflicts=[d['id'] for d in affected if target['country'] in d['denied_countries'] or target['country'] not in d['allowed_countries']]
        return dict(entity_id=entity,current_store=e['store_id'],proposed_store=target['id'],approved=target['country'] in e['approved_countries'] and not conflicts,entity_country_allowed=target['country'] in e['approved_countries'],affected_records=len(affected),conflicting_records=conflicts,placement_version=e['placement_version'],applied=False,stages=['Validate residency','Fence old writer','Copy & reconcile','Verify destination','Switch versioned routing','Reconcile old copies'])
@app.get('/api/operational')
def operational_snapshot():return OPERATIONAL.snapshot()
@app.post('/api/operational/scopes/{sid}/commands')
def operational_command(sid:str,body:dict):return OPERATIONAL.command(sid,body)
@app.get('/api/operational/scopes/{sid}/preview/{entity}')
def operational_preview(sid:str,entity:str):return OPERATIONAL.preview(sid,entity)
@app.get('/api/operational/scopes/{sid}/read/{entity}')
def operational_read(sid:str,entity:str):return OPERATIONAL.read(sid,entity)

from migration import MigrationRuntime,make_router
if os.getenv('MIGRATION_STORAGE','cockroach')!='cockroach':raise RuntimeError('The development service requires CockroachDB; no SQLite fallback is permitted')
MIGRATION=MigrationRuntime(mode='cockroach',tracer=TRACER) if os.getenv('MIGRATION_ENABLED')=='1' else None
if MIGRATION is not None:app.include_router(make_router(MIGRATION))
app.mount('/',StaticFiles(directory=os.getenv('UI_DIR',str(Path(__file__).resolve().parents[1]/'dist')),html=True),name='monitor')
