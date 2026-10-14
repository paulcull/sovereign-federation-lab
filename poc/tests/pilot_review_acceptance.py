"""Real API/SQL/OPA regressions for the pilot's authorization review.

Temporarily narrow actual OPA field catalogs, restoring them in finally blocks.
Run sequentially with other acceptance and outage suites on synthetic data only.
"""
import json
from pathlib import Path
import time
import uuid

import httpx
import psycopg
from psycopg.types.json import Jsonb

ROOT = Path(__file__).resolve().parents[2]
config = json.loads((ROOT / '.pilot/api/config.json').read_text())
client = httpx.Client(base_url='http://pilot-gateway:8080',timeout=25,trust_env=False)
direct = httpx.Client(timeout=10,trust_env=False)


def call(method,path,identity='crm-sg',body=None,status=200):
    response = client.request(method,path,json=body,
        headers={'Authorization':'Bearer '+config['principals'][identity]['token']})
    assert response.status_code == status,(method,response.status_code,status)
    return response.json()


def sql(region,statement,args=()):
    with psycopg.connect(f'postgresql://root@db-{region}:26257/defaultdb?sslmode=disable') as c:
        cursor=c.execute(statement,args)
        return cursor.fetchall() if cursor.description is not None else []


def wait(predicate):
    end=time.monotonic()+45
    while time.monotonic()<end:
        if predicate():return
        time.sleep(.4)
    raise AssertionError('Review regression did not converge')


# Seeded Trading permits US at scope level but excludes US on the party resource.
trading=call('GET','/pilot/system/v1/customers/SYN-TRADING')
path='/pilot/experience/v1/relationships/'+trading['party_scope_id']
for freshness in ('owner','projection'):
    call('GET',path+'?freshness='+freshness,'uk-from-us',status=403)
call('GET','/pilot/experience/v1/customers/'+trading['global_party_id'],'uk-from-us',status=404)
print('PASS processing-country resource exclusion for owner, projection and assembled views')

# Aster's shared contact touches a business relationship UK servicing cannot see.
aster=call('GET','/pilot/system/v1/customers/SYN-ASTER')
with psycopg.connect('postgresql://root@db-sg:26257/defaultdb?sslmode=disable') as c:
    sid=str(c.execute("SELECT id FROM sovereignty.scope WHERE primary_party_id=%s AND doc->>'name' LIKE '%%Personal%%'",(aster['party_id'],)).fetchone()[0])
path='/pilot/experience/v1/relationships/'+sid
current=call('GET',path+'?freshness=owner','uk-servicing')
body=dict(request_id=str(uuid.uuid4()),expected_version=current['data_version'],
          command='update_contact',value='review.aster@example.invalid')
for result in (call('POST',path+'/commands','uk-servicing',body),
               call('POST',path+'/commands','uk-servicing',body)):
    assert set(result['scope_versions']) == {sid}
    assert not {'changed','affected_scope_ids'} & set(result)
receipt=sql('sg','SELECT result FROM sovereignty.command_receipt WHERE request_id=%s',(body['request_id'],))[0][0]
assert len(receipt['affected_scope_ids']) == 2
assert any(change['table']=='contact_history' for change in receipt['changed'])
print('PASS command/replay receipts omit hidden scope/history IDs while SQL retains the complete receipt')

reference='SYN-REVIEW-'+uuid.uuid4().hex.upper()
customer=call('PUT','/pilot/system/v1/customers/'+reference,body=dict(request_id=str(uuid.uuid4()),
    expected_version=0,display_name='Synthetic Policy Review',party_type='PERSON',identity_profile='global_minimum'))
