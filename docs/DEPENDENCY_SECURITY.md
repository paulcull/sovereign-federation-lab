# Dependency security and update procedure

The dependency audit covers the application, optional scaling tools, browser and
audit tooling, and the actual images resolved by both Compose files, including
build helpers. It does not inspect customer records or private pilot credentials.
Use synthetic data for the functional acceptance that follows an upgrade.

## Reproduce the audit

Install the reviewed, hash-locked tooling on a Python 3.11+ host:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --require-hashes -r requirements-dev.txt
bash scripts/install_trivy.sh .venv/bin
./lab pilot-up
LAB_PILOT=1 ./lab test
TRIVY_DB_REPOSITORY=ghcr.io/aquasecurity/trivy-db:2 \
  .venv/bin/python scripts/audit_dependencies.py \
  --pip-audit .venv/bin/pip-audit --trivy .venv/bin/trivy
```

The installer verifies the Trivy 0.76.0 Linux x86_64 archive against its reviewed
SHA-256. Other platforms should install that version using their normal trusted
package mechanism. Keep certificate verification enabled; the existing
`LAB_BUILD_CA` build-secret overlay supports approved HTTPS-intercepting hosts.
`TRIVY_CACHE_DIR` can select a reusable cache. Run one audit at a time per cache.

CI executes this audit after the complete base/pilot container and browser
acceptance. Its `lab-evidence` artifact includes `security/summary.json`, the full
Python advisory report, image IDs/digests and complete Trivy reports/logs. Every
Compose image must be available locally; missing images and scan failures block
the audit rather than silently reducing coverage.

The gate rejects all known Python advisories and skipped Python packages. It
also rejects every HIGH or CRITICAL image finding with a reported upstream fixed
version. Lower-severity and unfixed findings remain in the reports. A fixed Go
or OS package version does not imply that a vendor has published a compatible
image containing it. Those findings still block the gate; this project does not
invent an exception or describe a failing audit as passed. There is no CVE
ignore list. A passing gate would not mean zero vulnerabilities or production
approval.

## Refresh dependencies

Edit the direct requirements in `poc/requirements.in`, `scale/requirements.in`
and `requirements-dev.in`, then regenerate their complete transitive locks:

```bash
.venv/bin/uv pip compile poc/requirements.in --python-version 3.12 \
  --generate-hashes -o poc/requirements.txt
.venv/bin/uv pip compile scale/requirements.in --python-version 3.11 \
  --generate-hashes -o scale/requirements.txt
.venv/bin/uv pip compile requirements-dev.in --python-version 3.11 \
  --generate-hashes -o requirements-dev.txt
