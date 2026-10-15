# Authority, delivery and recovery contract

This contract describes the executable synthetic pilot and the additional proof
needed before regional production use. Each region still runs a separate
single-node CockroachDB. The pilot has one authoritative coordinator. Neither
placement revision checks nor successful container tests establish distributed
consensus, regional availability or a legally approved revocation window.

## Current authority contract

The business service owns the business mutation. Its local CockroachDB transaction
contains business rows, relevant versions, outbox intent, mandatory business audit
and the idempotency receipt. Application logging and peer delivery cannot make a
failed business commit successful or undo a successful commit.

The source constructs an envelope from current scoped business and policy facts.
It applies exclusions before exporting any payload. The recipient authenticates
the workload, confirms its destination binding, asks the current source to verify
the exact envelope against a durable intent, and evaluates its own OPA policy.
An unavailable or incompatible authority fails closed. There is no offline read
lease, cached permission fallback or arbitrarily selected five-second tolerance.

An experience read requires current source approval, the recipient's committed
manifest, current placement and applicable recipient policy. The API's processing
route is an additional obligation: storage permission does not authorise every
gateway, operator or business service to process the payload.

| Boundary | Executable guarantee | Limit |
|---|---|---|
| Business commit | Business changes, versions, intent, audit and receipt commit locally together. | No cross-region atomic transaction is claimed. |
| Source admission | Exact envelope digest matches a current source plan and a destination-bound export intent. | A source change can commit after admission. |
| Recipient commit | Graph, exact field sets, manifest, source-placement ledger, inbox, envelope hash and audit commit in one local SQL transaction. | The source authority check and local SQL commit are separate events. |
| Duplicate delivery | The same event and exact envelope return the durable receipt without another graph/audit mutation. | An old inbox without a digest is not proof of the new envelope. |
| Recipient ordering | No accepted message decreases data, policy, decision, destination placement or source placement revisions. | Revisions must have meaningful monotonic writers; this does not elect one. |
| Projection read | Missing or different source-placement proof blocks the read until source-authorised reconciliation. | A response in flight can overlap a newer restriction; receipt and read checks are not instantaneous global revocation. |

Mandatory transactional audit remains in CockroachDB. Protocol diagnostics contain
fixed outcomes; envelope hashes, customer graphs, URLs and credentials are not
added to application logs. The durable SQL receipts may contain identifiers
because they are controlled business/sovereignty records, not telemetry exports.

## Protocol and transaction ordering

The HTTP envelope declares `protocol_version: 1`. It carries the event UUID,
owner, scope, destination, data/policy/decision revisions, destination placement
revision and source placement revision. Each revision must be a positive signed
64-bit integer; boolean and floating-point values are rejected. The bounded graph
must use registered fields, distinct resource keys, matching policy facts and
accurate row counts. Unknown protocol versions fail before SQL mutation.

The current recipient SQL transaction:

1. Verifies protocol shape and checks the inbox plus exact canonical-envelope
   digest. A changed or unproved consumed event receives the fixed
   `projection_receipt_conflict` response.
2. Locks the existing scoped manifest and checks each revision independently.
   Source placement uses the companion `sovereignty.manifest_authority` row.
3. Replaces the bounded graph in dependency order and updates the manifest,
   source placement, exact imported field names, inbox, import receipt and audit.
4. Acknowledges only after the transaction commits. A SQL error or serialization
   failure cannot produce a successful receipt; ordinary delivery remains retryable.

Two overlapping recipient transactions rely on CockroachDB serializable
isolation and the scoped manifest row, not a process-local mutex. A stale purge
cannot delete a later grant. A stale grant cannot resurrect a later purge.
These are current-state projection semantics: intermediate desired states may be
coalesced while mandatory audit persists. Payments, notifications and other
business workflows requiring every transition need a separate ordered, durable
event contract and must not use projection coalescing as their event delivery.

Placement is routing metadata. `source_placement_version` does **not** implement a
writer epoch for the normalized MDM tables, transfer source references/receipts
or fence a competing database writer. The original India demonstration migrates
its separate fixture. Migrating the new MDM model remains an explicit release gate.

## Upgrade and consumed-intent recovery

The additive receipt/authority tables preserve the original direct-SQL lab path.
Existing inbox rows and projections are not backfilled with guessed evidence.
Strict pilot reads of a projection without a source-placement ledger return a
conflict until a fresh source-authorised import supplies it.

Run `./lab pilot-reconcile` when upgrading existing volumes or after an operator
has established that a recipient can safely rejoin. The underlying command is:

