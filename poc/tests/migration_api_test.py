"""HTTP contracts, trace attributes and cutover crash gaps against real SQLite."""
import tempfile,sys,os
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from fastapi import FastAPI
from fastapi.testclient import TestClient
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from migration import MigrationRuntime,make_router,OWNER
from migration_test import writers,copy_all

with tempfile.TemporaryDirectory() as folder:
    os.environ['OTEL_SDK_DISABLED']='false'
    from opentelemetry.sdk.trace.sampling import ALWAYS_ON
    provider=TracerProvider(sampler=ALWAYS_ON);export=InMemorySpanExporter();provider.add_span_processor(SimpleSpanProcessor(export))
    r=MigrationRuntime(mode='sqlite',folder=folder,opa_url='',tracer=provider.get_tracer('test'));r.initialize()
    app=FastAPI();app.include_router(make_router(r));client=TestClient(app)
    def post(action,body=None,status=200):
        response=client.post('/api/migration/'+action,json=body or {});assert response.status_code==status,response.text;return response.json()
    assert client.get('/api/migration').json()['mode']=='persistent-sqlite'
    post('reset',{'scenario':'wrong'},409)
    post('register');assert client.get('/api/migration/read/IN').status_code==409
    post('plan');post('start');post('copy',{'batch':'eight'},409);post('copy',{'batch':33},409)
    copy_all(r);post('validate')
    # Simulate death between durable source fence and control checkpoint.
    with r.stores['SG'].tx() as q:q('UPDATE mig_authority SET writable=0 WHERE owner=?',(OWNER,))
    r.initialize();assert r.control()['phase']=='FENCED';assert writers(r)==[]
    post('write',{},409)
    # Fail exactly after durable ACTIVATING route checkpoint, before target enable.
    original=r.save
    def crashing_save(c):
        original(c)
        if c['phase']=='ACTIVATING':raise RuntimeError('injected process death')
    r.save=crashing_save
    try:r.command('activate')
    except RuntimeError:pass
    else:raise AssertionError('Crash gap not reached')
    r.save=original
    assert r.control()['phase']=='ACTIVATING';assert writers(r)==[]
    r.initialize();post('write',{},409);post('activate');assert writers(r)==['IN']
    first=post('write',{'request_id':'http-1','kind':'update'});assert first['home']=='IN'
    assert post('write',{'request_id':'http-1','kind':'update'})['replayed']
    post('write',{'request_id':'http-1','kind':'create'},409)
    post('write',{'store':'SG'},409);post('stale',{},409);post('rollback',{},409)
    assert client.get('/api/migration/read/SG').status_code==409
    assert client.get('/api/migration/read/IN').status_code==200
    post('other');count=r.snapshot()['other_writes'];post('reset',{'scenario':'synthetic-india'})
    assert writers(r)==['SG'] and r.snapshot()['other_writes']==count
    spans=export.get_finished_spans();assert any(s.name=='migration.activate' for s in spans)
    assert {'guard','operational','reconciliation'}<={s.attributes['work.class'] for s in spans}
    assert all(set(s.attributes)=={'work.class'} for s in spans)
    provider.shutdown()
print('PASS HTTP status/read guards, bounded inputs, source-fence and target-activation crash gaps, idempotency, scoped reset and OTel span attributes. No OTLP exporter/network claim.')
