# Network Stats — Development Action Plan

**Status:** Execution roadmap  
**Baseline date:** 6 November 2026  
**Canonical requirements:** [`PROJECT_SPEC.md`](PROJECT_SPEC.md)  
**Implementation audit:** [`IMPLEMENTATION_STATUS.md`](IMPLEMENTATION_STATUS.md)

This plan converts the canonical specification into ordered work with explicit exit criteria. It is a living execution plan; it must not redefine product requirements. If this document and `PROJECT_SPEC.md` disagree, the specification takes precedence until the user explicitly changes it.

---

## 1. Execution rules

1. Complete one meaningful task at a time. Do not jump to unrelated modules while the current task is unfinished.
2. Reuse and audit existing code before designing replacements.
3. Inspect relevant files before changing them.
4. Make file changes through terminal commands; do not ask the user to edit files manually in an IDE.
5. Keep changes small, controlled and reversible.
6. Run focused tests after each meaningful change.
7. Run the full relevant test/build suite at phase gates.
8. Verify behaviour, not merely the presence of code, endpoints or navigation labels.
9. The user manages Git commits. Do not stage, commit, reset, amend or rewrite Git history on the user's behalf.
10. Update `IMPLEMENTATION_STATUS.md` when work is actually verified.
11. Update this plan when sequencing changes, explaining why.
12. Keep this specification and plan available as context at the beginning of future development sessions.

## 2. Sequencing decision for the existing project

The canonical roadmap is:

1. Foundation.
2. Core platform.
3. Connectivity.
4. DNS.
5. Speed tests.
6. Topology and discovery.
7. Route Explorer.
8. Analytics.
9. Integrations.
10. Production polish.

However, discovery is already partially implemented and has been explicitly agreed to be finished rather than abandoned halfway. Therefore, **first complete the in-progress discovery workflow to a usable first version**, then resume the roadmap by auditing and closing gaps in Foundation/Core Platform/Connectivity. This is a limited sequencing exception, not a change to the product scope.

The initial one-container deployment, GitHub Actions, GHCR and TrueNAS lifecycle remain mandatory foundation work. The user previously emphasized validating the development-to-deployment lifecycle early. The project should avoid postponing all deployment validation until the product is very large; establish a minimal production image and CI path as part of the Foundation work while preserving the existing code.

## 3. Phase 0 — Project continuity and baseline

### Tasks

- [ ] Keep `PROJECT_SPEC.md`, `PROJECT_PLAN.md` and `IMPLEMENTATION_STATUS.md` at repository root.
- [ ] Verify their contents and ensure they agree.
- [ ] Inspect current Git status before each session where changes may matter.
- [ ] Preserve all existing user changes and backup files unless the user explicitly approves cleanup.
- [ ] Inventory repository structure and current dependencies before architectural changes.
- [ ] Maintain an explicit record of unresolved architecture decisions.

### Exit criteria

- The three documents exist at the repository root.
- The user can identify the current phase, next task and known blockers from the documents.
- Existing uncommitted Git changes remain untouched.

## 4. Immediate work — Complete device discovery

**Priority: First implementation work.**

### 4.1 Audit existing discovery contract

- [ ] Inspect `backend/app/discovery.py`.
- [ ] Inspect `backend/app/services/discovery.py`.
- [ ] Inspect `DiscoveryScan`, `DiscoveryResult` and `Device` models.
- [ ] Inspect discovery schemas and API routes.
- [ ] Confirm scan status transitions, persistence and result response structure.
- [ ] Decide and record how open ports are persisted and exposed. The scanner already collects them; they are useful for review and should not silently disappear.
- [ ] If schema changes are needed, add an Alembic migration and migration tests.

### 4.2 Enrich discovery results

- [ ] Add best-effort reverse-DNS hostname lookup.
- [ ] Add best-effort MAC lookup from the OS neighbour/ARP table.
- [ ] Preserve response time and open TCP ports.
- [ ] Make enrichment failures non-fatal to the scan.
- [ ] Distinguish unavailable data from empty/zero values.
- [ ] Support macOS development and validate Linux/Docker behaviour before deployment.
- [ ] Consider container capabilities and neighbour-cache visibility; do not assume a container can always see host ARP information.

### 4.3 Discovery methods

The first completed version may use the existing TCP scanner, but the discovery architecture must be extensible to the full specification.

