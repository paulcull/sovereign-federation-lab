# CockroachDB cluster control

Open **http://localhost:8080/clusters/** on the Docker host after `./lab up` or
`./lab pilot-up`. The gateway remains bound to loopback. This implemented console
reads the four real CockroachDB instances. Static previews report an unavailable
API instead of substituting simulated data.

## Cluster and environment experience

The initial **Clusters** view opens Singapore, UK, US or India. Overview shows SQL
identity, binary/cluster versions and database names. Nodes shows observed
liveness, country labels, ranges, process CPU/memory and physical store bytes.
Customer tables and records are not queried. Disk availability is shared with
other containers on the development host.

**Environment**, under Platform context, is a separate view of the single-host
Compose deployment and direct OPA/Loki/Grafana HTTP health probes. These probes
do not establish Docker container or host liveness. Four country labels on one
host do not establish four physical regions.

Business services retain interactions and transactions. Sovereign services retain
relationship policies, source exclusions and read/write placement. This console
manages database observations and scoped administrative checks beneath them.

## Working operations

**Run health check** verifies SQL, live nodes, available ranges and expected
country labels. This does not establish HA or physical residency.

**Run recovery rehearsal** opens a review dialog showing cluster, scope, storage
and restore destination. Enter its two-letter code to confirm. A durable journal
entry precedes execution. The regional worker creates a uniquely named temporary
database with three synthetic canary rows, executes native CockroachDB `BACKUP`
to that cluster's node-local volume, performs native `RESTORE` into another
temporary database, compares every restored row, and removes both temporary
databases on success. The canary backup is retained.

Recovery preflight requires a healthy cluster and at least 8% free node disk
(minimum 512 MiB), leaving headroom above CockroachDB's observed 5% ingest
threshold. The UI disables rehearsal when headroom is absent. Capacity can change
after preflight; a paused or uncertain operation still requires inspection.

Activity shows persisted steps and results. Native BACKUP/RESTORE jobs and
`cluster_control.events` supply operational audit evidence. These management
events remain separate from business transactional audit and OTel logs.

The rehearsal does **not** protect business data or prove recovery after losing
the host. Business backup schedules, retention, external regional storage,
off-host restores and RPO/RTO remain unconfigured. Failed temporary databases are
retained for inspection; there is no backup-erasure claim.

## Implementation boundary

This increment shares the existing trusted, single-process lab API. Its controller
has a worker and SQL management journal per cluster and does not acquire the
business harness's process-wide lock. A paused India database does not block UK
administrative checks. This is logical separation, not an independently deployed
or highly available fleet service. PostgreSQL management storage, Ansible/OpenTofu
provisioning, regional agents, Keycloak and OpenBao remain proposed standalone
architecture, not installed features.

Clients can select only two operation kinds and four registered targets. They
cannot submit SQL, connection strings, backup destinations or shell commands.
Mutations require a custom header and reject conflicting Origin/Fetch Metadata
headers. These protections are not authentication: loopback is a trusted
development boundary. Do not expose this surface publicly. Reviewed logging uses
route templates and fixed fields without SQL, credentials, raw URLs or payloads.

Job creation and operational audit commit atomically. UUIDs provide replay
receipts and cannot be reused for a different kind. Success follows database and
journal completion. API restart marks unfinished running jobs interrupted rather
than replaying a potentially completed mutation. Interrupted recovery blocks new
rehearsals until an operator inspects native jobs and retained artifacts;
automatic incident resolution is not implemented.

Latest successful recovery is queried independently of the latest 30 activity
entries. An unavailable journal displays unknown recovery status, rather than
claiming that no rehearsal has run. A lost final write is reconciled to
interrupted after SQL reconnects, retaining known native job receipts.

Scaling, decommission and upgrades remain unavailable pending a validated
multi-node adapter. There is no Docker socket mount or browser operation to
restart database containers. SQL remains insecure on the private development
network, as documented for the base lab.

## Reproduce acceptance

```bash
./lab doctor
./lab pilot-up
LAB_PILOT=1 ./lab cluster-test
LAB_PILOT=1 ./lab cluster-faults
.venv/bin/python poc/tests/cluster_control_browser.py
```

Install locked browser tools using the development guide. `cluster-test` checks
actual identities, sanitized metadata, guards, replay, native jobs, exact canary
contents, cleanup, audit and API restart persistence. `cluster-faults` pauses the
actual India database, verifies visible failure and continued UK operations, and
restores India even after assertions fail. Chromium covers the reader journey,
native operations, confirmation, results and 375/768/1440px layouts. Its transport
fault checks UI presentation, not additional database integration evidence.

The new controller package and cluster UI are MIT-licensed in their directories.
CockroachDB and dependencies retain their own licences. This does not make
CockroachDB open source. The existing dependency security gate and unresolved
vendor findings remain mandatory.
