"""Real CockroachDB/OPA contracts for the workspace, in full or compact mode."""
import argparse
import json
import os
from pathlib import Path
import time
import uuid

import httpx
import psycopg

ROOT = Path(__file__).resolve().parents[2]
args_parser = argparse.ArgumentParser()
args_parser.add_argument('--compact', action='store_true')
args_parser.add_argument('--restart', action='store_true')
args = args_parser.parse_args()
config = json.loads((ROOT / '.pilot/api/config.json').read_text())
client = httpx.Client(base_url=os.getenv('PILOT_URL', 'http://pilot-gateway:8080'), timeout=25, trust_env=False)
evidence_path = ROOT / 'artifacts/mdm-workspace/restart.json'
evidence_path.parent.mkdir(parents=True, exist_ok=True)


def call(path, identity='crm-sg', method='GET', body=None, status=200):
    headers = {'Authorization': 'Bearer ' + config['principals'][identity]['token']} if identity else {}
    response = client.request(method, path, headers=headers, json=body)
    assert response.status_code == status, (method, response.status_code, status)
    assert len(response.headers.get('X-Trace-ID', '')) == 32
    return response.json()


def sql(query, values=()):
    with psycopg.connect('postgresql://root@db-sg:26257/defaultdb?sslmode=disable') as connection:
        cursor=connection.execute(query, values)
        return cursor.fetchall() if cursor.description else []


def wait_relationship(sid, email):
    deadline = time.monotonic()+40
    while time.monotonic()<deadline:
        response = client.get('/pilot/experience/v1/relationships/'+sid,
            headers={'Authorization':'Bearer '+config['principals']['uk-servicing']['token']})
        if response.status_code == 200:
            data=response.json()
            if any(row['table']=='contact_info' and row['row'].get('value')==email for row in data['rows']):
                assert data['served_from']=='projection'
                return data
        time.sleep(.3)
    raise AssertionError('UK projection did not converge')


status = call('/pilot/api/v1/runtime')
assert status['mode']=='live' and status['database']=='cockroach' and status['status']=='ready'
assert status['footprint']==('mdm-compact' if args.compact else 'full')
assert status['active_regions']==(['SG','UK'] if args.compact else ['SG','UK','US','IN'])
assert status['suspended_regions']==(['US','IN'] if args.compact else [])
assert all(component['state']=='ready' for component in status['components'])
assert len(status['components'])==(6 if args.compact else 11)
assert status['telemetry']==('suspended' if args.compact else 'configured')

if args.restart:
    prior=json.loads(evidence_path.read_text())
    current=call('/pilot/system/v1/customers/'+prior['reference'])
    assert current['global_party_id']==prior['global_party_id']
    wait_relationship(prior['scope_id'],prior['email'])
    found=call('/pilot/system/v1/customers?q='+prior['reference'])
    assert any(c['global_party_id']==prior['global_party_id'] for c in found['items'])
    print('PASS real SQL directory, owner identity and UK projection persist after coordinator/API restart')
    if not args.compact:
        deadline=time.monotonic()+45
        while True:
            response=client.get('/pilot/experience/v1/customers/'+prior['global_party_id'],
                headers={'Authorization':'Bearer '+config['principals']['us-reader']['token']})
            if response.status_code==200:
                result=response.json()
                assert len(result['views'])==1 and result['views'][0]['scope_kind']=='party'
                assert set(result['views'][0]['rows'][0]['row'])=={'id','global_party_id','party_type'}
                assert prior['email'] not in json.dumps(result)
                break
            assert time.monotonic()<deadline,'Deferred US minimum did not resume under current policy'
            time.sleep(.4)
        print('PASS restored full footprint delivers deferred US minimum while retaining the independent relationship exclusion')
    raise SystemExit(0)

for endpoint in ('/pilot/api/v1/runtime','/pilot/system/v1/customers'):
    call(endpoint,identity=None,status=401)
for identity in ('uk-servicing','us-reader'):
    call('/pilot/system/v1/customers',identity=identity,status=403)
for suffix in ('?limit=0','?limit=51','?after=NOT-SYNTHETIC','?q='+'X'*81):
    call('/pilot/system/v1/customers'+suffix,status=422)
print('PASS authenticated dependency evidence, exact footprint, directory identity boundaries and bounded input')

prefix='SYN-UI-'+uuid.uuid4().hex[:12].upper()
customers=[]
for ending in ('A','B'):
    reference=prefix+'-'+ending
    customer=call('/pilot/system/v1/customers/'+reference,method='PUT',body={
        'request_id':str(uuid.uuid4()),'expected_version':0,
        'display_name':'Synthetic Workspace '+ending,'party_type':'PERSON','identity_profile':'global_minimum'})
    customers.append(customer)