- [ ] Keep the scanner modular so ARP, subnet scanning, mDNS and SSDP can be separate methods.
- [ ] Record discovery method and timestamps.
- [ ] Do not imply TCP scanning finds devices that reject all selected TCP ports.
- [ ] Defer router API integrations as an optional later extension.

### 4.4 Enrollment API

- [ ] Add explicit enrollment of one reviewed discovery result into managed inventory.
- [ ] Map discovered IP, hostname and MAC into the managed device model appropriately.
- [ ] Add duplicate protection and identity checks.
- [ ] Reject missing, invalid or already-enrolled results clearly.
- [ ] Keep discovery separate from managed inventory: never auto-enroll all results.
- [ ] Add service and API tests for successful and unsuccessful enrollment.

### 4.5 Discovery frontend

- [ ] Add network CIDR input and scan action.
- [ ] Display pending, running, completed and failed states.
- [ ] Display scan timestamps and status information.
- [ ] Display discovered IP, hostname, MAC and open ports where available.
- [ ] Provide a review step before enrollment.
- [ ] Enroll selected results only.
- [ ] Clearly show already-enrolled devices.
- [ ] Provide loading, empty, success and error states.
- [ ] Show enrolled devices in the managed inventory.

### 4.6 Discovery verification

- [ ] Test scanner success, timeout and invalid-network cases.
- [ ] Test hostname and MAC lookup success and failure.
- [ ] Test service persistence and interrupted-scan recovery.
- [ ] Test API response and error cases.
- [ ] Test enrollment and duplicate protection.
- [ ] Run the discovery UI against the actual LAN `192.168.50.0/24`.
- [ ] Compare results with available macOS network information.
- [ ] Verify a failed enrichment does not fail the scan.
- [ ] Verify no duplicate managed devices are created by repeated scans/enrollment attempts.

### Exit criteria

A user can scan a network from the WebUI, inspect enriched results and explicitly enroll selected devices. The system handles missing hostname/MAC data safely, and automated plus real-LAN verification passes.

## 5. Foundation — deployment and application packaging

This work should be progressed in parallel only where it does not interrupt the agreed discovery completion. It is a required early lifecycle validation.

### 5.1 Repository and application configuration

- [ ] Audit root and backend/frontend project structures.
- [ ] Define runtime configuration via environment variables and persisted application settings as appropriate.
- [ ] Separate development-only and production dependencies.
- [ ] Define a reliable application version source.
- [ ] Keep secrets out of source control.
- [ ] Document local development and production startup.

### 5.2 Docker

- [ ] Create a production Docker image for the existing application.
- [ ] Serve the built React frontend and FastAPI backend appropriately within the one-container design.
- [ ] Add health/readiness checks.
- [ ] Mount persistent application data at `/data`.
- [ ] Store SQLite data under the persistent mount.
- [ ] Establish reliable startup, shutdown and migration handling.
- [ ] Use a non-privileged container user where possible.
- [ ] Add only required capabilities, including `NET_RAW` if required for ICMP.
- [ ] Start with bridge networking; test LAN discovery and routing before considering host networking.

### 5.3 GitHub Actions and GHCR

- [ ] Configure CI to install backend dependencies and run backend tests.
- [ ] Configure frontend type-check and production build.
- [ ] Build the Docker image in CI.
- [ ] Validate image startup and health.
- [ ] Configure GHCR authentication for publishing.
- [ ] Publish `latest` after successful pushes to `main`.
- [ ] Publish release/version tags.
- [ ] Publish immutable commit-SHA tags.
- [ ] Build for `linux/amd64` and `linux/arm64`.
- [ ] Set package visibility to public as specified.
- [ ] Confirm the exact image name `ghcr.io/untalturner/network-stats`.

The repository is known to have been empty at the last recorded audit. Recheck before creating workflows or pushing code. The user owns and performs Git commits/pushes; do not commit on the user's behalf.

### 5.4 TrueNAS lifecycle validation

- [ ] Create/choose the persistent HDD dataset.
- [ ] Deploy the image as a Custom App/container.
- [ ] Mount the dataset at `/data`.
- [ ] Configure ports, environment and health checks.
- [ ] Validate monitoring and discovery network permissions/routing.
- [ ] Create initial data and measurements.
- [ ] Update to a newer image and verify the reported version changes.
- [ ] Verify data survives container replacement/update.
- [ ] Test rollback to a previous image.
- [ ] Verify database migration compatibility; image rollback alone does not reverse a schema migration.

