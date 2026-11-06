# Network Stats — Implementation Status

**Status:** Initial baseline reconstructed from project history  
**Baseline date:** 6 November 2026  
**Specification:** [`PROJECT_SPEC.md`](PROJECT_SPEC.md)  
**Action plan:** [`PROJECT_PLAN.md`](PROJECT_PLAN.md)

> This document records implementation evidence, not intended scope. Status is based on the latest project history available when this baseline was prepared. It is not a fresh inspection of the user's Mac working tree. Re-verify items before relying on them.

---

## 1. Repository and development environment

| Item | Recorded status | Notes |
|---|---|---|
| Local repository | Exists | `/Users/untalturner/IdeaProjects/network-stats` |
| GitHub repository | Reported empty | No source had been pushed at the last audit; recheck before publishing |
| Backend | Implemented foundations | FastAPI/Python application |
| Frontend | Initial implementation | React/TypeScript/Vite shell and dashboard |
| Backend virtual environment | Exists | `backend/.venv` |
| Local backend startup | Verified previously | From `backend`: `uvicorn app.main:app --reload` |
| Local frontend startup | Verified previously | `npm run dev` from `frontend` |
| API docs | Available previously | `http://127.0.0.1:8000/docs` |
| Frontend dev URL | Available previously | `http://localhost:5173` |
| Database migrations | Ran previously | `alembic upgrade head` completed |

At the last captured `git status`, the working tree contained pre-existing staged/unstaged and untracked changes. In particular, `backend/app/database.py` and `backend/app/models.py` appeared as `AM`, with multiple untracked application, migration, test and frontend paths. These changes must be preserved. The assistant must not stage, reset, clean, commit or rewrite Git history.

There were no Markdown documents at the repository root when the documentation work began.

## 2. Backend implementation

| Capability | Status | Evidence / remaining work |
|---|---|---|
| FastAPI application | Implemented | `backend/app/main.py` and API routes exist |
| Health/readiness endpoints | Implemented | Health tests previously passed |
| SQLAlchemy models | Implemented foundation | Devices, targets, measurements, discovery and job-related models exist |
| SQLite persistence | Implemented foundation | Database setup exists |
| Alembic migrations | Implemented foundation | Migration environment and migration files exist; migration lifecycle still needs regression |
| Monitoring target CRUD API | Implemented | Target create/list/update/delete endpoints were implemented |
| ICMP probe | Implemented | Probe module exists |
| TCP probe | Implemented | Probe module exists |
| HTTP probe | Implemented | Probe module exists |
| HTTPS probe | Implemented | Probe module exists |
| Measurement persistence | Implemented | Monitoring measurements are persisted |
| APScheduler recurring jobs | Implemented foundation | A Cloudflare target was configured with a 30-second interval; scheduler logs showed successful probe execution |
| Job execution history/recovery | Partial | Some job/discovery recovery work exists; universal job contract and complete controls need audit |
| Authentication | Not verified / missing | Must be audited and implemented to the specification |
| Prometheus exporter | Not implemented | `/metrics` not yet confirmed |
| Home Assistant API integration | Not implemented | Required versioned endpoints not yet confirmed |

### Historical test results

Previously recorded results:

- Backend test suite reached **91 passed, 1 warning**.
- Focused discovery suite reached **30 passed, 1 warning**.
- An earlier test run failed async tests because `pytest-asyncio` was missing/configuration was incomplete; this was subsequently addressed. Do not treat that initial failure as the latest outcome.
- A Starlette/httpx deprecation warning was recorded in test output.

These are historical results, not a claim that tests have been rerun against the current working tree today. Run the current suite before declaring a phase complete.

## 3. Device discovery status

### Implemented

- Async TCP discovery scanner in `backend/app/discovery.py`.
- Default scanner ports: `22, 53, 80, 443, 445, 554, 631, 8000, 8080, 8443, 9100`.
- Concurrency limit of 100.
- Default connection timeout of approximately 0.5 seconds.
- IPv4 validation with a maximum network size of `/24`.
- Discovered host records include IP, open ports and response time.
- Discovery scan persistence and pending/running/completed/failed lifecycle.
- Background scan execution.
- Interrupted-scan recovery handling.
- API endpoints to create scans, retrieve scan status/results and list results.

### Real LAN test recorded

Network: `192.168.50.0/24`

A completed scan found three TCP-accessible hosts:

- `192.168.50.1` — likely router.
- `192.168.50.164` — unidentified.
- `192.168.50.250` — TrueNAS.

The recorded scan completed in approximately 14 seconds. A separate scan of `192.168.50.250/32` found TrueNAS.

### Enrichment experiments (manual only)

On macOS, reverse DNS for `192.168.50.250` returned hostname `yoda`.

The macOS ARP table returned MAC `c8:ff:bf:08:71:d8` for that IP.

These were manual OS-level tests only. They do not establish that hostname/MAC enrichment is implemented in the application, or that the same lookup will work inside the eventual Linux Docker container.

### Missing discovery work

- Hostname enrichment in the application.
- MAC enrichment in the application.
- Persist and expose open ports if confirmed as part of the discovery result UX (the scanner already collects them, but current model/schema/API do not expose them).
- ARP discovery method.
- mDNS discovery method.
- SSDP discovery method.
- Explicit result enrollment endpoint.
- Duplicate enrollment protection.
- Full discovery UI.
- Real-LAN verification through the UI.
- Linux/Docker validation of neighbour-cache and network permissions.