```

Use `--upgrade-package NAME` when intentionally refreshing a transitive pin.
The runtime Dockerfile requires hashes. Refreshing only direct versions while
leaving an affected transitive pin is insufficient. Scanner/tool versions and
the verified Trivy archive checksum also require deliberate review.

The audit covers recognised Python/OS/Go/npm package metadata in the selected
artifacts. It does not certify every native bundled library, the workstation's
Chromium binary, the Docker daemon or the CI runner's system packages. The
updated Playwright package selects a newer browser in CI; local browser
acceptance may use an independently managed system Chromium. Host/browser
patching remains the environment owner's responsibility.

Update vendor image tags and immutable manifest digests in `compose.yaml`,
`compose.pilot.yaml`, `poc/Dockerfile`, `infra/Gateway.Dockerfile` and
`infra/NodeTools.Dockerfile`. Retain the
separate CockroachDB stores, source-side OPA enforcement and loopback gateways.
Never replace a vendor binary's embedded dependencies in place. Changing a
database release line requires a separate, supported migration/rollback plan;
do not infer that an existing volume can be downgraded after an upgrade.

Rebuild and execute `./lab pilot-test`, `./lab pilot-faults`,
`LAB_PILOT=1 ./lab test`, `LAB_PILOT=1 ./lab faults` and all three browser
walkthroughs sequentially. Keep mandatory transactional audit independent of
telemetry failures and check trace/log correlation after SDK or Collector changes.
Use the exact commit's CI result, not a previous image's acceptance.

## Findings and residual exposure

The 15 October 2026 scan used pip-audit 2.10.1 and Trivy 0.76.0. The initial Python
resolution included Starlette 0.46.2 through FastAPI 0.115.12. Seven distinct CVEs
were reported: CVE-2025-54121, CVE-2025-62727, CVE-2026-48710,
CVE-2026-48817, CVE-2026-48818, CVE-2026-54282 and CVE-2026-54283.
FastAPI 0.141.1 with Starlette 1.8.0 removes those findings. Uvicorn and Psycopg
are refreshed as well, including Psycopg's bundled native libraries. The
scaling dependencies retain their audited direct versions; their transitive
versions are now locked. Browser tooling moves to Playwright 1.64.0.

The Node helper only executes repository JavaScript and built-in Node modules.
Its image retains the patched Node 22 runtime and removes unused npm, Corepack
and Yarn dependency trees. This removes the affected package-manager code from
the final container filesystem; the JavaScript and browser/OPA parity gates still
execute normally. The upstream base image's findings remain in the before/after
inventory, rather than being presented as patched npm packages.
Normal startup rebuilds both helpers so an existing custom Node image cannot
silently survive a future Dockerfile security update.

FastAPI 0.141.1 supports the patched Starlette release while preserving the
lab's explicit OpenTelemetry 1.36 logging integration. Later FastAPI releases
introduce a newer telemetry dependency; changing the logging contract is outside
this CVE patch. The older SDK has no findings in this Python advisory scan.

Updated vendor images and the final scan results are recorded with this PR's
acceptance evidence and the [component inventory](security/dependency-scan-2026-10-15.json).
The observed image findings are:

| Component | Previous → updated | Critical findings before → after | HIGH/CRITICAL with a reported fixed version after |
|---|---|---:|---:|
| Application | FastAPI 0.115.12 / Starlette 0.46.2 → 0.141.1 / 1.8.0; Python 3.12.15 | 0 → 0 | 0 |
| Gateway / authority | nginx 1.28.0 → 1.30.6 | 2 → 0 | 0 |
| CockroachDB | 25.4.0 → 25.4.17 | 1 → 1 | 34 |
| OPA | 1.9.0 → 1.21.2 | 2 → 0 | 0 |
| Collector | 0.140.0 → 0.162.0 | 2 → 0 | 4 |
| Loki | 3.5.7 → 3.7.8 | 2 → 0 | 4 |
| Grafana | 12.2.0 → 12.4.13 | 10 → 0 | 2 |
| Node helper | 22.14.0 → 22.23.3; unused package managers removed | 5 → 0 | 0 |

Counts are finding instances per representative image, including repeated
package findings, rather than distinct CVEs or demonstrated exploit paths.
Unfixed HIGH findings also remain: for example, the application image reports
44 HIGH findings without a fixed version in this database snapshot. They remain
in the inventory and full reports despite not triggering this gate's fixable
finding rule.

**The image security gate fails:** 44 HIGH/CRITICAL finding instances have a
reported upstream fixed version across the four affected vendor components.
The remaining CockroachDB critical is CVE-2025-68121 in its embedded Go standard
library. Collector/Loki retain CVE-2026-78667, CVE-2026-78669 and CVE-2026-97031
in Go dependencies. Grafana reports two Tempo-module advisories; whether its
embedded client code reaches the affected Tempo server paths requires a reviewed
disposition, not an automatic exception. No finding is waived here.

Important unresolved categories include vendor-embedded Go dependencies and OS
packages. Even the evaluated CockroachDB 26.3 release retains
HIGH Go findings; the lab stays on the patched 25.4 line and preserves existing
data. A newer release number alone is insufficient evidence that an image is
clear.

## Validation and observed failure

Normal `./lab pilot-up` upgraded the existing volumes without deleting data.
The base integration/restart/India migration/telemetry suite, expanded
`pilot-test` and base outage suite passed on the patched images. The full
`pilot-faults` suite passed after correcting the repeatability defect below.
All three Chromium walkthroughs then passed: generator/migration, MDM
system/experience APIs and the microsite reader journey. A repeated isolation
run passed with owner reads of 0.04/0.03 seconds while the real paused peer/OPA
requests failed closed after 5.04/2.03 seconds. These are regression samples,
not a load benchmark.
Twelve audit-orchestration regressions pass, including stale-success evidence,
missing/malformed inventories, interrupted scans and ambient filtering. Offline
verification passes 55 HTML pages, 1,612 local links and 19 ADRs.

The first local fault run reached a legitimate 422 for the shared Aster owner
view: repeated earlier suites had accumulated enough contact history to exceed
the existing 32 KiB response bound. Its isolation test now creates an independent
synthetic customer and relationship through the real MDM APIs before checking
the real owner and UK projection. It preserves the response bound, retained
history, mandatory-audit checks and paused-dependency timing assertions.

The complete local dependency audit covered all 11 resolved image identities,
reported zero Python advisories/skipped packages and no scan errors, and exited
1 because of the 44 remaining vendor finding instances. Its completion is a
successful execution of a **failed security gate**, not a security pass. The
exact PR commit's workflow and `lab-evidence` artifact supply the final clean
build, browser, outage and CVE evidence; later findings may differ when advisory
data changes.

Published CVE severity is not a reachability assessment. Internal networking and
loopback gateways limit exposure in this synthetic lab; they do not establish
that every flagged dependency is unreachable. Before a bank pilot, obtain patched
vendor builds or an explicit, reviewed vulnerability disposition with an owner,
expiry and deployment evidence. This update supplies neither a risk acceptance
nor approval to process bank data. See [production gates](PRODUCTION_READINESS.md).
