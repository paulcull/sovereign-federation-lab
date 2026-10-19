# Logical lab admin

The terminal control plane manages **saved logical configuration** and observes
the running lab. It is separate from the existing cluster web console, business
APIs and infrastructure runtime. Physical target assignment comes later.

## Start

Run from the checked-out repository on Linux, macOS or WSL2 with Python 3.11+:

```bash
python3 -m venv .venv-admin
.venv-admin/bin/python -m pip install --require-hashes -r requirements-admin.txt
./lab admin
```

The optional terminal packages stay outside the business-service images. The
launcher selects `.venv-admin/bin/python` when present; `LAB_ADMIN_PYTHON` can
select another installed interpreter. No new network listener is created.

Start the compact lab separately with `./lab pilot-compact-up` for actual SG/UK
health. The TUI also works when Docker is unavailable, showing health as
unverified. It never switches to simulated health. Existing browser entry points
remain `http://localhost:8080/clusters/` and `http://localhost:8081/`.

## Demonstrate Germany

1. Press **a**. Enter `STORE-DE-01`, `Germany`, `DE`, and `3` logical nodes.
2. Select **Review configuration**. Read the changes and deployment boundary.
3. Select **Save configuration**. Germany appears with three stable logical node
   IDs, a revision and a durable receipt. Its status is **Backend unassigned**.
4. Select Germany and press **e**. Reduce desired count to one; review and save.
   Two identities remain suspended. Increasing to three reuses those identities.
5. Press **o** to change observability intent independently of stores. Saving
   this intent does not start or stop Collector, Loki or Grafana.
6. Open **Health** for current SQL/OPA reachability. Press **r** to refresh or
   **p** to pause automatic polling. Gateway failures invalidate current health;
   observations expire after 30 seconds. Polling does not control business audit.
7. Open **Activity** and press Enter on a receipt. Quit with **q**, restart, and
   confirm the configuration and receipts persist.

Use `/` to search and `?` for help. Minimum terminal size is 80×24; 140×42 gives
side-by-side inventory and detail. Tab/Shift-Tab navigate controls, arrows select
table rows, Enter opens selects/receipts, and Escape cancels forms.

## State and automation

The private `.lab-admin/state.json` contains logical configuration and management
receipts. It is independent of SQL and ignored by Git. Back up this directory
before local maintenance. Do not put customer data or secrets in display names.
These local receipts are not business audit or tamper-resistant governance logs.

Use `--state-dir` or `LAB_ADMIN_STATE_DIR` for separate environments; the default
is relative to the repository root. Each directory has its own independent
revision. Multiple operators on one shared directory serialize writes and reject
stale reviews. There is no distributed administration service or multi-host lock.

JSON commands need only Python's standard library:

```bash
./lab admin config
./lab admin status
./lab admin history
./lab admin plan register_store --payload '{"id":"STORE-DE-01","name":"Germany","country":"DE","node_count":3}'
# Use the reviewed revision and a fresh UUID; retain this UUID for retries.
./lab admin save register_store --payload '{"id":"STORE-DE-01","name":"Germany","country":"DE","node_count":3}' --expected-revision 0 --request-id 11111111-1111-4111-8111-111111111111
```

The example save expects an untouched revision-zero registry. Use the actual
revision from `plan`. Identical retries return the original receipt; changed
input using the same UUID fails. A stale review requires a new review. Corrupt,
oversized or unknown-version state fails visibly without a reset. After an
uncertain disk error, retry the identical request and UUID before issuing new work.

The observer accepts a loopback origin only, e.g.
`./lab admin --gateway http://127.0.0.1:8080 status`. It checks the fixed readiness
route without private pilot credentials. For a remote lab, establish an SSH
forward and use its loopback port. It rejects redirects and arbitrary URLs.
Each request uses an isolated Python probe with an eight-second total deadline;
expiry kills and reaps it, including a connection that keeps trickling bytes.
The next refresh can run normally. No shell or arbitrary command runs.

## Meaning of health

The four initial logical stores have fixed observation aliases to the existing
gateway. In compact mode SG and UK can show **SQL + OPA healthy**, while US and
India show **Suspended (gateway report)**. Observability's gateway report is
configuration evidence; it does not verify the Loki/Grafana pipeline. Shared
host resource numbers are not node allocation or capacity guarantees.

New stores, including another store in SG, have no observation binding and
cannot inherit baseline health. Logical node rows always show **Unassigned**
physical targets. No operation provisions native nodes, grants placement,
changes entity mappings, migrates data, decommissions nodes or certifies residency.

The next adapter must bind explicit infrastructure targets and safely reconcile
reviewed desired revisions into execution receipts. Identity/TLS, off-host state
durability, health of individual nodes, dependency-safe telemetry changes and
governed placement activation remain work before a pilot deployment.

See [specification and acceptance matrix](ADMIN_TUI_SPEC.md) and
[verification commands](../TESTING.md#logical-admin-terminal).
