# Network Stats — Product and Technical Specification

**Status:** Canonical requirements baseline  
**Baseline date:** 6 November 2026  
**Repository:** `untalturner/network-stats`  
**Initial deployment target:** TrueNAS SCALE on the Aoostar  
**Initial measurement source:** The NAS itself

This document defines the intended product and its technical architecture. It is the source of truth for product requirements and architectural decisions. It does not imply that a feature has already been implemented.

- `PROJECT_SPEC.md` defines **what** Network Stats must become.
- `PROJECT_PLAN.md` defines **in what order** we will build it and how each phase is accepted.
- `IMPLEMENTATION_STATUS.md` records **what actually exists and has been verified**.

Changes to agreed requirements or architecture must be recorded here deliberately. Do not silently change scope or treat a suggestion as an accepted requirement.

---

## 1. Product vision

Network Stats is a self-hosted network observability platform for monitoring, analysing and understanding a home or small-network environment.

It must provide:

- A complete WebUI.
- Configurable network and service monitoring.
- Device discovery and managed inventory.
- Historical measurements, graphs and analytics.
- Network topology visualization.
- Route exploration and geographic route visualization.
- Internet performance testing.
- DNS performance monitoring.
- Configurable alerts and notifications.
- Integrations with Prometheus, Grafana and Home Assistant.
- A modular architecture that can support remote monitoring agents in the future.

The application must be useful independently. Grafana, Prometheus and Home Assistant are integrations, not dependencies required for core monitoring to operate.

## 2. Architecture and deployment baseline

### 2.1 Initial deployment architecture

The initial deployment will run as **one Docker container** on the Aoostar TrueNAS SCALE system.

The container will logically separate these responsibilities:

- WebUI assets and application interface.
- FastAPI REST API.
- Authentication and configuration.
- Universal scheduler.
- Monitoring workers.
- Discovery engine.
- Analytics engine.
- Notification engine.
- Integration services.
- SQLite database access and persistence.

The logical separation must allow modules to evolve independently without requiring a microservices deployment. No Kubernetes or unnecessarily complicated multi-container architecture is required initially.

### 2.2 Technology stack

| Layer | Technology |
|---|---|
| Backend | Python 3.12+ and FastAPI |
| Frontend | React and TypeScript |
| UI styling/components | Tailwind CSS and a component library |
| Charts | ECharts |
| Maps | MapLibre GL or Leaflet |
| Database | SQLite |
| ORM | SQLAlchemy |
| Migrations | Alembic |
| Scheduler | APScheduler or equivalent |
| HTTP monitoring | HTTPX |
| DNS | dnspython |
| Prometheus metrics | prometheus-client |
| Container | Docker |
| CI/CD | GitHub Actions |
| Image registry | GitHub Container Registry |

The existing implementation should be audited before adding or replacing dependencies. Technology choices should remain consistent with this baseline unless a deliberate decision is recorded.

### 2.3 Architectural principles

- All monitoring configuration must be manageable through the WebUI.
- SQLite is the primary application database for configuration and historical data.
- Scheduler and monitoring workers are logically separated, even when running in one container.
- Monitoring engines must be modular, replaceable and extensible.
- The NAS is the only measurement source initially.
- The architecture must support remote agents and additional measurement sources later.
- Database migrations are mandatory from the beginning.
- The API must support external integrations.
- Local monitoring must not depend on online/cloud services.
- Security, logging, backup, error handling and observability are foundational concerns.

## 3. Connectivity and latency monitoring

Network Stats must monitor arbitrary hostnames and IP addresses.

### 3.1 Supported checks

- ICMP ping.
- TCP connection checks.
- HTTP checks.
- HTTPS checks.
- TLS certificate validity and expiration.
- HTTP response codes and response times.

### 3.2 Configuration

Monitoring configurations must support the applicable options for each protocol:

- Target address.
- Protocol and port.
- Number of packets/probes.
- Probe interval.
- Timeout.
- Packet size.
- IPv4 or IPv6 selection.
- Expected HTTP status.
- Optional HTTP response conditions.
- Individual schedule.
- Enabled/disabled state.
- Data retention policy.

Configuration belongs in the database and must be manageable through the WebUI. Monitoring behaviour must not be hardcoded in individual workers.

### 3.3 Measurements

Record and expose, where applicable:

- Average latency.
- Minimum latency.
- Maximum latency.
- Jitter.
- Packet loss.
- Availability.
- Successes and failures.
- Measurement timestamp.
- Measurement engine and source.
- Vantage point.

For HTTP and HTTPS checks, measure the individual timing stages separately:

