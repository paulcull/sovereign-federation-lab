"""Pure Python command / graph invariants and actual OPA evaluation; no database needed."""
import sys,json,subprocess,os,tempfile,argparse,copy
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'poc'))
import operational_core as core
p=argparse.ArgumentParser();p.add_argument('--opa',default='opa');a=p.parse_args()
cat=json.loads((ROOT/'shared/catalog.json').read_text());entities={e['id']:e for e in cat['entities']};stores={s['id']:s for s in cat['stores']}
def plan(m,s,d):
    e=entities[d];inp=dict(customer=s['policy'],destination_entity=e,destination_store=stores[e['store_id']],now=1800000000,resources=core.resources(m,s))
    proc=subprocess.run([a.opa,'eval','--stdin-input','-d',str(ROOT/'poc/policies'),'data.operational.decisions'],input=json.dumps(inp),text=True,capture_output=True,check=True)
    decisions=json.loads(proc.stdout)['result'][0]['expressions'][0]['value'];assert len(decisions)==len(inp['resources']);return core.manifest(m,s,decisions)
def check_graph(m):
    keys={(t,r['id']) for t,rs in m['rows'].items() for r in rs}
    for t,rs in m['rows'].items():
        for r in rs:
            assert set(r)==set(core.TABLES[t]['columns']),(t,r)
            for parent in core.TABLES[t]['parents']:
                if r.get(parent['field']):assert (parent['table'],r[parent['field']]) in keys
    for s in m['scopes']:core.resources(m,s)
m=core.seed();check_graph(m);s=m['scopes'][0];party=m['scopes'][2]
assert len(plan(m,party,'LE-US-01')['rows'])==1
assert not plan(m,s,'LE-US-01')['rows']
assert not plan(m,m['scopes'][3],'LE-US-01')['rows']
pp=plan(m,s,'LE-GB-02');assert pp['row_counts']['contact_info']==1
# Even a misbound relationship cannot be exported through an identity-only scope.
bad=copy.deepcopy(m);bad['bindings'].append(dict(scope_id=party['id'],resource_type='relationship',resource_id=s['root_id']))
assert plan(bad,party,'LE-GB-02')['row_counts']['relationship']==0
assert set(next(r['row'] for r in plan(m,party,'LE-US-01')['rows']))=={'id','global_party_id','party_type'}
for cmd in ['update_contact','withdraw_consent','restore_consent','open_holding','classify_restricted','classify_internal','log_contact','table_contact_local','table_contact_restore','exclude_party_us','restore_party_us']:
    prev=copy.deepcopy(m);m,result=core.command(m,s['id'],{'command':cmd,'expected_version':core.next_scope(m,s['id'])['data_version']});check_graph(m)
    if cmd=='update_contact':assert len(result['affected_scope_ids'])==2
    current=core.next_scope(m,s['id']);pl=plan(m,current,'LE-GB-02')
    if cmd in ['withdraw_consent','table_contact_local']:assert pl['row_counts']['contact_info']==0
    if cmd=='restore_consent':assert pl['row_counts']['contact_info']==1
    if cmd=='exclude_party_us':assert not plan(m,core.next_scope(m,party['id']),'LE-US-01')['rows'];assert len(result['affected_scope_ids'])==3
    keys={(r['table'],r['row']['id']) for r in pl['rows']}
    for r in pl['rows']:
        assert 'balance' not in r['row']
        for parent in core.TABLES[r['table']]['parents']:
            if r['row'].get(parent['field']):assert (parent['table'],r['row'][parent['field']]) in keys
before=copy.deepcopy(m)
try:core.command(m,s['id'],{'command':'update_contact','expected_version':1});raise AssertionError('Expected stale command rejection')
except ValueError:assert m==before
print('PASS Python core + actual OPA: 11 commands, typed source graph, dependency closure, global party, field restrictions and table/key precedence')
# Browser mirror parity against the same actual Rego bundle.
with tempfile.TemporaryDirectory() as tmp:
    fixture=Path(tmp)/'cases.json';subprocess.run(['node',str(ROOT/'poc/tests/operational_engine.mjs')],env={**os.environ,'PARITY_OUTPUT':str(fixture)},check=True)
    cases=json.loads(fixture.read_text());inp=Path(tmp)/'inputs.json';inp.write_text(json.dumps({'cases':[c['input'] for c in cases]}))
    r=subprocess.run([a.opa,'eval','-d',str(ROOT/'poc/policies'),'-i',str(inp),'[d | x := input.cases[_]; d := data.operational.decisions with input as x]'],check=True,capture_output=True,text=True)
    actual=json.loads(r.stdout)['result'][0]['expressions'][0]['value'];assert len(actual)==len(cases)
    for i,(case,ds) in enumerate(zip(cases,actual)):assert case['expected']==ds,(i,case['expected'],ds)
    print('PASS',len(cases),'browser / OPA operational decisions across all 30 entities;',sum(len(c['expected']) for c in cases),'row decisions')
