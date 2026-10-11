from pathlib import Path
import json,csv,shutil
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
R=Path(__file__).resolve().parents[1];d=json.loads((R/'scale/results/simulation.json').read_text());out=R/'dist/scale';out.mkdir(exist_ok=True)
plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10,'axes.spines.top':False,'axes.spines.right':False,'figure.facecolor':'#f6f7f1','axes.facecolor':'#f6f7f1','axes.labelcolor':'#294737','text.color':'#294737','xtick.color':'#506450','ytick.color':'#506450'})
fig,axs=plt.subplots(2,2,figsize=(13,8.5),layout='constrained');fig.suptitle('50 million parties · 100 million relationships\nSynthetic capacity model — not a CockroachDB benchmark',fontsize=17,fontweight='bold')
caseids=['100m_peak','100m_125','100m_150','100m_200'];cases=[next(x for x in d['scenarios'] if x['id']==i) for i in caseids];x=[1,1.25,1.5,2]
for op,label,c in [('party_read','Party lookup','#2f7150'),('relationship_read','Relationship view','#b78c3c'),('write','Local commit','#72608b')]:
 y=[next(m['p99_ms'] for m in s['metrics'] if m['region']=='SG' and m['operation']==op) for s in cases];axs[0,0].plot(x,y,'o-',label=label,color=c,lw=2)
axs[0,0].set(title='Queueing dominates beyond assumed capacity',xlabel='Multiple of 35,000 requests/s',ylabel='SG p99, milliseconds (log scale)',yscale='log');axs[0,0].legend(fontsize=8);axs[0,0].grid(alpha=.15)
cs=d['storage'][-1]['logical_components_bytes'];names=['Business rows','Hot audit (7 days)','Remote graphs','Controls / other'];vals=[cs['source_business'],cs['hot_audit'],cs['remote_relationship_graphs'],sum(v for k,v in cs.items() if k not in ['source_business','hot_audit','remote_relationship_graphs'])];axs[0,1].barh(names,[v/1e12 for v in vals],color=['#2f7150','#b78c3c','#72608b','#7f9e8a']);axs[0,1].invert_yaxis();axs[0,1].set(title='Logical data before indexes and replicas',xlabel='Decimal TB');axs[0,1].grid(axis='x',alpha=.15)
for case in d['recovery']:
 xs,ys=zip(*case['series']);axs[1,0].plot([x/60 for x in xs],[y/1e6 for y in ys],label=str(case['service_factor'])+'× normal service',lw=2)