### Exit criteria

The real application can be built, published, deployed, updated and rolled back on TrueNAS, with persistent data intact. Local development remains supported.

## 6. Core platform — configuration, scheduler, history and retention

### 6.1 Universal scheduler audit and completion

- [ ] Audit current APScheduler integration, job models, services and APIs.
- [ ] Define a common job contract used by all monitoring modules.
- [ ] Support intervals, daily/weekly/monthly schedules, weekdays, cron, timezone, start/end dates.
- [ ] Support enable/disable, pause/resume, run-now and skip-next.
- [ ] Expose last and next execution.
- [ ] Persist execution history and logs.
- [ ] Implement timeout and retry policies.
- [ ] Implement priority and concurrency controls.
- [ ] Define missed-job and restart recovery policies.
- [ ] Prevent duplicate job registration and execution.
- [ ] Coordinate discovery and bandwidth-heavy jobs to avoid unnecessary network load.

### 6.2 Monitoring configuration frontend

- [ ] Build the Connectivity page for creating, editing, listing, enabling/disabling and deleting targets.
- [ ] Expose protocol-specific parameters supported by the backend.
- [ ] Build the Schedules & Jobs page.
- [ ] Allow users to configure schedules without editing files.
- [ ] Show job status, frequency, last execution and next execution.
- [ ] Add run-now, pause/resume and skip-next controls where supported.
- [ ] Ensure all controls call real backend operations.
- [ ] Display validation and execution errors.

### 6.3 Settings and retention

- [ ] Audit existing settings and database configuration.
- [ ] Define configurable retention independently for measurement categories.
- [ ] Separate raw-data retention from aggregated-data retention.
- [ ] Implement minute, hourly and daily aggregation.
- [ ] Add safe scheduled cleanup.
- [ ] Add retention settings in the WebUI.
- [ ] Test cleanup and aggregation boundaries, timezone handling and restart behaviour.
- [ ] Ensure cleanup does not affect active jobs or delete raw data before policy expiry.

### 6.4 Database operational features

- [ ] Confirm SQLite WAL mode.
- [ ] Add indexes for time-series and query patterns.
- [ ] Add database backup and restore.
- [ ] Test migrations from an existing database.
- [ ] Track measurement engine/source and vantage point consistently.

### Exit criteria

Users can configure and control monitoring and all scheduled operations through the WebUI. Scheduler state matches actual execution. Historical data and retention work and survive restart.

## 7. Connectivity completion

- [ ] Audit current ICMP/TCP/HTTP/HTTPS probes against the full specification.
- [ ] Add protocol-specific configuration for packet count, interval, timeout, size and IPv4/IPv6 where applicable.
- [ ] Add TLS certificate validity/expiration checks.
- [ ] Add expected HTTP status and optional response conditions.
- [ ] Capture HTTP timing breakdown: DNS, TCP, TLS, TTFB and total.
- [ ] Record average/min/max latency, jitter, packet loss, availability and failure details where relevant.
- [ ] Add measurement timestamps, engine/source and vantage point.
- [ ] Ensure error and unavailable states are represented accurately.
- [ ] Build real connectivity history charts with time-range selection.
- [ ] Build a dashboard using persisted data rather than placeholders.
- [ ] Add outage and historical availability views.

### Exit criteria

Connectivity monitoring is configurable, historically queryable and visualized in the WebUI with accurate measurements and failures.

## 8. DNS monitoring

- [ ] Implement resolver configuration and presets for router, Cloudflare, Google and Quad9.
- [ ] Support custom resolvers.
- [ ] Implement UDP, TCP, DoT and DoH adapters.
- [ ] Support A, AAAA, MX and TXT queries.
- [ ] Support custom domains and query lists.
- [ ] Implement cold-cache and warm-cache test modes where meaningful.
- [ ] Persist duration, response code, resolved addresses, timeout and failure data.
- [ ] Integrate DNS tests with universal scheduling.
- [ ] Build DNS configuration and resolver comparison screens.
- [ ] Build historical charts and failure analysis.
- [ ] Add tests for protocol and resolver failures.

### Exit criteria

Users can configure independent DNS tests and compare resolver performance historically from the WebUI.

## 9. Speed testing