- DNS resolution.
- TCP connection.
- TLS handshake.
- Time to first byte.
- Total response time.

A failed or unsupported measurement must never be represented as a successful measurement. Missing values must remain distinguishable from zero.

## 4. Internet speed testing

Speed testing must use a modular provider architecture rather than one hardcoded implementation.

### 4.1 Initial providers to investigate

| Provider | Intended use |
|---|---|
| Ookla Speedtest | Public internet speed testing |
| LibreSpeed | Open-source speed testing and configurable servers |
| iPerf3 | Controlled tests against an iPerf3 server |
| Cloudflare | Investigate supported measurement options |

These providers are candidates to investigate; their availability, licensing, execution requirements and supported metrics must be validated before implementation.

### 4.2 Independent configurations

Each provider must support multiple independent test configurations.

Example configurations:

- Ookla — every 6 hours.
- LibreSpeed — every 2 hours.
- iPerf3 — every 30 minutes.

Each configuration must have its own applicable:

- Provider.
- Server.
- Schedule.
- Duration.
- Repetitions.
- Timeout.
- Enabled tests.
- Concurrency and resource restrictions.

### 4.3 Measurements and controls

Record, where supported:

- Download speed.
- Upload speed.
- Latency.
- Jitter.
- Packet loss.
- Server selection and provider metadata.
- Test execution history.
- Measurement timestamp and source.

Prevent overlapping bandwidth-heavy tests and unnecessary network load. Provide configurable concurrency and bandwidth restrictions.

### 4.4 Future extension

Bufferbloat testing must be supported architecturally. It will compare latency under idle and loaded network conditions.

## 5. DNS performance monitoring

Network Stats must compare local DNS resolution with external providers.

### 5.1 Initial resolver presets

- Router: `192.168.50.1`
- Cloudflare: `1.1.1.1`
- Google: `8.8.8.8`
- Quad9: `9.9.9.9`

Support custom resolvers in addition to the presets.

### 5.2 Protocols and queries

Support:

- DNS over UDP.
- DNS over TCP.
- DNS over TLS (DoT).
- DNS over HTTPS (DoH).
- A records.
- AAAA records.
- MX records.
- TXT records.
- Custom domains.
- Custom query lists.
- Cold-cache and warm-cache tests.

### 5.3 Measurements and UI

Record:

- Response time.
- Failures.
- Timeouts.
- DNS response codes.
- Resolved addresses.
- Resolver and query configuration.
- Measurement timestamp and source.

The WebUI must support side-by-side resolver comparisons and historical performance charts.

## 6. Network topology and device discovery

Support manual and automatic device discovery.

### 6.1 Discovery methods

Initial discovery methods:

- ARP.
- Subnet scanning.
- mDNS.
- SSDP.

Optional future method:

- Router API integrations.

The current TCP scanner is an initial implementation, not the complete discovery requirement.

### 6.2 Device inventory

The managed device inventory should include:

- Device name.
- Hostname.
- IP addresses.
- MAC addresses.
- Device type.
- Network segment.
- First seen.
- Last seen.
- Availability/status.
- Associated monitoring configurations.

Discovered devices must be reviewed before being added permanently to managed inventory. Discovery must not automatically enroll every detected device.

The system must prevent duplicate enrollment and preserve identity when addresses or other observed attributes change.

### 6.3 Monitoring vantage points

Support measurements from the NAS to:

- Router.
- LAN clients.
- Servers.
- Internet destinations.

Router-to-client latency requires router-side measurements or another measurement source. Never present an inferred value as a directly measured result.

### 6.4 Topology

Visualize known devices and network relationships. Distinguish confirmed relationships from inferred relationships, and show the source of topology information where possible.

Network segments, interfaces and gateways must be representable in the data model.

## 7. Traceroute and Route Explorer

Route Explorer must provide interactive route exploration rather than only a basic traceroute command.

### 7.1 Supported methods

- ICMP traceroute.
- UDP traceroute.
- TCP traceroute.
- Configurable destination ports.
- Configurable maximum hops.
- Configurable probes per hop.
- Configurable timeouts.
- Reverse DNS lookups.
- Scheduled execution.
- On-demand execution.

### 7.2 Per-hop data

Store:

- Hop number.
- IP address.
- Reverse DNS name.
- Individual probe times.
- Average latency.
- Non-responsive probes.
- ASN information where available.
- ISP information where available.
- Approximate geolocation where available.

Enrichment failures must not invalidate the underlying traceroute result.

### 7.3 Visualization and analysis

Provide:

- Hop-by-hop route timeline.
- Geographic route map.
- Latency per hop.
- Historical route comparisons.
- Route-change detection.
- Identification of unusual latency increases.

### 7.4 Online and offline maps

Both online and offline map operation must be supported.

Offline mode should support locally hosted tiles or imported map data. Geolocation data should be locally cacheable.

Map rendering must be independent of traceroute collection and geolocation enrichment. A missing map or geolocation service must not prevent route measurements from being collected and stored.

## 8. Universal scheduling engine

The scheduler is a shared platform capability. Individual monitoring modules must not implement unrelated scheduling systems.

Every monitoring operation must have its own configuration and schedule.

### 8.1 Scheduling expressions

Support:

- Every N minutes or hours.
- Daily.
- Weekly.
- Monthly.
- Specific weekdays.
- Custom cron schedules.
- Start dates.
- End dates.
- Configurable timezone.

### 8.2 Job controls

Every applicable job must support:

- Enable and disable.
- Pause and resume.
- Run now.
- Skip next execution.
- Last execution.
- Next execution.
- Execution history.
- Timeout policy.
- Retry policy.
- Priority.
- Concurrency limits.
- Missed-job handling.
- Duplicate-execution protection.

### 8.3 Resource and network protection

The scheduler must coordinate work to prevent unnecessary network load.

In particular:

- Avoid overlapping speed tests that exceed configured limits.
- Avoid excessive concurrent discovery scans.
- Respect per-job concurrency and priority.
- Handle timeouts and retries without creating duplicate executions.
- Make execution state and failures inspectable.

The scheduler must be robust across application restarts and must recover or account for interrupted and missed jobs according to an explicit policy.

## 9. Analytics, alerts and advanced monitoring

Analytics and alerts must use shared measurement and event infrastructure.

The architecture and data model must accommodate these capabilities even when their implementation is scheduled for a later phase.

### 9.1 Analytics capabilities

| Capability | Description |
|---|---|
| ISP outage detection | Detect outages using multiple independent destinations |
| Anomaly detection | Identify unusual latency, jitter, packet loss or DNS degradation |
| Bufferbloat | Compare latency under idle and loaded conditions |
| Historical comparisons | Compare today, yesterday, last week and custom periods |
| Availability statistics | Uptime, downtime and service availability |
| Network degradation | Identify gradual deterioration in performance |
| Route change detection | Compare traceroute paths over time |
| Device availability | Detect devices disappearing from the network |

Where a conclusion depends on several measurements, preserve the underlying evidence and avoid presenting uncertain inferences as confirmed facts.

### 9.2 Alerts

Alerts must cover configurable conditions such as:

- Device or target outages.
- Availability loss.
- Latency thresholds.
- Packet loss.
- Sustained degradation.
- DNS failures or degradation.
- Speed-test conditions.
- Route changes.
- Unusual network conditions.

Support configurable thresholds and persistence periods to reduce false positives.

Alerts must support:

- Enable and disable.
- Current condition/state.
- Alert and incident history.
- Start and recovery events.
- Deduplication.
- Cooldowns or suppression policies where appropriate.
- Integration with notification channels.

Home Assistant is an important initial integration for notifications and automation. Additional notification channels can be introduced incrementally.

The event model should allow the same underlying incident and recovery information to be consumed by the WebUI and integrations, rather than maintaining conflicting alert states in separate modules.

## 10. WebUI

Everything related to application behaviour must be configurable through the WebUI. Ordinary configuration must not require editing YAML, environment files or source code.

### 10.1 Navigation

The proposed navigation is:

1. Dashboard
2. Connectivity
3. Speed Tests
4. DNS Monitoring
5. Network Topology & Discovery
6. Route Explorer
7. Schedules & Jobs
8. Historical Data & Analytics
9. Alerts & Notifications
10. Integrations
11. Settings

Every visible navigation item must lead to a functional page or be clearly identified as not yet available.

### 10.2 Dashboard

The dashboard should be customizable with widgets for:

- Internet status.
- Current latency and packet loss.
- Speed-test results.
- DNS performance.
- Device availability.
- Network health.
- Recent alerts.
- Historical performance.

Dashboard widgets must use real measurements and clearly indicate missing or stale data.

### 10.3 Configuration

Users must be able to configure, as applicable:

- Monitoring targets.
- Providers.
- Devices.
- DNS resolvers.
- Schedules and jobs.
- Data retention.
- Alert thresholds.
- Notification channels.
- Integrations.
- Application settings.

### 10.4 Historical views

Provide real historical charts and data views for the supported measurement categories, including appropriate time ranges and comparisons.

