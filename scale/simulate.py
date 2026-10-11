"""Reproducible scenario model; never claims to instantiate or benchmark 100M DB rows."""
from pathlib import Path
import json,math,time,heapq,csv,hashlib
import numpy as np
R=Path(__file__).resolve().parents[1];A=json.loads((R/'scale/assumptions.json').read_text());OUT=R/'scale/results';OUT.mkdir(exist_ok=True)
REGIONS=['SG','UK','US'];OPS=A['queue_model']['operation_names']
def quant(x):return {f'p{q}':float(np.percentile(x,q)) for q in [50,95,99,99.9]}
def storage(scale=1,history_days=None,copies=None):
 p=A['population']['parties']*scale;r=A['population']['relationships']*scale;st=A['storage'];tr=A['traffic'];hd=history_days or st['history_days'];copies=tr['remote_projection_copies_per_relationship'] if copies is None else copies
 counts={'party':(p,400),'relationship':(r,256),'party_relationship':(r*1.25,160),'product_holding':(r*2,320),'contact_info':(p*2,320),'consent':(r*2,220),'preference':(r,180),'contact_history':(tr['normal_writes_per_second']*scale*st['history_fraction_of_normal_writes']*86400*hd,700),'party_alternate_id':(p*2,180),'relationship_alternate_id':(r,180),'holding_alternate_id':(r*2,180),'classification':(p+r+r*2,160)}
 tables=[dict(table=t,rows=int(n),row_bytes=b,logical_bytes=n*b) for t,(n,b) in counts.items()];business=sum(t['logical_bytes'] for t in tables)
 components={'source_business':business,'remote_relationship_graphs':r*copies*st['remote_graph_bytes'],'additional_party_minima':p*2*96,'scope_and_binding_controls':(p+r)*256+r*1.25*72,'resource_exceptions':(p+r)*.02*192,'recipient_manifests':(r*copies+p*2)*160,'live_outbox_5_minutes':tr['peak_writes_per_second']*scale*300*512,'hot_audit':tr['normal_writes_per_second']*scale*86400*st['hot_audit_days']*st['audit_records_per_write']*st['audit_row_bytes']}
 logical=sum(components.values());physical=logical*st['index_multiplier']*st['kv_multiplier']*st['mvcc_multiplier']*st['replication_factor'];audit_daily=tr['normal_writes_per_second']*scale*86400*st['audit_records_per_write']*st['audit_row_bytes']
 return dict(parties=int(p),relationships=int(r),source_rows=int(sum(t['rows'] for t in tables)),tables=tables,logical_components_bytes=components,logical_tb=logical/1e12,replicated_used_tb=physical/1e12,provisioned_tb=physical/st['target_disk_fill']/1e12,audit_daily_gb=audit_daily/1e9,audit_annual_archive_tb=audit_daily*365/1e12,history_days=hd,copies=copies)
def queue(arrival,service,regions,slots,keys=None):
 completion=np.empty(len(arrival));waiting=np.empty(len(arrival));util=[]
 for region in range(3):
  ids=np.flatnonzero(regions==region);ids=ids[np.argsort(arrival[ids],kind='stable')];heap=[0.0]*int(slots[region]);heapq.heapify(heap);key_ready={}
  for i in ids:
   free=heap[0];key=int(keys[i]) if keys is not None else -1;start=max(float(arrival[i]),free,key_ready.get(key,0) if key>=0 else 0);finish=start+float(service[i]);heapq.heapreplace(heap,finish);completion[i]=finish;waiting[i]=start-arrival[i]
   if key>=0:key_ready[key]=finish
  horizon=max(float(arrival[ids].max()-arrival[ids].min()),1e-6) if len(ids) else 1
  util.append(float(service[ids].sum()/horizon/slots[region]))
 return completion,waiting,util