- [ ] Define provider adapter interface and capability metadata.
- [ ] Investigate Ookla, LibreSpeed, iPerf3 and Cloudflare supported options, licensing and runtime requirements.
- [ ] Implement provider adapters incrementally.
- [ ] Support multiple independent configurations per provider.
- [ ] Configure server, schedule, duration, repetitions, timeout and enabled tests.
- [ ] Persist download, upload, latency, jitter and packet loss where supported.
- [ ] Add scheduler concurrency and bandwidth protections.
- [ ] Build provider/server configuration UI.
- [ ] Build on-demand and scheduled execution flows.
- [ ] Build historical speed-test charts and comparisons.
- [ ] Keep bufferbloat as a future extension using compatible measurement interfaces.

### Exit criteria

Users can configure multiple independent speed-test jobs and view their historical results without causing uncontrolled overlapping tests.

## 10. Topology and discovery expansion

The first discovery workflow is completed in the immediate work section. This phase expands it to the full specification.

- [ ] Implement and validate ARP discovery.
- [ ] Implement subnet scanning as an explicit method.
- [ ] Implement mDNS discovery.
- [ ] Implement SSDP discovery.
- [ ] Keep router API integrations optional/future.
- [ ] Maintain device identity across changes in IP or observed attributes.
- [ ] Track first seen and last seen.
- [ ] Represent interfaces, gateways and network segments.
- [ ] Record evidence/source for relationships.
- [ ] Distinguish confirmed topology links from inferred links.
- [ ] Build topology visualization.
- [ ] Integrate managed devices with connectivity monitoring.

### Exit criteria

The user can discover, manage and visualize devices and supported network relationships with evidence and clear uncertainty.

## 11. Route Explorer

- [ ] Define common traceroute run/hop/probe model.
- [ ] Implement ICMP traceroute.
- [ ] Implement UDP traceroute.
- [ ] Implement TCP traceroute and configurable destination ports.
- [ ] Add configurable max hops, probes per hop and timeouts.
- [ ] Add on-demand and scheduled execution.
- [ ] Persist per-probe timings and non-responsive hops.
- [ ] Add reverse DNS enrichment.
- [ ] Add ASN/ISP enrichment where available.
- [ ] Add approximate geolocation where available.
- [ ] Cache enrichment data locally where appropriate.
- [ ] Build hop timeline and per-hop latency UI.
- [ ] Build geographic route map.
- [ ] Support online map providers and offline local tiles/imported data.
- [ ] Compare historical routes and detect route changes/latency increases.
- [ ] Ensure map/geolocation outages do not block traceroute collection.

### Exit criteria

Users can execute and schedule multiple traceroute methods, inspect hops, visualize routes online/offline and compare historical route changes.

## 12. Analytics and alerting

### 12.1 Analytics

- [ ] Implement availability, uptime and downtime calculations.
- [ ] Implement ISP outage detection using multiple independent destinations.
- [ ] Implement historical comparisons: today, yesterday, last week and custom periods.
- [ ] Implement latency/jitter/packet-loss/DNS anomaly detection.
- [ ] Implement gradual network degradation analysis.
- [ ] Implement route change analysis.
- [ ] Add bufferbloat when the required test engine exists.
- [ ] Preserve supporting measurements and confidence/evidence for derived conclusions.

### 12.2 Shared alert and incident engine

- [ ] Define alert rule and condition model.
- [ ] Support thresholds and persistence periods.
- [ ] Support device outages, availability, latency, packet loss, sustained degradation, DNS, speed-test and route conditions as source modules become available.
- [ ] Track active incidents and alert history.
- [ ] Generate incident start and recovery events.
- [ ] Add deduplication and cooldown/suppression policy.
- [ ] Make alerts configurable in the WebUI.
- [ ] Add notification channel interfaces.
- [ ] Integrate alerts with Home Assistant and Grafana capabilities.
- [ ] Add direct channels incrementally, based on an explicit decision.

### Exit criteria

Conditions generate reliable incidents and recovery events, with no uncontrolled duplicate notifications. The WebUI and integrations consume the same canonical incident/event state.

## 13. Prometheus and Grafana integration