The UI must distinguish raw measurements, aggregates, failed probes, gaps and unavailable data.

## 11. Database and historical data

SQLite is the primary application database.

The data model must cover the following entity groups.

| Entity group | Main records |
|---|---|
| Devices | Devices, interfaces, network segments |
| Connectivity | Targets, configurations, ping and HTTP results |
| Speed tests | Providers, servers, configurations, results |
| DNS | Resolvers, configurations, query results |
| Traceroute | Runs, hops, probes, geolocation metadata |
| Discovery | Scans, discovered devices, discovery history |
| Scheduling | Jobs, executions, execution logs |
| Analytics | Aggregated measurements, alerts, incidents |
| Application | Settings, integrations, credentials |

### 11.1 Retention

Retention must be configurable independently by measurement category.

Raw measurements and aggregates must have independent retention policies.

Example only: raw ping measurements may be retained for 30 days while hourly summaries are retained for one year. These are not fixed defaults; the actual defaults must be configurable.

### 11.2 Aggregation

Support:

- Minute aggregation.
- Hourly aggregation.
- Daily aggregation.

Aggregation must preserve the meaning of the underlying data and be suitable for historical comparisons and external integrations.

### 11.3 Database engineering

Requirements:

- SQLite WAL mode.
- Appropriate indexes.
- Schema migrations through Alembic.
- Automatic cleanup.
- Separate retention for raw and aggregated data.
- Database backup and restore.
- Measurement source tracking.
- Vantage-point tracking.

Data cleanup must not delete records prematurely or interfere with active jobs. Migrations and backup/restore must be tested.

## 12. External integrations

### 12.1 Prometheus and Grafana

Expose a Prometheus-compatible `/metrics` endpoint.

Initial metric families:

```text
network_ping_latency_ms
network_ping_packet_loss_percent
network_ping_success_total
network_http_response_time_ms
network_dns_query_duration_ms
network_dns_query_failures_total
network_speedtest_download_mbps
network_speedtest_upload_mbps
network_speedtest_latency_ms
network_traceroute_hop_latency_ms
network_monitor_job_last_execution_timestamp
```

Metric labels must be controlled to avoid high-cardinality problems. In particular, do not use arbitrary URLs, query values or unbounded dynamic identifiers as labels.

Prometheus and Grafana must be able to use Network Stats measurements without duplicating the monitoring operations.

The integration should support Grafana graphs and alerting based on Network Stats data. Dashboard templates or provisioning examples should be considered part of the integration deliverables.

Historical storage in Network Stats remains important even when Prometheus is also collecting exported metrics.

### 12.2 Home Assistant

Expose authenticated, versioned REST endpoints:

```text
/api/v1/status
/api/v1/devices
/api/v1/connectivity
/api/v1/speedtests/latest
/api/v1/dns/latest
/api/v1/network/topology
/api/v1/traceroute/latest
/api/v1/jobs
```

These endpoints must allow Home Assistant to consume monitoring results and create sensors, dashboards and automations.

Home Assistant must be able to use relevant monitoring events for automation and notifications.

The integration must not make Network Stats dependent on Home Assistant availability.

### 12.3 Integration engineering

- API versioning is mandatory.
- Authentication is mandatory.
- Credentials must be stored securely.
- Integration configuration must be manageable through the WebUI.
- Integration failures must not stop core monitoring.
- External access must not require exposing unauthenticated application endpoints.
- Integration documentation and connection verification must be provided.

## 13. Security, reliability and operational requirements

Security, backup, logging and error handling are part of the foundation.

### 13.1 Security

- Authenticate protected API access.
- Protect integration credentials and secrets.
- Apply appropriate authorization to configuration and control operations.
- Avoid exposing sensitive values through logs or API responses.
- Use least privilege for container capabilities.
- Do not use privileged container mode unless a demonstrated requirement cannot be met otherwise.

### 13.2 Reliability

- Handle network timeouts and unavailable destinations.
- Keep one failed probe from stopping unrelated monitoring.
- Persist meaningful failure results.
- Recover safely after application restarts.
- Prevent duplicate scheduled executions.
- Handle external integration outages independently of core monitoring.
- Keep the application usable without external cloud services.

### 13.3 Backup and recovery

- Provide database backup and restore.
- Document configuration and data recovery.
- Test recovery against the deployed persistent dataset.
- Consider database consistency when copying or restoring SQLite data.

### 13.4 Logging and diagnostics

Provide useful operational logs for:

- Scheduler activity.
- Job execution.
- Monitoring failures.
- Discovery.
- Database migrations.
- Retention and aggregation.
- Integrations.
- Notifications.
- Application startup and shutdown.