```bash
PILOT_OWNER_DSN='<private owner connection string>' \
  python3 poc/pilot_reconcile.py --batch-size 10
```

Keep the connection string in the deployment's secret environment; the command
prints counts only. The lab wrapper runs it inside the owner container with its
existing synthetic private DSN, including after `./lab pilot-up`.
The reconciler reads owner scopes in primary-key pages of at most 50, bounds the
scan to its starting high-water key, and commits fresh intents with mandatory
audit per page. It retains pending work and all old receipts/audit. Each delivery
still traverses source policy, destination binding, current source admission and
recipient OPA. Queuing an intent is not a claim that replication has completed.

If a recipient committed an event but its acknowledgement was lost, a later
source plan can produce different bytes under that consumed event. The source
relay recognises only the fixed receipt-conflict code, conditionally retires the
old pending intent, inserts one fresh event and writes mandatory audit in one
local transaction. Repeating that transition cannot insert a second replacement
for the same old event. Generic policy, placement and dependency failures do not
manufacture an acknowledgement or rotate event IDs. The replacement is processed
by the ordinary bounded relay and undergoes fresh admission.

## Partition, restriction and recovery milestones

These milestones must remain separate in operator status and any future SLO:

| Milestone | What it establishes | What it does not establish |
|---|---|---|
| Source restriction committed | New source evaluations use the new restriction. | Simultaneous enforcement by an offline recipient. |
| Read restriction observed | A checked serving path refuses the affected view. | Absence of a response already in flight or every alternative reader. |
| Live purge committed | The scoped live projection rows have been removed with a durable receipt. | Removal from prior backups, SQL audit or other retained copies. |
| Recovery reconciliation complete | Enumerated current scopes have been re-authorised and reconciled. | Safe admission of an unknown/orphaned scope restored from an old backup. |
| Retained-copy disposition complete | An approved retention/erasure process has met its evidence requirements. | Something demonstrated by this single-host live-row cleanup test. |

During owner unavailability, pilot projection reads and imports fail closed.
Independent regional serving requires an explicit business-approved authority
contract: trusted identity, signed compatible policy/facts, monotonic epochs,
revocation watermarks, permitted evidence lifetime and clock-error bounds. The
production design must state whether source commit, receiver acknowledgement or
lease expiry is the enforcement deadline for each operation. This pilot does not
choose that policy on behalf of the business.

A database-local `quarantined` boolean would be restored alongside old data. It
cannot reliably prevent stale permissions or payloads reappearing after restore,
so this change deliberately does not label such a switch as recovery safety.
Before restoring a production recipient, an external control must fence its
serving/writer identities and network entry points, install a non-rollbackable
recovery epoch, and keep it out of service while current restrictions and placement
are acquired. Inventory must include restored scopes that no longer exist at the
source; these cannot be made safe merely by replaying current source scopes.
Promotion requires reconciliation evidence and a controlled release of that
external fence. Restore to an isolated environment, stale-message rejection,
orphan removal, RPO/RTO and retained-copy handling remain unexecuted production gates.

## Reproducible regression evidence

`poc/tests/pilot_protocol_acceptance.py` uses real CockroachDB transactions and
the running HTTP pilot. It is included in the pilot acceptance sequence. It tests:

- Unsupported/ambiguous protocol values before SQL mutation.
- Exact duplicate delivery, changed-envelope replay rejection and legacy inbox
  entries with no digest.
- Independent data/source-placement/destination-placement rollback fences.
- Delayed purge after regrant, delayed grant after purge and overlapping SQL
  transactions resolving to the newer version.
- An actual SQL transaction abort after projection work, with all graph, fence,
  inbox, hash and audit changes rolled back.
- Missing source-placement evidence failing closed.
- A real consumed source intent renewed exactly once, audited and delivered
  through current source and recipient admission after a legacy receipt conflict.

The direct SQL cases establish the local transaction invariants; their synthetic
test envelopes do not constitute OPA or cross-region admission evidence. The
final live recovery case and existing HTTP policy/outage suites cover those paths.
Execution results belong in the PR acceptance record, not in this contract as
assumed passes. Continue to require the preserved original lab, OPA/peer/Collector
outages, restart, browser, log privacy and normalized-model acceptance gates.

Before production, add crash tests around source fencing and ownership transfer,
concurrent restrictive policy changes at import/read boundaries, policy bundle
incompatibility, restored stale inbox/manifests, clock skew, competing coordinators,
credential expiry/rotation and audited external quarantine release. Measure
restriction visibility, live purge, backup disposition and recovery deadlines
separately; a successful eventual projection read is not evidence for all four.
