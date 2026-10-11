// Deterministic service-budget illustration, not a database or OPA benchmark.
export const DEFAULTS = Object.freeze({rate:500, burst:20000, duration:60, at:5, total:1000, guard:50, operational:700, reconcile:250, fixedMs:60});
const quantile=(xs,p)=>xs[Math.max(0,Math.ceil(xs.length*p)-1)]??0;
export function simulate(input={}) {
  const c={...DEFAULTS,...input};
  for(const [k,v] of Object.entries(c)) if(!Number.isFinite(v)||v<0) throw Error(`Invalid ${k}`);
  if(!c.rate||!c.operational||!c.reconcile||!c.guard||c.duration<=c.at||c.operational+c.reconcile+c.guard>c.total||c.rate*c.duration>200000) throw Error('Invalid capacity envelope');
  const sharedRate=c.total-c.guard, ops={shared:[],isolated:[]}, finish={shared:0,isolated:0};
  let burstInserted=false, sharedBulkStart=0,sharedBulkEnd=0;
  const incident={shared:[],isolated:[]};
  for(let i=0;i<Math.floor(c.rate*c.duration);i++) {
    const arrival=i/c.rate;
    if(!burstInserted&&arrival>=c.at) {
      sharedBulkStart=Math.max(c.at,finish.shared);
      sharedBulkEnd=sharedBulkStart+c.burst/sharedRate;
      finish.shared=sharedBulkEnd;burstInserted=true;
    }
    for(const mode of ['shared','isolated']) {
      const service=1/(mode==='shared'?sharedRate:c.operational);
      finish[mode]=Math.max(arrival,finish[mode])+service;
      const visible=finish[mode]+c.fixedMs/1000;
      ops[mode].push({arrival,visible});
      if(arrival>=c.at) incident[mode].push((visible-arrival)*1000);
    }
  }
  const summary={};
  for(const mode of ['shared','isolated']) {
    const values=incident[mode].sort((a,b)=>a-b);
    summary[mode]={p95:quantile(values,.95),p99:quantile(values,.99),max:values.at(-1)??0,completed:ops[mode].filter(o=>o.visible<=c.duration).length};
  }
  const counts={shared:0,isolated:0},series=[];
  for(let t=0;t<=c.duration;t++) {
    const s={t,arrivals:Math.min(Math.floor(c.rate*c.duration),Math.floor(t*c.rate)+1)};
    for(const mode of ['shared','isolated']) {
      while(counts[mode]<ops[mode].length&&ops[mode][counts[mode]].visible<=t) counts[mode]++;
      s[mode]=s.arrivals-counts[mode];s[mode+'Completed']=counts[mode];
    }
    s.sharedBulk=Math.max(0,c.burst-Math.floor(Math.max(0,t-sharedBulkStart)*sharedRate));
    s.isolatedBulk=Math.max(0,c.burst-Math.floor(Math.max(0,t-c.at)*c.reconcile));
    series.push(s);
  }
  return {config:c,summary,series,bulkEnd:{shared:sharedBulkEnd,isolated:c.at+c.burst/c.reconcile},guardAt:c.at+.18+1/c.guard,overloaded:c.rate>=c.operational};
}

// Small executable specification of admission checks. No cryptography or OPA.
// Adapters must establish trusted identity, facts, epochs and lease watermarks.
export function admission(event,state,now) {
  if(!state.verified||now>=state.validUntil||state.appliedWatermark<state.requiredWatermark) return {allow:false,reason:'AUTHORITY_NOT_CURRENT'};
  if(event.homeEpoch!==state.homeEpoch||event.placementVersion!==state.placementVersion) return {allow:false,reason:'WRONG_AUTHORITY_OR_STORE'};
  if(event.authorityRevision!==state.authorityRevision) return {allow:false,reason:'REAUTHORISE_CURRENT_STATE'};
  if(!state.allowed) return {allow:false,reason:'CURRENT_POLICY_DENIES'};
  if(event.dataVersion<state.dataVersion) return {allow:false,reason:'OLDER_DATA_VERSION'};
  if(event.fieldSet!==state.fieldSet) return {allow:false,reason:'CURRENT_FIELDS_MISMATCH'};
  return {allow:true,reason:'APPLY_OR_IDEMPOTENT_REPLAY'};
}
export function purgeAllowed(job,state,now) {
  return state.verified&&now<state.validUntil&&state.appliedWatermark>=state.requiredWatermark&&!state.allowed&&job.authorityRevision===state.authorityRevision&&job.homeEpoch===state.homeEpoch&&job.placementVersion===state.placementVersion&&job.manifestVersion===state.dataVersion;
}