DEGREES=np.array([1,6,50,610]);PARTY_PROBS=np.array([.9,.09,.009,.001]);SIZE_PROBS=DEGREES*PARTY_PROBS/(DEGREES@PARTY_PROBS)
def fanout():
 rng=np.random.default_rng(A['seed']);mixed=.8*PARTY_PROBS+.2*SIZE_PROBS;d=rng.choice(DEGREES,1000000,p=mixed);copies=A['traffic']['remote_projection_copies_per_relationship'];jobs=rng.binomial(d, min(copies,1))
 w=A['traffic']['peak_writes_per_second'];raw_jobs=w*(.9+.1*float(DEGREES@mixed))*copies;optimized=w*(.9*copies+.1*2)
 # 0.6 ms per scope touched is an explicit illustrative serial-hook cost.
 return dict(distribution=[dict(parties=round(A['population']['parties']*p),degree=int(n),party_share=float(p),edge_share=float(z)) for n,p,z in zip(DEGREES,PARTY_PROBS,SIZE_PROBS)],mean_degree=float(DEGREES@PARTY_PROBS),mean_event_degree=float(DEGREES@mixed),fanout_quantiles=quant(d),candidate_job_quantiles=quant(jobs),inline_scope_hook_ms=quant(d*.6),baseline_jobs_per_second=raw_jobs,optimized_jobs_per_second=optimized,full_snapshot_mb_s=raw_jobs*A['storage']['full_graph_event_bytes']/1e6,optimized_delta_mb_s=optimized*A['storage']['delta_event_bytes']/1e6,notes=['Party participation totals 125M edges for 100M relationships: average 1.25 parties per relationship','80% uniform party events + 20% degree-weighted events; synthetic stress assumption','Optimized route count assumes canonical shared-resource delta at no more than two remote physical stores, plus recipient-scoped checks; not implemented in the PoC','Without this resource-level deduplication, ordinary deltas still have the baseline destination-job fanout'])
def run(cfg,seed):
 q=A['queue_model'];rng=np.random.default_rng(seed);n=q['samples_per_run'];scale=cfg.get('population_scale',1);load=cfg.get('load',1);normal=cfg.get('normal',False)
 rps=(11000 if normal else 35000)*scale*load;mix=[.4,.5090909091,.0909090909] if normal else list(A['traffic']['operation_mix'].values());mix=np.array(mix);mix/=mix.sum();op=rng.choice(3,n,p=mix);region=rng.choice(3,n,p=cfg.get('region_mix',A['traffic']['region_mix']));arr=np.cumsum(rng.exponential(1/rps,n));warm=q['warmup_samples'];service_multiplier=cfg.get('service_multiplier',1);slots_multiplier=cfg.get('slots_multiplier',1)
 hot=(op==2)&(rng.random(n)<cfg.get('hot_key_share',0));region[hot]=0
 gateway=rng.lognormal(np.log(q['gateway_median_ms']),.45,n)/1000
 t,wg,ug=queue(arr,gateway,region,q['gateway_slots']);opa=rng.lognormal(np.log(q['opa_median_ms']),.5,n)/1000;t,wo,uo=queue(t,opa,region,q['opa_slots'])
 # Cardinality affects assumed cache-miss rate and B-tree depth mildly; not a full table scan.
 depth=0.85+0.15*math.log10(max(scale*100,1))/2
 db=rng.lognormal(np.log(np.array(q['db_medians_ms'])[op]*depth),np.array(q['db_lognormal_sigma'])[op])/1000
 cold=rng.random(n)<np.array(q['cold_miss_probability'])[op]*cfg.get('cold_multiplier',1)*(0.6+0.4*math.sqrt(scale))
 db+=cold*rng.lognormal(np.log(q['cold_miss_median_ms']/1000),.65,n)
 retry=(op==2)&(rng.random(n)<cfg.get('retry_probability',q['serialization_retry_probability']))
 db+=retry*(rng.lognormal(np.log(14/1000),.65,n)+q['retry_backoff_ms']/1000)
 # Bounded resource-epoch write is default; compare inline scope updates under a high-degree workload.
 if cfg.get('inline_fanout'):
  iscontact=(op==2)&(rng.random(n)<.1);d=rng.choice(DEGREES,n,p=.8*PARTY_PROBS+.2*SIZE_PROBS);db+=iscontact*d*.0006
 db*=service_multiplier
 horizon=arr[-1];write_rps=rps*mix[2];bg_rate=write_rps*(.9*.8+.1*2);bn=max(1,int(bg_rate*horizon));ba=rng.uniform(0,horizon,bn);br=rng.choice(3,bn,p=[.25,.60,.15]);bs=rng.lognormal(np.log(.006),.6,bn)*service_multiplier
 all_t=np.concatenate([t,ba]);all_s=np.concatenate([db,bs]);all_r=np.concatenate([region,br]);dbslots=[max(1,int(x*slots_multiplier)) for x in q['db_slots']]
 key_ids=np.concatenate([np.where(hot,0,-1),np.full(bn,-1)]);key_demand=float(db[hot].sum()/horizon)
 finished,wd,ud=queue(all_t,all_s,all_r,dbslots,key_ids);net=rng.lognormal(np.log(q['local_network_median_ms']/1000),.4,n);lat=(finished[:n]+net-arr)*1000
 if cfg.get('wan_authority'):
  # One synchronous SG↔UK authority round-trip on every modeled read; not 3-region weighted WAN traffic.
  lat+=np.where(op!=2,rng.lognormal(np.log(.18),.2,n)*1000,0)
 rows=[]
 for region_idx in range(3):
  for op_idx in range(3):
   keep=(np.arange(n)>=warm)&(region==region_idx)&(op==op_idx);x=lat[keep]
   rows.append(dict(region=REGIONS[region_idx],operation=OPS[op_idx],samples=int(keep.sum()),**quant(x),over_1s_pct=float(np.mean(x>1000)*100),db_wait_p99_ms=float(np.percentile(wd[:n][keep]*1000,99))))
 demand_max=max(ud);return dict(seed=seed,global_rps=rps,simulated_seconds=float(horizon),foreground_events=n,background_events=bn,metrics=rows,db_demand_ratio=ud,gateway_demand_ratio=ug,opa_demand_ratio=uo,stable_under_assumed_capacity=demand_max<1 and key_demand<1,hot_key_demand_ratio=key_demand,ending_db_drain_seconds=max(0,float(finished.max()-horizon)),service_ms_mean=float(db.mean()*1000))
