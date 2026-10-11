"""Run the browser scenario matrix against a local OPA binary (also needs Node)."""
import argparse,json,os,subprocess,tempfile
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--opa',default='opa');a=p.parse_args()
root=Path(__file__).resolve().parents[2]
with tempfile.TemporaryDirectory() as temp:
    fixture=Path(temp)/'cases.json';env={**os.environ,'PARITY_OUTPUT':str(fixture)}
    subprocess.run(['node',str(root/'poc/tests/engine.mjs')],env=env,check=True)
    cases=json.loads(fixture.read_text());inp=Path(temp)/'input.json';inp.write_text(json.dumps({'cases':[c['input'] for c in cases]}))
    result=subprocess.run([a.opa,'eval','-d',str(root/'poc/policies/federation.rego'),'-i',str(inp),'[d | x := input.cases[_]; d := data.federation.decision with input as x]'],check=True,text=True,capture_output=True)
    actual=json.loads(result.stdout)['result'][0]['expressions'][0]['value']
    assert len(actual)==len(cases)
    for i,(case,decision) in enumerate(zip(cases,actual)):
        for key in ['allow','reason','fields']:assert case['expected'][key]==decision[key],(i,key,case['expected'],decision)
    print('PASS',len(cases),'browser / actual OPA decisions')
