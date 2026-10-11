# Sovereign Federation Lab

A consolidated synthetic banking-data lab: **four independent CockroachDB stores, four OPA decision services, an HTTP gateway, OpenTelemetry, a data monitor and a complete design/ADR library**.

SG, UK and US serve the 30-entity federation examples. Mumbai is the fourth store for an isolated legal-entity relocation scenario. One node per store, one API coordinator; no HA or physical-residency claim.

## Start the development environment

Requirements: Docker Engine/Desktop with Compose v2 supporting `--wait-timeout`; Bash (WSL2 on Windows); approximately 8 GB available Docker memory and 10 GB disk. Internet access is needed to pull pinned images and Python packages on first build. Python and Node run inside helper containers.

```bash
./lab doctor
./lab up
./lab smoke
```

Open **http://localhost:8080**. API explorer: **http://localhost:8080/api-docs**.

`./lab up` rebuilds documentation, validates local navigation, builds images and waits for actual CockroachDB/OPA readiness. Both service entry points reject SQLite configuration. A live API failure stays visible and never switches to browser simulation. The hosted portal is separately and explicitly configured as a browser demonstration.

```bash
./lab test
./lab generate --count 5 --scenario sg-uk-no-us
./lab business --command open_holding --count 2
./lab migrate --reset
./lab sql IN -e 'SELECT owner,kind,count(*) FROM mig_rows GROUP BY owner,kind'
```

`./lab test` modifies synthetic data, exercises original federation/normalized data and the isolated migration, restarts the API, checks SQL authority and requires Collector span receipt. Its migration section resets only the isolated India fixture. Original datasets are not dropped. `./lab down` preserves named volumes; `./lab reset --confirm-synthetic-lab` removes this project's data and telemetry volumes.

Copy `.env.example` to `.env` to change LAB_PORT or COMPOSE_PROJECT_NAME. Only the gateway is published, bound to loopback. For a remote VM use `ssh -L 8080:127.0.0.1:8080 user@dev-host`, then open localhost:8080 on your workstation.

## Navigate the work

| Material | Entry point |
|---|---|
| Run and troubleshoot containers | [Development guide](docs/DEVELOPMENT.md) |
| Sixteen architectural decisions | [ADR register](docs/adr/README.md) |
| Verification status and gates | [Testing evidence](TESTING.md) |
| Core architecture | [Design](DESIGN.md) |
| Party/relationship/holding integration | [Operational data model](OPERATIONAL.md) |
| New-store/entity migration | [Migration contracts](MIGRATION.md) |
| Foreground vs bulk isolation | [Work isolation](WORK_ISOLATION.md) |
| 50M parties / 100M relationships and pilot backlog | [Scale assessment](scale/SCALE_AND_PILOT.md) |
| Origin and review findings | [Provenance](docs/source-provenance.json), [documentation audit](docs/DOCUMENTATION_AUDIT.md) |

The portal links the monitor, migration workspace, 28 component design pages, 16 ADR pages, capacity model and run guide. Design pages retain engineering prompts and label implemented lab features versus production targets.

## Implementation boundary

The lab implements actual SQL stores and OPA decisions; SQL outbox polling, field projections and exclusions; normalized business tables alongside sovereignty metadata; local command/receipt/outbox transactions; isolated migration with versioned changes and durable fencing; a gateway; readiness checks; OTel wiring; generators; reproducible builds and tests.

CDC/Kafka, regional production gateways/identity, signed policy distribution, distributed fencing, large-scale worker isolation, local HA, normalized-table migration and retained-storage erasure are pilot work. The original worker is serial; the queue-isolation page models the future design. The migration control row remains in SG, so source-cell decommissioning is not demonstrated.

**Execution limit:** Docker is unavailable in the authoring environment. Container integration has not passed here. Historical SQLite adapter tests and browser models are not CockroachDB evidence; run `./lab test` on the development host before acceptance. See TESTING.md.

## Repository layout

| Path | Responsibility |
|---|---|
| `poc/` | API, business/migration adapters, schema, policies, generators and tests |
| `shared/` | Canonical entity and business fixtures |
| `web/` | Editable monitor, portal and deployment-guide UI |
| `design/src/` | Component pages, diagrams and engineering prompts |
| `docs/adrs.json`, `docs/adr/` | Decision register and generated records |
| `scale/` | Assumptions, simulations, stored results and pilot actions |
| `infra/`, `compose.yaml` | Gateway and four-store deployment |
| `scripts/`, `lab` | Build, verification, deployment, release and GitHub export |
| `dist/` | Generated portable portal, committed for immediate inspection |
| `docs/history/` | Clearly marked earlier deployment documents/configuration |

The complete private source repository is hosted by Sites Git. The downloadable `.bundle` is a portable Git repository with the initial lab commit:

```bash
git clone sovereign-federation-lab.bundle sovereign-federation-lab
cd sovereign-federation-lab
```

On an authenticated GitHub workstation, `./scripts/publish-github.sh OWNER/sovereign-federation-lab` creates a new **private** GitHub repository, pushes the commit and verifies its visibility. The connection available during authoring cannot create GitHub repositories; no GitHub repository is claimed to exist until that helper succeeds. Existing repositories are never overwritten.
