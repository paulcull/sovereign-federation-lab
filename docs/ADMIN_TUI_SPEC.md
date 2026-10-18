# Logical lab administration: specification, UX and acceptance

Status: implemented for single-host logical administration; see
[executed acceptance and limits](ADMIN_TUI_ACCEPTANCE.md). Physical VM/container/cluster
bindings, provisioning and data-placement activation are deferred by design.

## Outcomes and boundaries

An operator can register Germany, assign stable logical node identities, increase
or decrease desired node count, request store suspension/activation and request
observability on/off. Every change has a review screen, revision check, durable
management receipt and idempotent request UUID. The configuration survives TUI,
API and database restarts. It is not the business database or business audit.

These are real persisted configuration operations. They do not start/stop Docker,
provision VMs, join CockroachDB nodes, migrate data, alter legal-entity bindings,
grant policy rights or change running telemetry. Those effects require the later
deployment adapter. Saved requests remain explicitly pending that adapter.

Existing Singapore/UK/US/India health can be observed read-only through the
loopback lab gateway. The two-store footprint remains running. A new logical
store has no observation binding and must always say **Backend unassigned**;
declaring DE never proves German infrastructure or hosting readiness. No control
in this increment can mark a new store ready for placement.

## Data and persistence contract

- Store: stable ID, display name, intended ISO country, desired state and desired
  logical node count. Initial lab entries are externally managed until edited.
- Node: stable ID and desired state. Reducing count suspends excess logical nodes
  while retaining identities. This is not native decommissioning or data erasure.
- Observability: desired enabled/suspended/unmanaged. Business audit is always
  required and has no toggle. Health polling is independent of observability.
- Revision: monotonically increasing integer. Review against revision N; reject
  applying against another revision. Reusing a UUID with different input fails;
  replaying identical input returns its original receipt.
- State and management receipts commit in one atomically replaced, fsynced JSON
  file in `.lab-admin/`, protected by a stable advisory lock and private modes.
  It contains no credentials, connection URLs or customer data. An explicit
  state directory supports independent environments. Corruption fails visibly;
  it never silently resets the registry. This single-host operator file is not
  tamper-proof evidence or a production management database.

## Terminal UX

Textual supplies a keyboard-first, resizable interface with high-contrast dark
panels. Minimum supported terminal size is 80 columns by 24 rows; a smaller
terminal requests resizing while preserving configuration. Screens:

1. **Stores**: searchable store table, desired/observed states, selected-store
   detail and stable node rows. Add store opens a form; configure selected store
   changes desired state/count. Country is immutable after registration.
2. **Environment**: independent observability intent, actual gateway footprint,
   last successful health time and bounded local disk/memory observations where
   available. Shared host resources are labelled as shared.
3. **Health**: actual SQL/OPA checks by known store, unavailable/suspended/unknown
   states and source age. Failed refresh invalidates current healthy claims;
   retained observations are explicitly stale. No fixtures or browser fallback.
4. **Activity**: management receipts, revision, request UUID and fixed summary.
   These are configuration changes, not infrastructure execution or SQL audit.

Global keys: `a` register, `e` configure, `o` observability, `r` refresh health,
`/` search, `?` help, `q` quit. Forms have labelled fields and inline errors.
Escape cancels. Review shows intended changes and the pending-adapter boundary;
**Save configuration** is the only mutation action. No button says deploy/apply
infrastructure. A stale review asks the operator to refresh and review again.
Text rendering treats labels as text, never Rich markup or terminal escapes.

Health polls in a background worker with bounded timeouts and no overlap. The
operator can pause auto-refresh without stopping applications or observability.
Latest completion order is fenced. UI timestamps and health expiry prevent an
old success from being shown as current. HTTP errors, malformed/oversized JSON,
untrusted redirects and incompatible responses become fixed diagnostic codes.
Only a validated loopback origin and fixed readiness route are accepted. The
observer does not read private identity files or accept arbitrary target URLs.

## Acceptance matrix

| ID | Acceptance |
|---|---|
| A1 | Register DE with three stable logical nodes; reload process/state and retain all fields and receipt. |
| A2 | Duplicate/invalid IDs, countries, node counts, terminal escapes and unknown fields fail without writes. |
| A3 | Decrease then increase node count; retained IDs are reused and no physical action is claimed. |
| A4 | Review at N, save another operation, then reject stale review; concurrent writers cannot lose updates. |
| A5 | Replay the same UUID/input once; changed input with that UUID fails and produces no second change. |
| A6 | Corrupt or unknown-version state fails visibly and remains untouched; failed replacement preserves the prior file. |
| A7 | Observability intent persists independently; business audit stays required; observed runtime is unchanged. |
| A8 | Successful actual gateway health shows current SQL/OPA evidence for known stores, never for new DE nodes. |
| A9 | Gateway/OPA loss makes current health unavailable/degraded; stale observations cannot remain healthy; recovery is observed. |
| A10 | Real Textual test driver registers/configures DE, reviews/cancels/saves, switches tabs, filters and handles stale reviews at 80x24 and 140x42. |
| A11 | PTY launches `./lab admin`, handles keys and exits restoring the terminal; JSON CLI supports automation without Textual. |
| A12 | Existing full lab acceptance stays mandatory. Admin unit/UI tests use isolated files and controlled HTTP fixtures; only A8/A9 against real containers count as lab-health integration evidence. |

## Later deployment adapter

Consume a reviewed configuration revision and bind logical node IDs to explicit
targets. Keep desired intent separate from observed runtime and execution
receipts. Provision, verify SQL/OPA/identity, then govern placement activation.
Capability prerequisites, migrations/fencing and dependency-safe observability
changes require separate operations and tests. No current management record can
be reinterpreted as proof that deployment or residency verification occurred.
