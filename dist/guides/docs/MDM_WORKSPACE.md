# Customer workspace: preview, compact pilot and full pilot

The workspace is at **http://localhost:8081/** on the Docker host. It uses the
existing System and Experience APIs. Its directory is an authenticated,
owner/source-qualified CockroachDB query, not a browser cache.

For a first demonstration:

```bash
./lab pilot-compact-up
./lab pilot-token crm-sg
```

The token command deliberately prints the selected synthetic credential in your
terminal. Paste it into **Connect an identity**; never put it in a URL or capture
it in screenshots/logs. The UI retains credentials only in page memory.

## Read the connection strip first

| State | What it means |
|---|---|
| Browser preview | Read-only synthetic fixtures. No pilot API calls, database writes or OPA checks. |
| Live pilot, identity not connected | The gateway declares a real pilot; no authenticated readiness claim yet. |
| Live pilot, SG + UK connected | Authenticated checks reached SG/UK SQL, OPA and TLS peers. US, India, migration and telemetry are suspended. |
| Live pilot, full footprint connected | Checks reached all four database/OPA dependencies and three MDM peers. |
| Connection/dependency unavailable | A live request could not be verified. Unverified views are cleared; preview fixtures are never substituted. |
| Deployment mode unavailable | Configuration is missing or invalid. Connection/customer actions are disabled. Refresh retries configuration. |

Connection details show observed dependencies, check time, footprint and suspended
regions. Checks repeat every 20 seconds while the page is visible. They establish
reachability, not permission for a particular customer. Every business request
still applies its existing identity, processing, placement and policy checks.

A successful view identifies its actual **owner or projection**, store, scope
version and HTTP trace. Versions are independent per scope. The advanced minimum
applies to a relationship read, not every scope of an assembled customer view.
Request activity is this identity session, not the durable CockroachDB audit.

## A short demonstration

1. Connect as `crm-sg`. Search the source directory by name or reference. Each
   page contains up to 25 records; **Next page** follows a keyset cursor. Counts
   describe this page, not an enterprise-wide total.
2. Choose **New customer**, retain a `Synthetic ` name and `SYN-` reference, and
   select identity sharing explicitly. New records default to owner-only. Save
   and inspect the returned profile and trace.
3. Choose **Add relationship**. Use an `@example.invalid` email and select **UK
   servicing permitted · US excluded**. Inspect its contact and consent.
4. Copy the global customer ID, reconnect with `./lab pilot-token uk-servicing`,
   and look up that ID. Switching identity clears the old directory, customer
   fields, identifiers, response and request history. In-flight responses cannot
   repopulate them. Experience identities cannot enumerate the owner directory.
5. Update an authorised contact, then refresh the relationship. Verify its
   version and UK projection. Commands commit at the SG owner with the existing
   idempotent receipt, outbox and mandatory transactional audit.
6. In the full footprint, reconnect as `us-reader`: eligible minimal party fields
   may be returned while the excluded relationship is denied. A suspended US
   store is **not** evidence of exclusion, purge or physical erasure.

The built-in walkthrough follows these steps. **API evidence** shows HTTP status,
trace IDs and the latest JSON. Uncertain writes can be retried with the same
request ID and unchanged body. A stale version needs a refreshed view and review.

## Choose the footprint

| Configuration | Running stores | Monitoring | Demonstration |
|---|---|---|---|
| `./lab pilot-compact-up` | Two independent single-node stores: SG, UK | Grafana, Loki, Collector and local trace-file exporters suspended | Real creation, directory, UK projections, commands and durable audit |
| `./lab pilot-up` | SG, UK, US, India | Full pipeline | Original federation, US exclusion, India migration, telemetry and recovery |
| Static `dist/pilot.html` | None | None | Read-only preview with an explicit amber strip |

The override `infra/compose.mdm-compact.yaml` requires Compose **2.24.4+** for
`!override`. SG and UK remain separate databases. Legal-entity/store bindings and
policies are unchanged. Compact does not move US/India data elsewhere, create a
two-node distributed database, or remove retained data. Work for suspended
destinations stays durable and is excluded from the active relay batch so it
cannot starve UK work.

Compact startup waits up to four minutes for its startup reconciliation intents
to active stores to drain. It fails explicitly if they remain pending, rather
than opening a demo behind a retained-data backlog. New writes still replicate
asynchronously; use the returned scope version to check a particular read.

`./lab pilot-up` restores the full configuration, starts retained stores and
queues current-policy reconciliation. All named volumes are preserved. Ordinary
full acceptance commands reject the compact footprint; gates are not skipped.

Stopping containers reduces memory but does not remove image layers. On a VFS
Docker host, removing a stopped Grafana container and its rebuildable image can
reclaim substantial space. Preserve its named `grafana` volume. Full startup must
download the same pinned image again. Never delete data volumes to pass a test.

```bash
./lab pilot-compact-test
python3 poc/tests/pilot_browser.py --compact
# Restore before complete federation/migration/telemetry acceptance:
./lab pilot-up
./lab pilot-test
LAB_PILOT=1 ./lab test
```

For a remote host, forward the loopback UI. The link's `localhost` refers to the
Docker host until you establish a tunnel:

```bash
ssh -L 8081:127.0.0.1:8081 user@dev-host
```

## Scope and design references

The design takes inspiration from profile-centred MDM workspaces:
[Reltio Hub](https://docs.reltio.com/en/applications/hub/hub-at-a-glance),
[Reltio profile/dashboard composition](https://docs.reltio.com/en/applications/console/configuration-applications/ui-modeler-at-a-glance)
and [Semarchy customer authoring](https://www.semarchy.com/tutorials-content/build-your-first-data-authoring-app/).
It does not reproduce those products or claim their matching, survivorship,
quality scoring, stewardship, merge/split or enterprise identity capabilities.
No invented quality score or global customer total is displayed.

See [pilot contracts](PILOT.md), [service integration](SERVICE_INTEGRATION.md) and
[production gates](PRODUCTION_READINESS.md). Both footprints remain synthetic
single-host engineering pilots, not bank-data or production approvals.