def recovery():
 f=fanout();rate=f['optimized_jobs_per_second'];data=[]
 for factor in [1.1,1.5,2.0]:
  # Exact discrete-time fluid backlog model: 30-minute outage of GB receiver, 60% of recipient traffic.
  incoming=rate*.6;capacity=incoming*factor;backlog=incoming*1800;initial=backlog;series=[]
  for sec in range(0,21601):
   if sec%60==0:series.append([sec,round(backlog)])
   if backlog<1e-5:backlog=0;break
   backlog=max(0,backlog+incoming-capacity)
  data.append(dict(service_factor=factor,incoming_jobs_s=incoming,initial_jobs=initial,drain_seconds=sec if backlog==0 else None,drain_minutes=sec/60 if backlog==0 else None,series=series))
 return data
def federation():
 rng=np.random.default_rng(A['seed']+42);n=500000
 # Healthy-path latency model, independent WAN lanes, with explicit 0.5% retry and 250ms debounce.
 lag=rng.uniform(0,250,n)+rng.lognormal(np.log(30),.55,n)+rng.lognormal(np.log(180),.2,n)+rng.lognormal(np.log(20),.6,n)+rng.lognormal(np.log(45),.65,n)
 retries=rng.random(n)<.005;lag+=retries*rng.lognormal(np.log(1000),.4,n)
 deny=rng.lognormal(np.log(180),.4,n)+rng.lognormal(np.log(70),.6,n);partitioned=rng.random(n)<.01;deny[partitioned]=rng.uniform(0,5000,partitioned.sum())
 purge=lag+rng.lognormal(np.log(600),.7,n)
 return dict(samples=n,visibility_ms=quant(lag),deny_ms=quant(deny),purge_ms=quant(purge),notes=['Assumed 180ms median WAN RTT and 250ms debounce, not measured transport','Visibility includes source planning, WAN, recipient commit and query refresh; excludes offline receivers','Deny distribution assumes 1% invalidation-path failure and a 5s residual authority lease; maximum is an engineered guarantee only with bounded clock skew and fail-closed expiry','Purge means live operational projection, not backup/audit deletion'])