Logs must make failures diagnosable without exposing secrets.

## 14. Future measurement sources and remote agents

The NAS is the only measurement source initially.

The architecture must allow future remote agents to perform measurements from additional network locations.

Measurement records must identify the engine, source and vantage point so that results from different locations are not confused.

Router-to-client latency and other measurements that cannot be observed directly from the NAS must use a suitable measurement source. They must not be fabricated or inferred and presented as direct measurements.

Remote agents are a future extension; they are not required for the first deployment.

## 15. TrueNAS and GitHub deployment requirements

Confirmed project configuration:

| Setting | Value |
|---|---|
| Repository | `untalturner/network-stats` |
| Default branch | `main` |
| Docker image | `ghcr.io/untalturner/network-stats:latest` |
| Configuration storage | SQLite on persistent HDD dataset |
| Deployment | Manual update on TrueNAS |
| Image visibility | Public |
| CI/CD | Automatic build and publish |

The GitHub repository was reported empty in the project history. No source had been pushed and no Network Stats image had been published at the last recorded audit. These are target settings, not claims of an existing deployment. Recheck before acting on this status.

### 15.1 GitHub Actions

The pipeline must:

- Run backend tests.
- Build and validate the frontend.
- Build and test the Docker image.
- Publish `latest` after successful pushes to `main`.
- Publish version tags for releases.
- Publish immutable SHA-tagged images.
- Support AMD64 and ARM64 builds.

The pipeline must fail if required validation fails.

### 15.2 Docker and TrueNAS

- Initially run the application in one Docker container.
- Store SQLite and persistent application data on the HDD dataset.
- Mount persistent data at `/data`.
- Configure health checks and restart behaviour.
- Support safe database migrations.
- Support manual image updates through TrueNAS.
- Verify data survives container replacement and updates.
- Verify rollback to a previous image/version.

Use bridge networking initially with only necessary capabilities, such as `NET_RAW` for ICMP where required.

Test actual TrueNAS routing and network access before deciding whether host networking is necessary. Avoid privileged mode.

## 16. Global engineering principles

These principles apply to every implementation phase:

1. No hardcoded monitoring behaviour. Configuration belongs in the database and WebUI.
2. Every monitoring operation is independently schedulable.
3. Every measurement has a timestamp and source.
4. Measurement source and vantage point are recorded.
5. Historical data is retained according to configurable policies.
6. Monitoring modules are independent and extensible.
7. The NAS is the initial measurement source, but remote agents remain possible.
8. Online services are not mandatory for local monitoring.
9. Offline map support is preserved.
10. The API is versioned and authenticated for external integrations.
11. Security, backup, logging and error handling are foundational.
12. Failed or unsupported measurements are never represented as successful.
13. Shared scheduler, measurement, persistence, analytics and event infrastructure must be reused.
14. Tests and documentation accompany each feature.
15. A feature is not complete merely because a backend endpoint or navigation label exists. Its required UI, persistence, behaviour and integrations must also work and be verified.

## 17. Development roadmap

This roadmap determines implementation order, not product scope. All requirements in this specification remain part of the intended product.

| Phase | Deliverables |
|---|---|
| 1. Foundation | Repository, Docker, CI/CD, database and migrations |
| 2. Core platform | WebUI, API, configuration, scheduler, history and retention |
| 3. Connectivity | Ping, TCP, HTTP(S), charts |
| 4. DNS | Resolver monitoring and comparison |
| 5. Speed tests | Provider adapters and independent schedules |
| 6. Topology | Device inventory and automatic discovery |
| 7. Route Explorer | Traceroute, hop analysis, maps and route history |
| 8. Analytics | Outage detection, anomalies, bufferbloat and comparisons |
| 9. Integrations | Prometheus, Grafana and Home Assistant |
| 10. Production polish | Alerts, backups, security, performance and documentation |

Existing implemented work must be audited and reused. The roadmap does not require discarding or rewriting working code simply to match the phase numbering. Work already in progress may be completed as a controlled exception before returning to the roadmap.

## 18. Document governance

- `PROJECT_SPEC.md` defines the product and architectural requirements.
- `PROJECT_PLAN.md` defines task sequencing, dependencies and acceptance criteria.
- `IMPLEMENTATION_STATUS.md` records actual implementation and verification status.

Do not use implementation status as a substitute for requirements.

Do not silently change agreed architecture or scope. Record deliberate decisions here and update the plan and status documents as appropriate.

The user manages Git commits. Development assistance must not commit changes or alter Git history on the user's behalf.
