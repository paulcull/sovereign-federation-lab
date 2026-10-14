"""Assertions around real peer/OPA/Collector outages and process restarts."""
import json
from pathlib import Path
import sys
import time
import uuid

import httpx
import psycopg

ROOT = Path(__file__).resolve().parents[2]
CONFIG = json.loads((ROOT / '.pilot/api/config.json').read_text())
STATE = ROOT / 'artifacts/pilot/fault-fixture.json'
client = httpx.Client(base_url='http://pilot-gateway:8080', timeout=35, trust_env=False)


def request(method, path, identity='crm-sg', body=None, status=200):
    response = client.request(method, path, json=body,
        headers={'Authorization':'Bearer ' + CONFIG['principals'][identity]['token']})
    assert response.status_code == status, (method,path.split('?')[0],response.status_code,status)
    return response


def query(sql, args=()):
    with psycopg.connect('postgresql://root@db-sg:26257/defaultdb?sslmode=disable') as c:
        return c.execute(sql,args).fetchall()


def wait_view(state):
    end = time.monotonic() + 45
    while time.monotonic() < end:
        response = client.get('/pilot/experience/v1/relationships/' + state['scope_id'],
            headers={'Authorization':'Bearer ' + CONFIG['principals']['uk-servicing']['token']})
        if response.status_code == 200 and response.json()['data_version'] >= state['version']:
            return response.json()
        time.sleep(.4)
    raise AssertionError('Peer failed to recover a current projection')


def update(state):
    path = '/pilot/experience/v1/relationships/' + state['scope_id']
    latest = request('GET',path+'?freshness=owner','uk-servicing').json()
    body = dict(request_id=str(uuid.uuid4()),expected_version=latest['data_version'],
                command='update_contact',value='fault.pilot@example.invalid')
    response = request('POST',path+'/commands','uk-servicing',body)
    state['version'] = response.json()['scope_versions'][state['scope_id']]
    assert query('SELECT count(*) FROM sovereignty.command_receipt WHERE request_id=%s',(body['request_id'],))[0][0] == 1
    assert query("SELECT count(*) FROM sovereignty.audit WHERE doc->>'record_id'=%s AND doc->>'status'='business_commit'",(state['scope_id'],))[0][0] >= 1
    return body,response


phase = sys.argv[1]
if phase == 'setup':
    reference='SYN-FAULT-'+uuid.uuid4().hex.upper()
    body=dict(request_id=str(uuid.uuid4()),expected_version=0,display_name='Synthetic Fault Customer',party_type='PERSON',identity_profile='global_minimum')
    customer=request('PUT','/pilot/system/v1/customers/'+reference,body=body).json()
    relationship=request('POST','/pilot/system/v1/customers/'+reference+'/relationships',body=dict(
        request_id=str(uuid.uuid4()),expected_version=customer['version'],email='fault.pilot@example.invalid',sharing_profile='uk_servicing_no_us')).json()
    state=dict(reference=reference,customer_body=body,global_party_id=customer['global_party_id'],scope_id=relationship['scope_id'],version=1)
    STATE.parent.mkdir(parents=True,exist_ok=True); STATE.write_text(json.dumps(state))
    wait_view(state)
    print('PASS independent fault fixture committed and delivered over HTTP')
    raise SystemExit(0)

state=json.loads(STATE.read_text()); path='/pilot/experience/v1/relationships/'+state['scope_id']
if phase == 'peer':
    for _ in range(4):update(state)
    request('GET',path,'uk-servicing',status=503)
    assert query("SELECT count(*) FROM sovereignty.outbox WHERE scope_id=%s AND destination_entity_id='LE-GB-02' AND status IN ('queued','retry')",(state['scope_id'],))[0][0] > 0
    print('PASS actual recipient process loss: owner commit/audit survive, delivery pending, no fabricated projection')
elif phase == 'recipient-policy':
    request('GET',path,'uk-servicing',status=503)
    update(state)
    print('PASS actual recipient OPA loss: reads fail closed, valid owner commit and durable retry remain separate')
elif phase == 'source-policy':
    request('GET',path,'uk-servicing',status=503)
    body=dict(request_id=str(uuid.uuid4()),expected_version=state['version'],command='update_contact',value='forbidden.pilot@example.invalid')
    request('POST',path+'/commands','uk-servicing',body,status=503)
    assert query('SELECT count(*) FROM sovereignty.command_receipt WHERE request_id=%s',(body['request_id'],))[0][0] == 0
    print('PASS actual source OPA loss: affected reads and commands fail closed without a business receipt')
elif phase == 'telemetry':
    update(state)
    print('PASS actual Collector loss: API success and mandatory SQL audit remain durable')
elif phase in ('recovered','restart'):
    wait_view(state)
    customer=request('GET','/pilot/system/v1/customers/'+state['reference']).json()
    assert customer['global_party_id']==state['global_party_id']
    replay=request('PUT','/pilot/system/v1/customers/'+state['reference'],body=state['customer_body']).json()
    assert replay['idempotent_replay'] and replay['global_party_id']==state['global_party_id']
    assert query("SELECT count(*) FROM sovereignty.outbox WHERE scope_id=%s AND destination_entity_id='LE-GB-02' AND status='superseded'",(state['scope_id'],))[0][0] > 0
    print('PASS peer/authority/API recovery: identity, source reference, request replay and approved view persisted')
elif phase == 'logs':
    response=request('GET','/pilot/api/v1/context','uk-servicing')
    trace=response.headers['X-Trace-ID']; end=time.monotonic()+35
    with httpx.Client(timeout=10,trust_env=False) as direct:
        while time.monotonic()<end:
            try:
                response=direct.get('http://loki:3100/loki/api/v1/query_range',params={
                    'query':'{service_name="sovereign-pilot-api"} | json | trace_id="'+trace+'"',
                    'limit':'50','start':str(int((time.time()-120)*1e9)),'end':str(int(time.time()*1e9))})
                response.raise_for_status(); result=response.json()
            except (httpx.HTTPError,ValueError):
                time.sleep(.5);continue
            entries=[json.loads(line) for stream in result.get('data',{}).get('result',[]) for _,line in stream['values']]
            evidence = Path('/pilot-telemetry/pilot-api-traces.jsonl')
            spans = [json.loads(line) for line in evidence.read_text().splitlines()
                     if line.strip()] if evidence.exists() else []
            matching = [span for span in spans if span['trace_id'] == trace]
            if entries and matching:
                assert all(set(entry)<= {'timestamp','event','level','method','route','status','duration_ms','trace_id','span_id'} for entry in entries)
                assert all(set(span['attributes']) <= {'http.request.method','http.route','http.response.status_code'} for span in matching)
                break
            time.sleep(.5)
        else:raise AssertionError('Pilot API response, exported span and Loki log did not share a trace ID')
    print('PASS pilot API response, exported span and payload-free Loki log share a trace ID through the Collector')
else:
    raise AssertionError('Unknown fault phase')
STATE.write_text(json.dumps(state))