def main():
 start=time.time();scenarios=[dict(id='1m_peak',name='1M relationships / peak',population_scale=.01),dict(id='10m_peak',name='10M relationships / peak',population_scale=.1),dict(id='50m_peak',name='50M relationships / peak',population_scale=.5),dict(id='100m_normal',name='100M / normal workload',normal=True),dict(id='100m_peak',name='100M / design peak'),dict(id='100m_125',name='100M / 1.25× peak',load=1.25),dict(id='100m_150',name='100M / 1.5× peak',load=1.5),dict(id='100m_200',name='100M / 2× peak',load=2),dict(id='100m_cold',name='100M / cold cache + slower DB',cold_multiplier=4,service_multiplier=1.5),dict(id='100m_skew',name='100M / 70% Singapore traffic',region_mix=[.7,.2,.1]),dict(id='100m_az_loss',name='100M / one AZ capacity lost',slots_multiplier=2/3),dict(id='100m_headroom',name='100M / 50% extra DB capacity',slots_multiplier=1.5),dict(id='100m_inline',name='100M / inline high-degree fanout',inline_fanout=True),dict(id='100m_hotkey',name='100M / 5% of writes hit one party',hot_key_share=.05),dict(id='100m_headroom_az',name='100M / extra capacity then AZ loss',slots_multiplier=1.5*2/3),dict(id='100m_wan',name='100M / synchronous remote authorisation',wan_authority=True)]
 allruns=[]
 for cfg in scenarios:
  runs=[run(cfg,A['seed']+i) for i in range(A['queue_model']['replicates'])];combined=[]
  for idx,metric in enumerate(runs[0]['metrics']):
   vals=[r['metrics'][idx] for r in runs];combined.append({k:metric[k] for k in ['region','operation']}|dict(samples=sum(x['samples'] for x in vals),p95_ms=float(np.median([x['p95'] for x in vals])),p99_ms=float(np.median([x['p99'] for x in vals])),p999_ms=float(np.median([x['p99.9'] for x in vals])),p99_min_ms=min(x['p99'] for x in vals),p99_max_ms=max(x['p99'] for x in vals),over_1s_pct=float(np.mean([x['over_1s_pct'] for x in vals])),db_wait_p99_ms=float(np.median([x['db_wait_p99_ms'] for x in vals]))))
  result=dict(**cfg,rps=runs[0]['global_rps'],duration_seconds=runs[0]['simulated_seconds'],max_db_demand_ratio=float(max(max(r['db_demand_ratio']) for r in runs)),hot_key_demand_ratio=max(r['hot_key_demand_ratio'] for r in runs),stable=all(r['stable_under_assumed_capacity'] for r in runs),max_ending_drain_seconds=max(r['ending_db_drain_seconds'] for r in runs),metrics=combined,runs=runs);allruns.append(result);print(cfg['id'],round(result['max_db_demand_ratio'],3),'SG graph p99',round(combined[1]['p99_ms'],1),flush=True)
 scenarios_storage=[storage(x) for x in [.01,.1,.5,1]];sens=[storage(1,h,c) for h in [30,90,365] for c in [.3,.8,1.5]]
 output=dict(kind='synthetic_scenario_model',assumption_sha256=hashlib.sha256((R/'scale/assumptions.json').read_bytes()).hexdigest(),assumptions=A,scenarios=allruns,storage=scenarios_storage,storage_sensitivity=sens,fanout=fanout(),recovery=recovery(),federation=federation(),method=dict(foreground_events=sum(r['foreground_events'] for s in allruns for r in s['runs']),background_events=sum(r['background_events'] for s in allruns for r in s['runs']),wall_seconds=time.time()-start,seeds=[A['seed']+i for i in range(3)],notes=['No 100M-row database was loaded. Populations are analytic cardinality/storage models; workload is sampled discrete-event arrivals.','Results assume indexed, bounded reads/writes, connection pools, resource epochs, local authorisation and deduplicated delta propagation. These are proposed improvements, not current PoC behavior.','Independent lognormal demands, Poisson arrivals; separate scenarios cover selected correlations but not a full disk/CPU/compaction model.','Percentiles are medians of three run-specific percentiles; min/max is seed variability, NOT a confidence interval or model uncertainty interval.','Timeout threshold is reported as over-1s share. Simulation keeps those requests in queues instead of censoring them; no retries/aborts are triggered by client deadline.','Unstable scenarios are finite-horizon overload illustrations, not steady-state latency forecasts.','Lower scales use the same full-scale synthetic capacity with proportionately lower traffic. This is not a pilot hardware sizing test.']))
 (OUT/'simulation.json').write_text(json.dumps(output,indent=2));(R/'dist/scale/simulation.json').write_text(json.dumps(output,separators=(',',':')))
 with (OUT/'latency.csv').open('w',newline='') as f:
  rows=[dict(scenario=s['id'],global_rps=s['rps'],stable=s['stable'],**m) for s in allruns for m in s['metrics']];w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
 print('Completed',output['method'],flush=True)
if __name__=='__main__':main()
