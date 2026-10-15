# Production readiness: evidence, decisions and release gates

The lab is a synthetic integration pilot. It demonstrates useful controls against
real CockroachDB and OPA, but its successful container suite is not permission to
process bank data. The next release objective is a repeatable integration contract
for existing services, bounded failure impact, and an explicit authority contract.

Use [pilot setup](PILOT.md), [pilot acceptance](PILOT_ACCEPTANCE.md),
[foundation acceptance](FOUNDATIONS_ACCEPTANCE.md), the exact
commit's `lab-evidence` workflow artifact, and [ADR-0019](adr/ADR-0019.md) together.
An implemented check below identifies a testable control, not a result for an
unexecuted revision. Do not transfer evidence from a previous commit to a changed
deployment, identity configuration or policy bundle.

The [dependency security audit](DEPENDENCY_SECURITY.md) records current patch
updates and unresolved vendor CVEs. Its strict image gate remains failed; a
successful functional container suite does not clear those findings or supply a
vulnerability risk acceptance.

## What the concept must protect

A relationship identifies the relevant legal entity, purpose and servicing
context. It does not own every fact about a customer or supply a universal legal
basis. Apply the intersection of the relationship's rules and each party,
attribute, holding, consent and classification rule. For example, a relationship
may permit UK servicing while a shared contact attribute remains restricted to
SG; another relationship's permission cannot broaden that contact's rules.

The party minimum contains a stable global identifier. That identifier permits
correlation even when names, contacts and relationship links are absent. A bank
must decide whether its approved footprint permits a common identifier or
requires regional identifiers plus a separately controlled linkage service.
The latter needs its own access, matching, retention and recovery contract; the
current global UUID is not evidence that correlation is harmless.

The base MDM implements exact source-reference identity. Enterprise MDM must also
assign attribute ownership and provenance, steward uncertain matches, define
survivorship, and audit merge/split. A merge changes identity interpretation; it
must not union grants or erase independent relationship restrictions. Require
explicit review of the resulting bindings and preserve historical identifiers
and receipts. These stewardship workflows are not implemented by the pilot.

## Integration and routing responsibilities

| Component | Responsibility | Prohibited shortcut |
|---|---|---|
| Existing business service | Interactions, domain validation, authoritative records and action permissions | Treat read/sharing rights as permission to execute a business command |
| Local transaction adapter | Business change, relevant versions, outbox intent, mandatory audit and replay receipt in one local SQL transaction | Call a remote peer inside the retrying business transaction |
| Sovereignty peer | Source filtering, admitted import, scoped projection, guarded read and reconciliation | Copy raw tables because a recipient has a customer identifier |
| Authority/placement service | Current trusted ownership, policy revisions, processing paths and writer fences | Promote a nearby replica or trust a stale client-supplied route |
| Experience API | Caller-specific view and explicit freshness contract along permitted processing paths | Terminate a sensitive body in an unapproved gateway region |

Integrate services that read or write governed data. Every writer of that data,
including batch loaders, support scripts, migrations and direct SQL, must use the
transaction contract or be prevented from bypassing it. A sidecar cannot infer
business purpose, consent context or atomic multi-table intent from arbitrary
CDC. Database privileges and an inventory of writers are part of adoption.

Deploy peers according to jurisdiction and trust boundaries. One peer may support
several services when permissions and resource budgets remain isolated. Services
do not have to merge their databases or transactions. Cross-service business
workflows require an explicit saga/reconciliation contract, not a claimed remote
ACID transaction.

## Release matrix

The responsible disciplines below describe who must supply or accept evidence;
they do not assign an individual or imply that approval has occurred.

