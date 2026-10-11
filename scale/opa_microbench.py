"""Observed loopback OPA HTTP timings. No database, WAN, TLS or production claim."""
import sys,json,time,copy,statistics,os,platform,argparse,subprocess,concurrent.futures
from pathlib import Path
import httpx
R=Path(__file__).resolve().parents[1];sys.path.insert(0,str(R/'poc'));import operational_core as core
p=argparse.ArgumentParser();p.add_argument('--opa',default='opa');p.add_argument('--samples',type=int,default=1200);a=p.parse_args()
cat=json.loads((R/'shared/catalog.json').read_text());m=core.seed();s=m['scopes'][0];e=next(e for e in cat['entities'] if e['id']=='LE-GB-02');st=next(st for st in cat['stores'] if st['id']==e['store_id']);base=core.resources(m,s)
proc=subprocess.Popen([a.opa,'run','--disable-telemetry','--server','--addr=127.0.0.1:18189',str(R/'poc/policies')],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
def pct(xs,p):
 xs=sorted(xs);k=(len(xs)-1)*p;lo=int(k);return xs[lo]+(xs[min(lo+1,len(xs)-1)]-xs[lo])*(k-lo)
try:
 client=httpx.Client(base_url='http://127.0.0.1:18189',trust_env=False,timeout=10)
 for _ in range(100):
  try:
   if client.get('/health').status_code==200:break
  except httpx.HTTPError:pass
  time.sleep(.05)
 results=[]
 for n in [1,16,64,256]:
  resources=[copy.deepcopy(base[i%len(base)]) for i in range(n)]
  body={'input':dict(customer=s['policy'],destination_entity=e,destination_store=st,now=1800000000,resources=resources)}
  times=[];evals=[]
  for i in range(a.samples+100):
   start=time.perf_counter_ns();r=client.post('/v1/data/operational/decisions?metrics=true',json=body);r.raise_for_status();d=r.json();elapsed=(time.perf_counter_ns()-start)/1e6;assert len(d['result'])==n
   if i>=100:times.append(elapsed);evals.append(d['metrics']['timer_rego_query_eval_ns']/1e6)
  result=dict(rows=n,samples=a.samples,p50_ms=pct(times,.5),p95_ms=pct(times,.95),p99_ms=pct(times,.99),eval_p99_ms=pct(evals,.99),request_bytes=len(json.dumps(body).encode()),mode='sequential warmed loopback HTTP')
  results.append(result);print(json.dumps(result),flush=True)
 out=dict(kind='observed_microbenchmark',opa_version='1.9.0',environment=dict(python=platform.python_version(),cpu_quota=Path('/sys/fs/cgroup/cpu.max').read_text().strip(),memory_limit_bytes=int(Path('/sys/fs/cgroup/memory.max').read_text())),notes=['Shared sandbox; 8 vCPU quota and 8 GiB memory, not dedicated hardware','100 warm-up requests discarded for each batch size; built-in telemetry explicitly disabled','Sequential HTTP client, JSON encode/decode and OPA response read included','Repeated actual seeded resources; batch-size stress, not a full operational graph benchmark','No CockroachDB, persistence, WAN, TLS, gateway, concurrent tenant load or sustained saturation','Measured results are NOT used as database service-time calibration'],results=results)
 (R/'scale/results/opa_microbench.json').write_text(json.dumps(out,indent=2))
finally:proc.terminate();proc.wait(timeout=10)
