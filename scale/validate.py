"""Validate conservation, isolation of assumptions and queue accounting; not DB acceptance."""
from pathlib import Path
import json,hashlib,sys
import numpy as np
R=Path(__file__).resolve().parents[1];sys.path.insert(0,str(R/'scale'));from simulate import queue,storage
A=json.loads((R/'scale/assumptions.json').read_text());D=json.loads((R/'scale/results/simulation.json').read_text());F=D['fanout']
assert D['assumption_sha256']==hashlib.sha256((R/'scale/assumptions.json').read_bytes()).hexdigest()
assert sum(x['parties'] for x in F['distribution'])==50_000_000
assert sum(x['parties']*x['degree'] for x in F['distribution'])==125_000_000
assert abs(F['mean_degree']-2.5)<1e-10
assert abs(sum(A['traffic']['region_mix'])-1)<1e-10
assert len(D['scenarios'])==16 and len(D['method']['seeds'])==3
for s in D['storage']:
 assert s['source_rows']==sum(t['rows'] for t in s['tables'])
 assert abs(s['logical_tb']-sum(s['logical_components_bytes'].values())/1e12)<1e-9
 assert s['provisioned_tb']>s['replicated_used_tb']>s['logical_tb']
assert storage(1,365)['provisioned_tb']>storage(1,30)['provisioned_tb']
for r in D['recovery']:
 expected=1800/(r['service_factor']-1)
 assert abs(r['drain_seconds']-expected)<1.1
 assert r['series'][0][1]==round(r['initial_jobs']) and r['series'][-1][1]==0
# A single server must conserve work, and independent regions cannot queue each other.
f,w,u=queue(np.array([0.,0.,0.,0.]),np.array([1.,1.,1.,1.]),np.array([0,0,1,2]),[1,1,1])
assert list(f)==[1.,2.,1.,1.] and list(w)==[0.,1.,0.,0.]
f,w,u=queue(np.array([0.,0.,0.]),np.array([1.,1.,1.]),np.array([0,0,0]),[3,1,1],np.array([0,0,-1]))
assert list(f)==[1.,2.,1.]
for s in D['scenarios']:
 for m in s['metrics']:
  assert 0<m['p95_ms']<=m['p99_ms']<=m['p999_ms']
  assert m['p99_min_ms']<=m['p99_ms']<=m['p99_max_ms']
  assert 0<=m['over_1s_pct']<=100
 assert sum(m['samples'] for m in s['metrics'])==(A['queue_model']['samples_per_run']-A['queue_model']['warmup_samples'])*3
peak=next(s for s in D['scenarios'] if s['id']=='100m_peak');surge=next(s for s in D['scenarios'] if s['id']=='100m_125');hot=next(s for s in D['scenarios'] if s['id']=='100m_hotkey')
assert peak['stable'] and not surge['stable'] and not hot['stable']
assert hot['hot_key_demand_ratio']>1 and hot['max_db_demand_ratio']<1
ids={a['id'] for a in json.loads((R/'scale/pilot_actions.json').read_text())};assert len(ids)==24
for a in json.loads((R/'scale/pilot_actions.json').read_text()):
 if a['dependency']!='None':assert all(d in ids and d<a['id'] for d in a['dependency'].split(','))
print('PASS model conservation, overhead arithmetic, recovery drain, region isolation, hot-key serialization, percentile accounting, scenario saturation and pilot dependencies')