| Requirement | Implemented evidence or executable gate | Unproven gap / required input | Responsible discipline | Measurable release acceptance |
|---|---|---|---|---|
| Relationship-scoped placement | `./lab test` and `./lab pilot-test`: exact eligible US party minimum, UK relationship graph, source-side exclusions and recipient field checks | Bank-approved ownership, purpose, attribute and legal-entity matrix; policy for global-ID correlation | Data owners, privacy/legal, domain architecture | Every approved and denied cell in the signed matrix has a fixture; forbidden payload and customer-linked metadata are absent from never-authorised destinations |
| Reusable business integration | Independent servicing-case process/schema, generic transaction adapter and guarded UK projection; [service contract](SERVICE_INTEGRATION.md) and expanded `pilot-test` | Full inventory and enforcement of each adopting service's writers; domain event semantics; schema ownership; insecure SQL still allows identity impersonation | Service owners, database engineering | A second independently implemented service passes the adapter contract on real SQL; injected failures leave either all business/evidence records committed or none; direct ungoverned writers are denied with authenticated SQL principals |
| Isolated request path | `./lab pilot-faults` verifies failed-peer delivery fairness; `pilot_read_isolation.py` requires an SG owner read below two seconds and before a paused UK peer's timeout | Regional dependency budgets, many concurrent slow calls, hot aggregates and CPU/disk contention; the two-second gate is a lab regression threshold | Backend performance, SRE | A paused peer cannot hold the owner coordination lock; unrelated reads/writes satisfy an agreed p99/error budget while the peer is unavailable; report all attempted requests |
| Bounded data access | `pilot_scope_query_acceptance.py`: real SQL/OPA scope parity, limits and EXPLAIN; point reads/admission/relay use indexed bindings, at most 512 bound resources and 50 customer scopes | Broad base commands/full monitor, source-wide outbox/expiry work, largest customer graph, shared-attribute fanout, pagination and realistic cardinality | Database engineering, service owners | EXPLAIN/statement evidence and increasing unrelated data show scope work does not grow with the entire owner dataset; oversized aggregates reject before an unbounded scan or response |
| Strict authority and revocation | Pilot reads consult source authority; source/recipient OPA loss fails closed in `./lab pilot-faults` | Regional authority availability, restriction effectiveness contract, distributed fencing | Distributed systems, risk owners | Partition each authority dependency; only affected operations close, no fallback broadens rights, and every acknowledged restriction meets its explicitly agreed visibility deadline |
| Import, read and replay races | Protocol v1 bounds/type checks, exact-envelope digest/inbox transaction, source and destination placement fences; `pilot_review_acceptance.py` exercises catalog skew and protocol tests cover delayed purge/replay races | Independent coordinators, source restriction versus recipient commit, crash windows across regional transport, restore of old fence state | Distributed systems, database engineering | Reordered/duplicate messages cannot resurrect a revoked view, overwrite newer data or remove a newly regranted view; stale routes and receipts fail with no mutation |
| Identity and delegation | Per-role local credentials, mTLS, expiry/revocation/token rotation, explicit contact versus consent command grants and refusal of a non-synthetic runtime profile | Bank IdP/workload issuer, audience/subject validation, key custody, administrator separation and deployment attestation | IAM, platform security, service owners | Expired/revoked/wrong-audience credentials and undelegated commands are denied at each boundary; rotation works without an unrestricted overlap; actor delegation is durably audited |
| Processing and metadata location | Policy checks storage, principal location and operator-registered processing-hop countries; payload minimisation is tested before export | Attestation of actual gateway/API/peer locations, support paths, identifiers in receipts, backups and telemetry | Privacy architecture, infrastructure | Trace every hop using synthetic canaries and deployment inventory; every payload and metadata class has an approved route, store, retention and operator-access path |
| Regional infrastructure | Separate real single-node CockroachDB stores and OPA processes; loopback-only gateways | Regional HA, SQL TLS and scoped principals, private OPA, segmented networks, patch/license approval | Platform/database engineering, security | Independent node/zone failure and certificate rotation meet agreed RPO/RTO; unauthorized services cannot reach or mutate SQL/policy/admin surfaces |
| Migration and recovery | `./lab test` and the browser gate cover the isolated India snapshot/catch-up/fence/cutover/live cleanup fixture | Normalized MDM/second-service table migration, distributed writer activation, source decommission, backup restoration | Database engineering, service owners, SRE | Crash before/after fence and activation; exactly one writer survives, request IDs retain meaning, pending outbox/inbox handoff completes, and restored systems remain quarantined until current authority is installed |
| Audit and disposal | Mandatory SQL audit shares business/import transactions; Collector outage preserves commits and receipts | Protected retention, independent completeness reconciliation, evidence custody, backup expiry and legal hold | Audit/compliance, storage engineering | Reconcile every accepted business request to its SQL commit/evidence; unauthorized audit alteration is denied or detected; disposal reports separate read denial, live purge and retained-storage expiry |
| Capacity and recovery headroom | Real small-fixture acceptance and failure recovery; no published capacity claim | Workload distribution, peak/burst target, p95/p99, backlog/delete deadlines, RPO/RTO and cost limits | Product/service owners, performance engineering, SRE | Sustain agreed peak plus burst, bulk reconciliation and one failed dependency; meet all request/error budgets and recover backlog before its deadline without starving restrictions or audit |
| Alerting and operations | API → Collector → Loki → Grafana, trace/log correlation and diagnostic outage isolation | Regional metrics/alerts, on-call ownership, tested runbooks and capacity reservations | SRE, service owners | Inject each alert condition, verify routing and recovery runbook; distinguish liveness, usable authority, projection freshness, physical purge and audit health |
| Upgrade compatibility | Explicit interface/schema and policy contracts; CI runs full real-container acceptance | Supported adjacent versions, policy activation readiness, expand/contract migrations and signed artifact provenance | Release engineering, database/policy owners | Run old/new peers and API versions together; incompatible messages fail closed, migrations preserve receipts/fences, and rollback cannot reduce an authority revision |