- [ ] Implement authenticated/appropriately protected Prometheus-compatible `/metrics` endpoint according to deployment/security design.
- [ ] Export the metric families defined in `PROJECT_SPEC.md` as each source module becomes available.
- [ ] Control label cardinality; do not put arbitrary URLs, queries or unbounded IDs in labels.
- [ ] Define metric names, units, types and lifecycle semantics.
- [ ] Verify Prometheus can scrape the endpoint.
- [ ] Provide Grafana dashboard templates/provisioning examples.
- [ ] Demonstrate graphs for availability, latency, packet loss, DNS, speed tests, traceroute and job execution as implemented.
- [ ] Demonstrate Grafana alerting using Network Stats data.
- [ ] Document how Prometheus retention relates to SQLite historical retention.
- [ ] Ensure Grafana/Prometheus do not need to run duplicate network probes.

### Exit criteria

Grafana can graph Network Stats metrics and use them for alerts through Prometheus or a compatible data source. Network Stats continues collecting when Grafana/Prometheus is unavailable.

## 14. Home Assistant integration

- [ ] Implement authenticated, versioned REST API endpoints listed in `PROJECT_SPEC.md`.
- [ ] Add integration configuration and credential management to the WebUI.
- [ ] Define entity/sensor mapping for status, devices, connectivity, speed tests, DNS, topology, traceroute and jobs as available.
- [ ] Define reliable event delivery for alert start and recovery.
- [ ] Document Home Assistant sensor, dashboard and automation usage.
- [ ] Demonstrate notifications through Home Assistant services/automations.
- [ ] Verify API compatibility and authentication.
- [ ] Verify Network Stats operates independently when Home Assistant is down.

### Exit criteria

Home Assistant can consume Network Stats data, create sensors/dashboards and use monitoring events in automations and notifications.

## 15. Production polish and operations

- [ ] Complete authentication and authorization review.
- [ ] Secure stored integration credentials.
- [ ] Review API exposure and network security.
- [ ] Implement database backup/restore UX or documented operational flow.
- [ ] Test restoration on a clean deployment.
- [ ] Add structured operational logs and useful diagnostics.
- [ ] Review resource consumption on Aoostar hardware.
- [ ] Verify failure isolation between monitoring modules and integrations.
- [ ] Complete documentation for installation, configuration, updates, backup and rollback.
- [ ] Complete full backend/frontend/integration regression.

### Exit criteria

The application is suitable for reliable self-hosted operation on TrueNAS, including backup, recovery, upgrades, integrations and diagnostics.

## 16. Global definition of done

A feature is not complete merely because code or a navigation item exists.

For every feature, verify the applicable dimensions:

1. **Backend:** model, service, API contract, validation, failure handling and persistence.
2. **Scheduling:** independent configuration and execution where the operation is schedulable.
3. **Frontend:** configure, execute/control, inspect status, inspect history and handle loading/empty/error states.
4. **Data:** timestamp, source, vantage point, retention and aggregation where applicable.
5. **Integrations:** expose data/events through stable documented interfaces where required.
6. **Tests:** focused tests, regression and migration tests where applicable.
7. **Documentation:** explain configuration, limits and operational behaviour.

## 17. Verification gates

### Per change

- Inspect the relevant code before modification.
- Make one small logical change.
- Run focused tests/build.
- Inspect the changed file/diff.
- Record outcome and any remaining gap.

### Per phase

- Run the full backend test suite.
- Run frontend TypeScript validation and production build.
- Run database migration tests where applicable.
- Run integration/API tests.
- Perform manual end-to-end verification.
- Update `IMPLEMENTATION_STATUS.md` only after evidence is available.

### Deployment gate

- CI passes.
- Image starts and health check passes.
- TrueNAS can reach the necessary LAN targets.
- Persistent data survives update/container replacement.
- Rollback is tested with database compatibility accounted for.

## 18. Unresolved decisions register

These decisions require investigation or explicit agreement. Do not silently guess:

- Exact Ookla/Cloudflare speed-test implementation and licensing.
- Final Home Assistant integration delivery mechanism beyond the required REST API (native integration, MQTT discovery or both).
- Direct Network Stats notification channels beyond Home Assistant.
- Default retention values for each raw/aggregate measurement category.
- Authentication model and local-vs-remote access policy.
- Exact offline tile package/source and storage approach.
- Remote agent protocol and enrolment/security model.
- Final choice between MapLibre GL and Leaflet after evaluating offline requirements.
- Final component library within the Tailwind-based UI.

When a decision is made, update `PROJECT_SPEC.md`, this register and relevant acceptance criteria.