party_path='/pilot/experience/v1/relationships/'+customer['party_scope_id']
call('GET',party_path+'?freshness=owner','uk-from-us')
rule=sql('sg',"SELECT rule FROM sovereignty.table_rule WHERE resource_type='party'")[0][0]
try:
    sql('sg',"UPDATE sovereignty.table_rule SET rule=%s WHERE resource_type='party'",
        (Jsonb({**rule,'denied_countries':sorted(set(rule['denied_countries'])|{'US'})}),))
    for freshness in ('owner','projection'):
        call('GET',party_path+'?freshness='+freshness,'uk-from-us',status=403)
finally:
    sql('sg',"UPDATE sovereignty.table_rule SET rule=%s WHERE resource_type='party'",(Jsonb(rule),))
print('PASS processing-country table exclusion independently of permitted UK storage')
relation=call('POST','/pilot/system/v1/customers/'+reference+'/relationships',body=dict(
    request_id=str(uuid.uuid4()),expected_version=customer['version'],sharing_profile='uk_servicing_no_us',email='review@example.invalid'))
sid=relation['scope_id']; path='/pilot/experience/v1/relationships/'+sid

def ready():
    response=client.get(path,headers={'Authorization':'Bearer '+config['principals']['uk-servicing']['token']})
    return response.status_code==200

wait(ready)
for extra in ({},{'value':None}):
    invalid=dict(request_id=str(uuid.uuid4()),expected_version=1,command='update_contact',**extra)
    call('POST',path+'/commands','uk-servicing',invalid,status=422)
    assert not sql('sg','SELECT request_id FROM sovereignty.command_receipt WHERE request_id=%s',(invalid['request_id'],))
assert sql('sg','SELECT value FROM business.contact_info WHERE party_id=%s',(customer['party_id'],))[0][0]=='review@example.invalid'
print('PASS absent/null contact values reject before mutation or receipt; consent commands remain optional-value contracts')


def fields(region):
    response=direct.get(f'http://opa-{region}:8181/v1/data/operational_catalog/party/export_fields')
    response.raise_for_status(); return response.json()['result']


def set_fields(region,value):
    response=direct.put(f'http://opa-{region}:8181/v1/data/operational_catalog/party/export_fields',json=value)
    response.raise_for_status()


original=fields('sg')
try:
    set_fields('sg',[field for field in original if field!='display_name'])
    call('GET',path,'uk-servicing',status=409)
    owner=call('GET',path+'?freshness=owner','uk-servicing')
    assert all('display_name' not in row['row'] for row in owner['rows'] if row['table']=='party')
finally:
    set_fields('sg',original)
wait(ready)
print('PASS source OPA field narrowing fences old projection without changing scope versions')

original=fields('uk'); before=sql('uk','SELECT data_version FROM sovereignty.manifest WHERE scope_id=%s AND destination_entity_id=%s',(sid,'LE-GB-02'))[0][0]
try:
    set_fields('uk',[field for field in original if field!='display_name'])
    current=call('GET',path+'?freshness=owner','uk-servicing')
    body=dict(request_id=str(uuid.uuid4()),expected_version=current['data_version'],
              command='update_contact',value='recipient.review@example.invalid')
    call('POST',path+'/commands','uk-servicing',body)
    wait(lambda:bool(sql('sg',"SELECT id FROM sovereignty.outbox WHERE scope_id=%s AND destination_entity_id='LE-GB-02' AND status='retry' AND attempts>0",(sid,))))
    assert sql('uk','SELECT data_version FROM sovereignty.manifest WHERE scope_id=%s AND destination_entity_id=%s',(sid,'LE-GB-02'))[0][0]==before
    assert sql('uk','SELECT value FROM projection.contact_info WHERE scope_id=%s AND destination_entity_id=%s',(sid,'LE-GB-02'))[0][0]=='review@example.invalid'
finally:
    set_fields('uk',original)
wait(lambda:sql('uk','SELECT value FROM projection.contact_info WHERE scope_id=%s AND destination_entity_id=%s',(sid,'LE-GB-02'))[0][0]=='recipient.review@example.invalid')
wait(ready)
print('PASS narrower recipient OPA rejects import before SQL projection/manifest mutation, then recovers')