The current scanner detects only hosts accepting connections on selected TCP ports. It is not complete subnet discovery.

## 4. Frontend implementation

### Implemented

- React, TypeScript and Vite application.
- Initial dashboard layout and styling.
- Sidebar navigation labels for Overview, Connectivity, Speed Tests, DNS, Topology, Route Explorer, Schedules and Settings.
- API readiness polling at `/api/v1/health/ready` every 15 seconds.
- Initial placeholder metric cards and panels.

### Important limitation

The sidebar entries are navigation labels, not completed functional pages. The captured `App.tsx` snapshot showed a dashboard placeholder, a disabled “Monitoring setup coming next” action and a device discovery placeholder.

### Missing frontend work

- Functional page routing/navigation for all modules.
- Monitoring target create/edit/delete/configuration UI.
- Universal schedule/job configuration and controls.
- Discovery scan/review/enrollment workflow.
- Managed device inventory.
- Real dashboard data/widgets.
- Historical connectivity graphs.
- Speed test UI and history.
- DNS configuration/comparison UI.
- Topology visualization.
- Route Explorer and maps.
- Historical analytics screens.
- Alerts and notifications UI.
- Integrations configuration/verification UI.
- Settings and retention UI.
- Tailwind/component-library implementation and ECharts/map dependencies need inspection against the current project.

## 5. Data model and persistence audit notes

- `Device` includes name, hostname, IP, MAC, device type, notes, active state and timestamps.
- `DiscoveryScan` and `DiscoveryResult` models exist.
- `DiscoveryResult` includes hostname and MAC fields, even though the discovery service has not yet populated them.
- `DiscoveryResult` does not currently persist open ports.
- Existing discovery schema response does not expose open ports.
- Universal scheduler entities and job history need an audit against the complete scheduling specification.
- Retention policies, raw/aggregate separation, minute/hour/day aggregation, WAL mode, indexing, backup and restore all need explicit verification.

Schema changes require Alembic migrations. Do not modify models without checking migrations and tests.

## 6. External integrations and advanced features

| Capability | Status |
|---|---|
| Prometheus `/metrics` endpoint | Not implemented / not verified |
| Grafana dashboards and graphs | Not implemented |
| Grafana alerting from Network Stats metrics | Not implemented |
| Home Assistant versioned REST API | Not implemented / not verified |
| Home Assistant sensors and dashboards | Not implemented |
| Home Assistant automation/notification events | Not implemented |
| Shared alert/incident engine | Not implemented |
| Direct notification channels | Not implemented |
| DNS monitoring | Not implemented |
| Multi-provider speed tests | Not implemented |
| Network topology visualization | Not implemented |
| ARP/mDNS/SSDP discovery | Not implemented |
| Traceroute/Route Explorer | Not implemented |
| Online/offline route maps | Not implemented |
| Historical aggregation and advanced analytics | Not implemented / not verified |
| Bufferbloat | Future capability |
| Remote agents | Future capability |
| Router-side measurements | Future capability |

## 7. Docker, CI/CD and TrueNAS deployment

| Capability | Recorded status |
|---|---|
| Production Dockerfile/image | Not implemented / not verified |
| GitHub Actions CI | Not implemented |
| GHCR publication | Not done |
| Public GHCR package | Not published |
| AMD64/ARM64 image pipeline | Not implemented |
| TrueNAS Network Stats deployment | Not done |
| Persistent HDD dataset mounted at `/data` | Not configured for Network Stats |
| Update lifecycle verification | Not done |
| Rollback verification | Not done |
| Backup/restore verification | Not done |

The target image is `ghcr.io/untalturner/network-stats:latest`, with public visibility, version tags and immutable SHA tags. Confirm repository/package state before executing deployment actions.

## 8. Current next actions

The immediate implementation priority is to finish the existing discovery workflow, as recorded in `PROJECT_PLAN.md`:

1. Reinspect discovery API/model/schema contracts.
2. Implement best-effort hostname and MAC enrichment.
3. Decide and implement open-port persistence/exposure.
4. Add explicit discovery-result enrollment and duplicate protection.
5. Build the discovery frontend.
6. Verify scanning and enrollment against the real LAN.
7. Then audit universal scheduler contracts and complete Connectivity and Schedules frontend.

Do not start DNS, speed tests, topology expansion or Route Explorer while the agreed in-progress discovery workflow is incomplete, unless the user changes priorities.

## 9. Status update protocol

For every meaningful task, record:

- Date.
- Files/components changed.
- Behaviour implemented.
- Tests/builds run and exact result.
- Manual verification performed.
- Remaining limitations or known risks.

Use these status labels consistently:

- **Not started** — no implementation evidence.
- **In progress** — implementation underway but acceptance criteria incomplete.
- **Implemented, not verified** — code exists but required tests/manual checks are incomplete.
- **Verified** — acceptance criteria and relevant checks have passed.
- **Blocked** — cannot proceed; explain the concrete blocker.
- **Deferred** — intentionally moved to a later phase, with reason.

Never mark a feature verified because a file, API route, navigation label or placeholder exists.