axs[1,0].set(title='Recovery after a 30-minute UK receiver outage',xlabel='Minutes after service returns',ylabel='Outstanding jobs, millions');axs[1,0].legend(fontsize=8);axs[1,0].grid(alpha=.15)
f=d['fanout'];axs[1,1].bar(['Whole graphs +\nrepeated shared rows','Deduplicated\nresource deltas'],[f['full_snapshot_mb_s'],f['optimized_delta_mb_s']],color=['#b78c3c','#2f7150']);axs[1,1].set(title='Modeled egress at 5,000 business writes/s',ylabel='Payload MB/s, before protocol overhead');axs[1,1].set_ylim(0,f['full_snapshot_mb_s']*1.35);axs[1,1].text(.5,.94,'Requires a new resource-delta importer;\nnot implemented in the current PoC',transform=axs[1,1].transAxes,ha='center',fontsize=8)
fig.savefig(out/'capacity-results.png',dpi=160);fig.savefig(out/'capacity-results.svg');plt.close(fig)
for name in ['opa_microbench.json','latency.csv']:shutil.copy2(R/'scale/results'/name,out/name)
shutil.copy2(R/'scale/assumptions.json',out/'assumptions.json');shutil.copy2(R/'scale/pilot_actions.json',out/'pilot_actions.json')
with (out/'pilot-actions.csv').open('w',newline='') as file:
 rows=json.loads((R/'scale/pilot_actions.json').read_text());w=csv.DictWriter(file,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
peak=next(s for s in d['scenarios'] if s['id']=='100m_peak');storage=d['storage'][-1];tail=lambda id,op='relationship_read':next(m['p99_ms'] for s in d['scenarios'] if s['id']==id for m in s['metrics'] if m['region']=='SG' and m['operation']==op)
text=f'''# Scale assessment and PoC-to-pilot plan

11 October 2026. Model version 1, seed family 20261011–20261013.

## Recommendation

The architecture can be engineered for 50M parties / 100M relationships, but the current PoC cannot be extrapolated to that scale. First remove full-owner scans, the global process lock, unbounded snapshots and per-recipient full-graph replacement. Keep the regional ACID boundary, explicit sovereignty rules and transactional outbox. The dominant risks are hot keys, fanout, insufficient recovery capacity, synchronous WAN authorisation and unbounded retention.

The proposed service targets are engineering acceptance goals under the workload envelope below, not measured database guarantees. There is no CockroachDB benchmark or loaded 100M-row database in this assessment.

## Proposed latency targets

| Operation | p95 | p99 | Boundary |
|---|---:|---:|---|
'''
for t in d['assumptions']['targets']:text+=f"| {t['name']} | {t['p95_ms']} ms | {t['p99_ms']} ms | {t['boundary']} |\n"
text+='''
Measure each operation separately per region and legal entity at gateway ingress to completion. Do not blend reads and writes or hide slow operations in a global aggregate. Search, exports, full party portfolios, history scans and cross-home writes need separate budgets. Responses larger than 50 rows/32 KiB must be paged. Report error/timeouts alongside percentiles, using attempted requests as the denominator; the target success error rate is <0.1% excluding expected policy denials. Instrument revocation and purge with source commit and recipient receipt timestamps, with a measured clock-error bound.

A strict remote read which consults an overseas authority cannot meet the same local-read target. In the illustrative 180 ms WAN RTT case, relationship-read p99 rises to '''+f"{tail('100m_wan'):.0f} ms"+'''. Choose either strict source-authorised reads with a WAN budget or locally enforced, versioned facts with a bank-approved bounded revocation window. This assessment proposes a maximum 5 seconds including clock tolerance; it does not implement or approve that trade-off.

## Workload and method

- Population: 50M parties, 100M relationships and 125M party participation edges. Average two primary relationships per party, with secondary signatory/owner roles bringing participation to 2.5 links per party.
- Normal traffic: 10,000 reads/s and 1,000 business writes/s globally. Design peak: 30,000 reads/s and 5,000 writes/s. These are planning assumptions, not inferred from population size. Regions receive 45% SG / 40% UK / 15% US traffic; the skew scenario changes this to 70% / 20% / 10%.
- Relationship sharing averages 0.8 remote recipient copies. Global party minimums add two remote physical copies, only where policy permits. No automatic grant to all 30 legal entities is assumed.
- 16 scenarios, three deterministic seeds each. Open Poisson arrivals pass through gateway, OPA and shared database service queues; independent lognormal service demands, cache misses and retries create tails. Background delta imports share DB capacity. A hot-key case adds a single serialized resource.
- '''+f"{d['method']['foreground_events']:,} foreground events and {d['method']['background_events']:,} background events were simulated."+''' Every run has 360,000 foreground events; its duration therefore depends on rate. At the full design peak this is roughly ten seconds, including 20,000 warm-up arrivals. Stable-case quantiles have substantial samples; overload results describe a finite growing backlog, not a long-run steady state. A 60-minute/24-hour physical load test remains necessary.
- Four cardinalities (1M/10M/50M/100M relationships) change row counts, assumed cache/depth cost and proportionately scaled traffic. They reuse the same full-scale synthetic capacity; they do not benchmark four differently sized clusters.
- The reported p95/p99 are medians of three run-specific percentiles; minimum/maximum p99 across seeds shows random variation, not a statistical confidence interval or calibration uncertainty.
- No measured DB, storage, TLS, compaction or cross-region network times calibrate this model. Database service medians are 3/10/14 ms for party/relationship/write, with explicit cold/retry terms in assumptions.json. Effective DB admission slots are 192/192/96; these are queue-model parameters, not CPU counts or a claim about specific hardware.
- Assumed local OPA request median 1.1 ms uses a small fact-based read decision; full resource-batch policy evaluation is asynchronous. The observed microbenchmark below gives context but is not a throughput calibration.

## Results

| Scenario | SG relationship p99 | Maximum DB demand / capacity | Interpretation |
|---|---:|---:|---|
'''
for s in d['scenarios']:
 if s['id'].startswith('100m'):
  text+=f"| {s['name']} | {tail(s['id']):.0f} ms | {s['max_db_demand_ratio']:.2f}× | {'Finite overloaded queue; not a sustainable p99' if not s['stable'] else 'Stable under stated assumptions'} |\n"
text+=f'''
At normal peak the busiest DB pool reaches {peak['max_db_demand_ratio']*100:.0f}% modeled demand. That is too close to saturation for a bank pilot exit. A 25% traffic increase pushes the same capacity above 100%. Adding 50% effective capacity reduces modeled peak demand to about 59%; losing one-third of that enlarged capacity returns it to roughly 88%. Plan to run at **≤60% of measured limiting capacity** during design peak if the same peak must survive an AZ loss. CPU, disk, network, locks and policy workers each need their own headroom measurement. This is a capacity reserve requirement, not proof that 50% more nodes produces 50% more throughput.

The hot-key scenario can be unstable even if aggregate DB demand is below one. A repeatedly updated party/resource epoch is still a serial resource: coalesce allowed updates, bound concurrency, isolate the hot key, and reject or queue excess work without blocking unrelated customers. Inspect p99.9 and per-key rates, not only fleet p99.

## Storage and bandwidth

The central model has **{storage['source_rows']/1e9:.2f} billion source business rows**, **{storage['logical_tb']:.2f} TB logical data** including projections, controls and seven days of audit, **{storage['replicated_used_tb']:.1f} TB used after overhead and replication**, and **{storage['provisioned_tb']:.1f} TB provisioned at 60% fill** across the three regions. Decimal TB is used throughout. This includes 90 days of contact history, assuming 10% of normal writes create history rows.

Overhead assumptions are explicit multipliers: secondary indexes 1.7×, key/encoding/storage overhead 1.35×, MVCC allowance 1.25×, RF=3 within each regional cluster; provisioned = used / 0.60. They need calibration from real schemas and update churn. No compression saving is assumed. The nine storage sensitivity cases vary history retention (30/90/365 days) and remote copies (0.3/0.8/1.5). Backup retention, audit archive, bus disks, replicas outside this three-region design, disaster recovery and future growth are additional.

At 1,000 normal business writes/s, two 512-byte audit events per write generate **{storage['audit_daily_gb']:.1f} GB/day** and **{storage['audit_annual_archive_tb']:.1f} TB/year** before archive compression/redundancy. If 5,000 writes/s becomes the sustained rate, audit/history growth is five times larger. Do not treat peak as the daily average or retain the full audit stream in the hot OLTP cluster indefinitely.

The synthetic degree distribution puts 24.4% of participation edges on 0.1% of parties. With 20% of change events sampled in proportion to degree, the average changed party touches {d['fanout']['mean_event_degree']:.1f} relationships and p99 touches 610. A serial hook costing an assumed 0.6 ms per scope adds 366 ms at p99 of **party changes**, even though all-write p99 can conceal that low-frequency path.

Whole-graph, repeated-recipient propagation produces about **{d['fanout']['baseline_jobs_per_second']:,.0f} jobs/s** and **{d['fanout']['full_snapshot_mb_s']:.1f} MB/s** at design peak. A proposed canonical resource-delta model reduces this to **{d['fanout']['optimized_jobs_per_second']:,.0f} jobs/s / {d['fanout']['optimized_delta_mb_s']:.1f} MB/s**. This approximately 25× payload reduction combines assumed payload sizes (6,000 → 900 bytes) and fanout deduplication. It is not a measured network saving. Delta messages alone do not remove per-relationship fanout; the physical shared-resource and recipient-authorisation design must change too.

A 24-hour outage retaining the optimized 4,600 events/s at 900 bytes needs about 358 GB of payload before bus indexes, broker replication, protocol overhead or safety margin. Regional retention must remain policy-compliant. Throughput also needs source/recipient OPA and DB capacity, not just WAN bandwidth.

## Recovery

A 30-minute UK receiver outage accumulates about 4.97 million jobs at the modeled peak route rate. Recovery while continuing new work takes:

| Available service after return | Drain time |
|---|---:|
| 1.1× incoming rate | 300 minutes |
| 1.5× incoming rate | 60 minutes |
| 2.0× incoming rate | 30 minutes |

These are fluid queue calculations with constant arrivals/capacity and no coalescing. Keep priority revocation/epoch traffic separate from data backfill so revocation does not sit behind millions of history updates. When a recipient is unavailable, live purge has no finite completion guarantee; reads must fail closed according to the approved authority contract and the UI must show purge pending.

## Observed OPA microbenchmark

OPA 1.9.0 ran locally, warmed with 100 requests and then measured for 1,200 sequential HTTP calls per batch size, with built-in telemetry disabled. The shared environment has an 8-vCPU quota / 8 GiB RAM, not dedicated benchmark hosts. HTTP timing includes JSON encode/decode and loopback response reading. No bank data was used.

| Resource rows | HTTP p95 | HTTP p99 | Evaluation p99 |
|---|---:|---:|---:|
'''
bench=json.loads((R/'scale/results/opa_microbench.json').read_text())
for b in bench['results']:text+=f"| {b['rows']} | {b['p95_ms']:.2f} ms | {b['p99_ms']:.2f} ms | {b['eval_p99_ms']:.2f} ms |\n"
text+='''
These are actual local component observations, unlike the simulated end-to-end numbers. They do not establish concurrent throughput, production tail latency or the p99 of a sum of stages. Batch and index OPA inputs; do not pass every policy or every relationship to every decision.

## Improvements, in priority order

1. **Bound the database work.** Remove load-all/snapshot-all from request paths. Index owner/root/resource bindings, use selective joins and capped keyset pages, pool connections and keep SQL plans stable. Replace the UI's raw global snapshot with regional materialized summaries and drill-down queries.
2. **Keep local ACID, remove process serialization.** Modular services share a local UoW; use per-resource versions, idempotency and bounded serialization retry. Every writer must call the sovereignty hook or be denied direct database access.
3. **Separate authority from materialization.** Use resource/scope/table epochs so one restriction becomes authoritative without rewriting hundreds of scope rows in the caller transaction. Dirty-scope work is asynchronous. For a table policy, advance the table epoch rather than rewriting 100M records.
4. **Replace full-graph delivery with versioned deltas.** Include parent requirements and content version, permit only legal recipient views, atomically apply changes and update inbox/manifest. Deduplicate party/contact payload physically only when all applicable recipient and purpose checks remain enforced; never share rights because two recipients share a store.
5. **Use regional queues and partitioned workers.** Retain the transactional outbox; move to local CDC/polling relay into regional Kafka or an equivalent durable bus. Partition by owner + resource/scope + recipient, quarantine bad events and implement jittered retry, backpressure, compaction/coalescing and priority revocation.
6. **Resolve remote-read semantics explicitly.** Local cached facts require bounded leases, epochs and freshness. A partition-level authority lease must be tied to a contiguous applied revocation watermark; a keepalive alone cannot certify no missing revocations. Batch lease refresh by authorized partition, not a 5-second refresh for every one of 100M scopes. Strict source reauthorisation remains available with a separate WAN latency target.
7. **Build real regional HA and operations.** Use 3 AZs per region, local RF=3, TLS, least-privilege credentials, regional keys and restore drills. Start the limited pilot with 3 nodes/region. A full-scale load-test candidate is SG 9 / UK 9 / US 6 nodes with 16 vCPU, 64 GiB RAM and 2 TB block storage each. This is a benchmark starting envelope, not a purchase recommendation or a mapping from the synthetic slots; measure and tune or scale it to satisfy capacity and failure headroom. Additional country-local stores may be required by actual entity policies.
8. **Make tails and custody visible.** OTel traces/metrics for queue wait, DB transaction, policy gate, retries and end-to-end projection freshness; govern audit separately. Avoid party IDs and payloads in general telemetry. Track oldest revocation and purge age alongside p95/p99; sample traces but keep required audit events complete.

## PoC to pilot

The backlog below is a gated plan, not work already implemented. An indicative 12–14 week path assumes an experienced team (backend/federation engineers, platform/DB, QA/performance, and dedicated business/security owners) plus timely infrastructure and data approvals. Legal review, procurement and unavailable environments can extend it. Start with approved 100k parties / 200k relationships in a limited pilot; run the 50M/100M scale rehearsal separately with synthetic data.

| ID | Priority / phase | Owner | Action | Exit evidence | Depends on |
|---|---|---|---|---|---|
'''
for a in json.loads((R/'scale/pilot_actions.json').read_text()):text+=f"| {a['id']} | {a['priority']} / {a['phase']} | {a['owner']} | {a['action']} | {a['exit']} | {a['dependency']} |\n"
text+='''
## Reproduce and replace assumptions

```bash
python3 -m pip install -r scale/requirements.txt
python3 scale/simulate.py
# Optional actual local component benchmark, with telemetry disabled:
python3 scale/opa_microbench.py --opa /path/to/opa --samples 1200
python3 scale/render_results.py
python3 scale/validate.py
```

The local runtime remains the v3 PoC; this delivery adds modeling and a pilot plan, not the optimized production data path. Raw scenarios, per-seed summaries, latency CSV, assumptions, benchmark script and action CSV are packaged. No external load test or infrastructure deployment was performed. Full CockroachDB integration, 100M-row data loading, multi-AZ fault tests, OTLP end-to-end collection and browser visual QA remain unverified.

Primary references used for the engineering guidance (none supplies the modeled latency numbers):

- CockroachDB production checklist: https://docs.cockroachlabs.com/docs/stable/recommended-production-settings
- CockroachDB SQL performance: https://docs.cockroachlabs.com/docs/stable/performance-best-practices-overview
- Connection pooling: https://docs.cockroachlabs.com/docs/stable/connection-pooling
- Changefeed ordering and at-least-once delivery: https://docs.cockroachlabs.com/docs/stable/changefeed-messages
- OPA performance: https://www.openpolicyagent.org/docs/policy-performance
- k6 open workload model: https://grafana.com/docs/k6/latest/using-k6/scenarios/concepts/open-vs-closed/
- k6 dropped iterations: https://grafana.com/docs/k6/latest/using-k6/scenarios/concepts/dropped-iterations/
'''
(R/'scale/SCALE_AND_PILOT.md').write_text(text);(out/'scale-and-pilot.md').write_text(text)
print('Rendered plots, report, downloadable assumptions/results/action files')