## Authority is a contract, not a timeout constant

The implemented pilot uses synchronous source authority. An unavailable owner can
make a still-stored regional projection unreadable. That is the current contract;
its availability cost must be accepted or changed explicitly before regional use.

A future bounded authority lease requires a decision for each operation: maximum
business-data age, maximum permission age, effective restriction time, clock
assumptions, and failure outcome. No five-second window is approved merely because
a model uses it. Signing a bundle proves its origin and integrity; it does not
prove that the recipient has the latest restriction.

Record four separate milestones: source restriction committed; new export denied;
recipient read/import authority fenced or expired; physical live copy purged.
In-flight bytes cannot be recalled. Source admission before a recipient commit
does not make those two commits atomic. A stricter guarantee needs a proven
recipient fence/activation protocol and corresponding acknowledgements. Retained
audit, inbox receipts and backups have their own governed lifecycle.

The authority path should operate on bounded metadata with reserved capacity.
Payload materialisation and large reconciliation scans must not run on its
critical path. [Work isolation](../WORK_ISOLATION.md) specifies that target; its
browser capacity model is not evidence of reserved database or network capacity.
The [implemented authority and recovery contract](AUTHORITY_RECOVERY.md) records
the current import fences, protocol upgrade path and remaining admission/commit
and restore limitations in detail.

## Verification sequence

Run on a dedicated synthetic Compose project with no concurrent fixture edits:

```bash
./lab doctor
./lab pilot-up
LAB_PILOT=1 ./lab test
./lab pilot-test
./lab pilot-faults
python3 poc/tests/pilot_browser.py
python3 design/tests/reader_browser.py
```

The browser commands require Playwright/Chromium. The fault suite stops real
containers and restores them; it is not safe to run concurrently with ordinary
acceptance or demonstrations. Keep the original migration, browser, telemetry
and persistence gates. Read the exit status of every pipeline; the workflow uses
explicit Bash with `pipefail` so `tee` cannot turn a failed gate into a pass.

`./lab pilot-test` includes the scoped-query, security, protocol and independent
servicing checks. `./lab pilot-isolation` repeats the slow-peer regression without
running the remaining outage suite. `./lab pilot-reconcile --batch-size 10`
requeues bounded current-state intents for persisted legacy protocol evidence;
delivery must still pass normal source and recipient admission. Its completion
means queueing completed, not that every recipient has caught up.

Capture commit and image digests, configuration/policy revisions without secrets,
host resources, attempted request counts, error counts, latency distributions,
queue ages and recovery times. Report interrupted, skipped and blocked gates
explicitly. Never export credentials, customer payloads, raw request URLs or
sensitive identifiers into application logs or public artifacts.

## What remains a bank decision

The repository can supply executable contracts and synthetic evidence. It cannot
invent approved regional hosting, a lawful data/processing matrix, the bank's
identity issuer, service permission owners, acceptable revocation exposure,
retention/legal-hold periods or business recovery objectives. Those inputs must
be recorded before the corresponding release gates can close.

A production release also needs enterprise MDM stewardship and support processes
where the bank intends this base MDM to become a master. If it remains only a test
source for sovereignty integration, keep that narrower role explicit. No result
from this single-host lab establishes physical residency compliance, production
HA, 100M-record throughput or erasure from backups.

## Upgrade and restore acceptance procedure

Before changing a deployed contract, inventory the API, import protocol, SQL
schema, policy/field catalog and credential formats on every participating
process. Require an explicit supported-version matrix. Apply additive SQL
changes first, verify old and new readers against them, then introduce new
writers. Incompatible imports must fail before any projection/inbox mutation.
Remove old fields only after all producers, consumers and retained replay inputs
have a documented migration path. A database migration completing is not proof
that every peer is ready for new policy semantics.

For a policy grant, prepare compatible policy and facts before activation. For a
restriction, preserve the monotonic authority/fence through a code rollback. Test
both mixed-version directions, dropped acknowledgements and an old queued payload
arriving after a new restriction. An application rollback must not restore an old
authority revision or silently reopen a projection.

For restore, rebuild into an externally quarantined environment with no serving,
export or import route. Verify backup integrity and keys, apply current policy,
ownership and placement fences from an authority that did not roll back, and
reconcile receipts/outbox/inbox before enabling traffic. Restore the source and
a recipient separately in the test: a current source does not make an old
recipient manifest safe. Record which live/retained surfaces still contain data,
their approved expiry and any legal hold. The current restart tests preserve live
volumes and do not execute this restore procedure.