page=call('/pilot/system/v1/customers?q='+prefix+'&limit=1')
assert len(page['items'])==1 and page['items'][0]['external_reference']==prefix+'-A'
assert page['next_cursor']==prefix+'-A'
second=call('/pilot/system/v1/customers?q='+prefix+'&limit=1&after='+page['next_cursor'])
assert len(second['items'])==1 and second['items'][0]['external_reference']==prefix+'-B'
assert second['next_cursor'] is None
assert call('/pilot/system/v1/customers?q='+prefix+'&after='+prefix+'-B')['items']==[]
assert call('/pilot/system/v1/customers?q=synthetic%20workspace')['items']
hidden_reference=prefix+'-OTHER'
try:
    sql('INSERT INTO mdm.source_reference VALUES (%s,%s,%s,%s)',
        ('LE-SG-01','other-synthetic-source',hidden_reference,customers[0]['party_id']))
    assert call('/pilot/system/v1/customers?q='+hidden_reference)['items']==[]
    assert call('/pilot/system/v1/customers?q='+hidden_reference+'&source_system=other-synthetic-source&owner_entity_id=LE-GB-02')['items']==[]
finally:
    sql('DELETE FROM mdm.source_reference WHERE owner_entity_id=%s AND source_system=%s AND external_reference=%s',
        ('LE-SG-01','other-synthetic-source',hidden_reference))
print('PASS real SQL source-qualified search, deterministic keyset pagination and other-source nondisclosure')

if args.compact:
    # At least 16 distinct suspended-US partitions must not occupy the relay's 15-task batch.
    existing_pending=sql("SELECT count(DISTINCT scope_id) FROM sovereignty.outbox WHERE destination_entity_id='LE-US-01' AND status IN ('queued','retry')")[0][0]
    for index in range(max(0,16-existing_pending)):
        call('/pilot/system/v1/customers/'+prefix+'-DEFER-'+str(index),method='PUT',body={
            'request_id':str(uuid.uuid4()),'expected_version':0,
            'display_name':'Synthetic Deferred Destination '+str(index),'party_type':'PERSON','identity_profile':'global_minimum'})
    pending=sql("SELECT count(DISTINCT scope_id) FROM sovereignty.outbox WHERE destination_entity_id='LE-US-01' AND status IN ('queued','retry')")[0][0]
    assert pending>=16

email='workspace@example.invalid'
body={'request_id':str(uuid.uuid4()),'expected_version':customers[0]['version'],
      'email':email,'sharing_profile':'uk_servicing_no_us'}
relationship=call('/pilot/system/v1/customers/'+customers[0]['external_reference']+'/relationships',method='POST',body=body)
assert call('/pilot/system/v1/customers/'+customers[0]['external_reference']+'/relationships',method='POST',body=body)['idempotent_replay']
sid=relationship['scope_id']
view=wait_relationship(sid,email)
changed_email='workspace.updated@example.invalid'
command={'request_id':str(uuid.uuid4()),'expected_version':view['data_version'],'command':'update_contact','value':changed_email}
receipt=call('/pilot/experience/v1/relationships/'+sid+'/commands',identity='uk-servicing',method='POST',body=command)
assert receipt['scope_versions'][sid]>view['data_version']
assert call('/pilot/experience/v1/relationships/'+sid+'/commands',identity='uk-servicing',method='POST',body=command)['idempotent_replay']
wait_relationship(sid,changed_email)
assert sql('SELECT count(*) FROM sovereignty.command_receipt WHERE request_id=%s',(command['request_id'],))[0][0]==1
assert sql("SELECT count(*) FROM sovereignty.audit WHERE doc->>'request_id'=%s",(command['request_id'],))[0][0]>=1
evidence_path.write_text(json.dumps({'reference':customers[0]['external_reference'],
    'global_party_id':customers[0]['global_party_id'],'scope_id':sid,'email':changed_email}))
print('PASS real SG/UK creation, policy-scoped contact projection, owner-routed command, replay and mandatory SQL audit')
if args.compact:
    assert sql("SELECT count(*) FROM sovereignty.outbox WHERE destination_entity_id='LE-US-01' AND status IN ('queued','retry')")[0][0]>=16
    print('PASS suspended-US work remains durable without starving eligible UK work; no US purge/exclusion claim')
else:
    call('/pilot/experience/v1/relationships/'+sid,identity='us-reader',status=403)
    print('PASS full-footprint US relationship denial retained')
