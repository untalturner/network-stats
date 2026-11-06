import { useCallback, useEffect, useState, type FormEvent } from "react";
import DiscoveryPage from "./DiscoveryPage";
import SchedulesPage from "./SchedulesPage";

import {
  Activity,
  AlertTriangle,
  Clock3,
  Gauge,
  Globe2,
  LayoutDashboard,
  Network,
  Pencil,
  Plus,
  RefreshCw,
  Router,
  Settings,
  ShieldCheck,
  Trash2,
  Wifi,
  X,
} from "lucide-react";

type HealthStatus = "checking" | "online" | "offline";
type Protocol = "icmp" | "tcp" | "http" | "https";

type MonitoringTarget = {
  id: number;
  name: string;
  target: string;
  protocol: Protocol;
  interval_seconds: number;
  timeout_seconds: number;
  is_enabled: boolean;
  device_id: number | null;
  created_at: string;
};

type Measurement = {
  id: number;
  target_id: number;
  measured_at: string;
  latency_ms: number | null;
  packet_loss_percent: number | null;
  is_available: boolean;
  error: string | null;
};

type TargetForm = {
  name: string;
  target: string;
  protocol: Protocol;
  interval_seconds: number;
  timeout_seconds: number;
  is_enabled: boolean;
};

const emptyForm: TargetForm = {
  name: "",
  target: "",
  protocol: "icmp",
  interval_seconds: 60,
  timeout_seconds: 5,
  is_enabled: true,
};

const navigation = [
  { label: "Overview", icon: LayoutDashboard },
  { label: "Connectivity", icon: Wifi },
  { label: "Speed Tests", icon: Gauge },
  { label: "DNS", icon: Globe2 },
  { label: "Topology", icon: Network },
  { label: "Route Explorer", icon: Router },
  { label: "Schedules", icon: Clock3 },
  { label: "Settings", icon: Settings },
];

async function apiRequest<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const response = await fetch(`/api/v1${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...options.headers,
    },
  });

  if (!response.ok) {
    let message = `Request failed (${response.status})`;

    try {
      const body = await response.json();
      message = body.detail ?? message;
    } catch {
      // Keep the HTTP status message if the response is not JSON.
    }

    throw new Error(message);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return response.json() as Promise<T>;
}

function App() {
  const [activePage, setActivePage] = useState<"Connectivity" | "Topology" | "Settings" | "Schedules">("Connectivity");
  const [health, setHealth] = useState<HealthStatus>("checking");
  const [targets, setTargets] = useState<MonitoringTarget[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [formOpen, setFormOpen] = useState(false);
  const [editingTarget, setEditingTarget] =
    useState<MonitoringTarget | null>(null);
  const [form, setForm] = useState<TargetForm>(emptyForm);
  const [saving, setSaving] = useState(false);
  const [measurements, setMeasurements] = useState<Record<number, Measurement[]>>({});
  const [probingTargetId, setProbingTargetId] = useState<number | null>(null);
  const [expandedTargetId, setExpandedTargetId] = useState<number | null>(null);

  const loadTargets = useCallback(async () => {
    setLoading(true);
    setError("");

    try {
      const result = await apiRequest<MonitoringTarget[]>("/targets");
      setTargets(result);

      const histories = await Promise.all(
        result.map(async (target) => {
          try {
            const history = await apiRequest<Measurement[]>(
              `/targets/${target.id}/measurements?limit=20`,
            );
            return [target.id, history] as const;
          } catch {
            return [target.id, []] as const;
          }
        }),
      );

      setMeasurements(Object.fromEntries(histories));
      setHealth("online");
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Could not load targets.",
      );
      setHealth("offline");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    let active = true;

    async function checkHealth() {
      try {
        await apiRequest<{ status: string }>("/health/ready");

        if (active) {
          setHealth("online");
        }
      } catch {
        if (active) {
          setHealth("offline");
        }
      }
    }

    void checkHealth();
    const interval = window.setInterval(checkHealth, 15000);

    return () => {
      active = false;
      window.clearInterval(interval);
    };
  }, []);

  useEffect(() => {
    void loadTargets();
  }, [loadTargets]);

  function openCreateForm() {
    setEditingTarget(null);
    setForm(emptyForm);
    setFormOpen(true);
    setError("");
  }

  function openEditForm(target: MonitoringTarget) {
    setEditingTarget(target);
    setForm({
      name: target.name,
      target: target.target,
      protocol: target.protocol,
      interval_seconds: target.interval_seconds,
      timeout_seconds: target.timeout_seconds,
      is_enabled: target.is_enabled,
    });
    setFormOpen(true);
    setError("");
  }

  function closeForm() {
    setFormOpen(false);
    setEditingTarget(null);
    setForm(emptyForm);
  }

  async function saveTarget(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    setError("");

    try {
      if (editingTarget) {
        await apiRequest<MonitoringTarget>(
          `/targets/${editingTarget.id}`,
          {
            method: "PATCH",
            body: JSON.stringify(form),
          },
        );
      } else {
        await apiRequest<MonitoringTarget>("/targets", {
          method: "POST",
          body: JSON.stringify(form),
        });
      }

      closeForm();
      await loadTargets();
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Could not save target.",
      );
    } finally {
      setSaving(false);
    }
  }

  async function toggleTarget(target: MonitoringTarget) {
    setError("");

    try {
      await apiRequest<MonitoringTarget>(`/targets/${target.id}`, {
        method: "PATCH",
        body: JSON.stringify({ is_enabled: !target.is_enabled }),
      });

      await loadTargets();
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Could not update target.",
      );
    }
  }

  async function runProbe(target: MonitoringTarget) {
    setProbingTargetId(target.id);
    setError("");

    try {
      await apiRequest<Measurement>(`/targets/${target.id}/probe`, {
        method: "POST",
      });

      const history = await apiRequest<Measurement[]>(
        `/targets/${target.id}/measurements?limit=20`,
      );

      setMeasurements((current) => ({ ...current, [target.id]: history }));
      setExpandedTargetId(target.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not run probe.");
    } finally {
      setProbingTargetId(null);
    }
  }

  async function deleteTarget(target: MonitoringTarget) {
    const confirmed = window.confirm(
      `Delete "${target.name}"? This cannot be undone.`,
    );

    if (!confirmed) return;

    setError("");

    try {
      await apiRequest<void>(`/targets/${target.id}`, {
        method: "DELETE",
      });

      await loadTargets();
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Could not delete target.",
      );
    }
  }

  const enabledCount = targets.filter((target) => target.is_enabled).length;

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark"><Activity size={21} /></div>
          <div>
            <div className="brand-name">Network Stats</div>
            <div className="brand-caption">NETWORK OBSERVABILITY</div>
          </div>
        </div>

        <div className="nav-label">MONITORING</div>
        <nav>
          {navigation.map(({ label, icon: Icon }) => (
            <button
              className={`nav-item ${label === activePage ? "active" : ""}`}
              key={label}
              type="button"
              disabled={label !== "Connectivity" && label !== "Topology" && label !== "Settings" && label !== "Schedules"}
              onClick={() => {
                if (label === "Connectivity" || label === "Topology" || label === "Settings" || label === "Schedules") {
                  setActivePage(label);
                }
              }}
              title={
                label === "Connectivity"
                  ? "Connectivity targets"
                  : label === "Topology"
                    ? "Network discovery"
                    : label === "Settings"
                      ? "Application settings"
                      : label === "Schedules"
                        ? "Scheduled jobs and execution history"
                        : "Coming in a future milestone"
              }
            >
              <Icon size={18} strokeWidth={1.8} />
              <span>{label}</span>
            </button>
          ))}
        </nav>

        <div className="sidebar-bottom">
          <div className="system-card">
            <div className="system-card-heading">
              <ShieldCheck size={16} />
              <span>System status</span>
            </div>
            <div className="system-status">
              <span className={`status-dot ${health}`} />
              {health === "online"
                ? "API operational"
                : health === "offline"
                  ? "API unavailable"
                  : "Checking API..."}
            </div>
          </div>
          <div className="version">Network Stats v0.1.0</div>
        </div>
      </aside>

      <main className="main-content">
        <header className="topbar">
          <div className="breadcrumb">
            Monitoring <span>/</span> {
              activePage === "Topology"
                ? "Network Discovery"
                : activePage === "Settings"
                  ? "Settings"
                  : activePage === "Schedules"
                    ? "Schedules & Jobs"
                    : "Connectivity"
            }
          </div>
          <div className="topbar-right">
            <span className="environment"><span /> LOCAL ENVIRONMENT</span>
            <div className="avatar">NS</div>
          </div>
        </header>

        <section className="page-content">
          {activePage === "Topology" ? (
            <DiscoveryPage />
          ) : activePage === "Schedules" ? (
            <SchedulesPage />
          ) : activePage === "Settings" ? (
            <SettingsPage
              onResetComplete={() => {
                setTargets([]);
                setMeasurements({});
              }}
            />
          ) : (
            <>
          <div className="page-heading">
            <div>
              <div className="eyebrow">NETWORK MONITORING</div>
              <h1>Connectivity</h1>
              <p>Configure and manage the endpoints monitored by Network Stats.</p>
            </div>
            <button className="primary-button" onClick={openCreateForm} type="button">
              <Plus size={16} /> Add target
            </button>
          </div>

          <div className="metric-grid">
            <MetricCard
              title="Total targets"
              value={String(targets.length)}
              unit=""
              icon={<Network />}
              description="Configured connectivity targets"
            />
            <MetricCard
              title="Enabled targets"
              value={String(enabledCount)}
              unit=""
              icon={<ShieldCheck />}
              description="Configured to be monitored"
            />
            <MetricCard
              title="Disabled targets"
              value={String(targets.length - enabledCount)}
              unit=""
              icon={<Activity />}
              description="Currently excluded from monitoring"
            />
            <MetricCard
              title="Measurements"
              value={String(Object.values(measurements).reduce((total, history) => total + history.length, 0))}
              unit=""
              icon={<Gauge />}
              description="Saved measurements in recent history"
            />
          </div>

          {formOpen && (
            <section className="panel target-form-panel">
              <div className="panel-heading">
                <div>
                  <h2>{editingTarget ? "Edit target" : "Add connectivity target"}</h2>
                  <p>Configure the endpoint and how often it should be checked.</p>
                </div>
                <button
                  className="icon-button"
                  type="button"
                  onClick={closeForm}
                  aria-label="Close form"
                >
                  <X size={18} />
                </button>
              </div>

              <form className="target-form" onSubmit={saveTarget}>
                <label>
                  Target name
                  <input
                    required
                    maxLength={150}
                    value={form.name}
                    onChange={(event) =>
                      setForm({ ...form, name: event.target.value })
                    }
                    placeholder="e.g. Cloudflare DNS"
                  />
                </label>

                <label>
                  Hostname or address
                  <input
                    required
                    maxLength={500}
                    value={form.target}
                    onChange={(event) =>
                      setForm({ ...form, target: event.target.value })
                    }
                    placeholder="e.g. 1.1.1.1 or example.com"
                  />
                </label>

                <label>
                  Protocol
                  <select
                    value={form.protocol}
                    onChange={(event) =>
                      setForm({
                        ...form,
                        protocol: event.target.value as Protocol,
                      })
                    }
                  >
                    <option value="icmp">ICMP (Ping)</option>
                    <option value="tcp">TCP</option>
                    <option value="http">HTTP</option>
                    <option value="https">HTTPS</option>
                  </select>
                </label>

                <label>
                  Interval (seconds)
                  <input
                    type="number"
                    min={5}
                    max={86400}
                    required
                    value={form.interval_seconds}
                    onChange={(event) =>
                      setForm({
                        ...form,
                        interval_seconds: Number(event.target.value),
                      })
                    }
                  />
                </label>

                <label>
                  Timeout (seconds)
                  <input
                    type="number"
                    min={0.1}
                    max={60}
                    step={0.1}
                    required
                    value={form.timeout_seconds}
                    onChange={(event) =>
                      setForm({
                        ...form,
                        timeout_seconds: Number(event.target.value),
                      })
                    }
                  />
                </label>

                <label className="form-checkbox">
                  <input
                    type="checkbox"
                    checked={form.is_enabled}
                    onChange={(event) =>
                      setForm({ ...form, is_enabled: event.target.checked })
                    }
                  />
                  Enable this target
                </label>

                <div className="form-actions">
                  <button
                    className="secondary-button"
                    type="button"
                    onClick={closeForm}
                    disabled={saving}
                  >
                    Cancel
                  </button>
                  <button
                    className="primary-button"
                    type="submit"
                    disabled={saving}
                  >
                    {saving
                      ? "Saving..."
                      : editingTarget
                        ? "Save changes"
                        : "Create target"}
                  </button>
                </div>
              </form>
            </section>
          )}

          {error && (
            <div className="error-banner" role="alert">
              <span>{error}</span>
              <button type="button" onClick={() => setError("")} aria-label="Dismiss error">
                <X size={16} />
              </button>
            </div>
          )}

          <section className="panel targets-panel">
            <div className="panel-heading">
              <div>
                <h2>Monitoring targets</h2>
                <p>Endpoints configured for connectivity monitoring</p>
              </div>
              <button
                className="secondary-button refresh-button"
                type="button"
                onClick={() => void loadTargets()}
                disabled={loading}
              >
                <RefreshCw size={14} className={loading ? "spin" : ""} />
                Refresh
              </button>
            </div>

            {loading ? (
              <div className="table-state">Loading monitoring targets...</div>
            ) : targets.length === 0 ? (
              <div className="table-state empty-targets">
                <div className="chart-icon"><Wifi size={23} /></div>
                <strong>No connectivity targets yet</strong>
                <span>
                  Add an IP address or hostname to start building your
                  monitoring configuration.
                </span>
                <button className="primary-button" type="button" onClick={openCreateForm}>
                  <Plus size={15} /> Add your first target
                </button>
              </div>
            ) : (
              <div className="table-wrapper">
                <table className="targets-table">
                  <thead>
                    <tr>
                      <th>Name</th>
                      <th>Endpoint</th>
                      <th>Protocol</th>
                      <th>Interval</th>
                      <th>Latest result</th>
                      <th>Status</th>
                      <th className="actions-heading">Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {targets.map((target) => (
                      <tr key={target.id}>
                        <td>
                          <strong className="target-name">{target.name}</strong>
                          <span className="target-id">ID #{target.id}</span>
                        </td>
                        <td className="endpoint-cell">{target.target}</td>
                        <td>
                          <span className="protocol-badge">
                            {target.protocol.toUpperCase()}
                          </span>
                        </td>
                        <td>{target.interval_seconds}s</td>
                        <td>
                          <LatestMeasurement measurement={measurements[target.id]?.[0]} />
                        </td>
                        <td>
                          <button
                            className={`status-toggle ${target.is_enabled ? "enabled" : "disabled"}`}
                            type="button"
                            onClick={() => void toggleTarget(target)}
                            aria-label={` ${target.is_enabled ? "Disable" : "Enable"} ${target.name}`}
                          >
                            <span />
                            {target.is_enabled ? "Enabled" : "Disabled"}
                          </button>
                        </td>
                        <td>
                          <div className="row-actions">
                            <button
                              className="probe-button"
                              type="button"
                              onClick={() => void runProbe(target)}
                              disabled={!target.is_enabled || probingTargetId !== null}
                              title={!target.is_enabled ? "Enable this target before probing" : "Run a probe now"}
                            >
                              <Activity size={14} />
                              {probingTargetId === target.id ? "Running..." : "Run now"}
                            </button>
                            <button
                              className="icon-button"
                              type="button"
                              onClick={() => openEditForm(target)}
                              aria-label={`Edit ${target.name}`}
                              title="Edit target"
                            >
                              <Pencil size={15} />
                            </button>
                            <button
                              className="icon-button danger"
                              type="button"
                              onClick={() => void deleteTarget(target)}
                              aria-label={`Delete ${target.name}`}
                              title="Delete target"
                            >
                              <Trash2 size={15} />
                            </button>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {targets.map((target) => {
                  const history = measurements[target.id] ?? [];
                  const expanded = expandedTargetId === target.id;

                  return (
                    <div className="measurement-section" key={`history-${target.id}`}>
                      <button
                        className="history-toggle"
                        type="button"
                        onClick={() => setExpandedTargetId(expanded ? null : target.id)}
                      >
                        <span>{target.name} · Recent measurements ({history.length})</span>
                        <span>{expanded ? "Hide" : "Show"}</span>
                      </button>
                      {expanded && (
                        history.length === 0 ? (
                          <div className="history-empty">
                            No measurements recorded yet. Select Run now to test this target.
                          </div>
                        ) : (
                          <div className="history-table-wrapper">
                            <table className="history-table">
                              <thead>
                                <tr>
                                  <th>Time</th><th>Result</th><th>Latency</th>
                                  <th>Packet loss</th><th>Details</th>
                                </tr>
                              </thead>
                              <tbody>
                                {history.map((measurement) => (
                                  <tr key={measurement.id}>
                                    <td>{new Date(measurement.measured_at).toLocaleString()}</td>
                                    <td>
                                      <span className={`result-label ${measurement.is_available ? "success" : "failure"}`}>
                                        {measurement.is_available ? "Available" : "Unavailable"}
                                      </span>
                                    </td>
                                    <td>{measurement.latency_ms === null ? "—" : `${measurement.latency_ms.toFixed(2)} ms`}</td>
                                    <td>{measurement.packet_loss_percent === null ? "—" : `${measurement.packet_loss_percent}%`}</td>
                                    <td>{measurement.error ?? "—"}</td>
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          </div>
                        )
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </section>

          <div className="footer-note">
            <span className={`status-dot ${health}`} />
            Backend connection: {health}
            <span className="footer-separator">·</span>
            Targets: {targets.length}
            <span className="footer-separator">·</span>
            {Object.values(measurements).reduce((total, history) => total + history.length, 0)} saved measurements
          </div>
            </>
          )}
        </section>
      </main>
    </div>
  );
}


function SettingsPage({ onResetComplete }: { onResetComplete: () => void }) {
  const [resetArmed, setResetArmed] = useState(false);
  const [confirmation, setConfirmation] = useState("");
  const [resetting, setResetting] = useState(false);
  const [error, setError] = useState("");
  const [backupFile, setBackupFile] = useState("");

  async function submitReset(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    if (confirmation !== "RESET" || resetting) return;

    setResetting(true);
    setError("");
    setBackupFile("");

    try {
      const result = await apiRequest<{
        status: string;
        message: string;
        backup_file: string;
      }>("/system/reset", {
        method: "POST",
        body: JSON.stringify({ confirmation }),
      });

      setBackupFile(result.backup_file);
      setResetArmed(false);
      setConfirmation("");
      onResetComplete();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not reset application data.");
    } finally {
      setResetting(false);
    }
  }

  return (
    <>
      <div className="page-heading">
        <div>
          <div className="eyebrow">APPLICATION CONFIGURATION</div>
          <h1>Settings</h1>
          <p>Manage application-level settings and data.</p>
        </div>
      </div>

      <section className="panel settings-panel">
        <div className="panel-heading">
          <div>
            <h2>Application information</h2>
            <p>Network Stats configuration and data are stored in the application database.</p>
          </div>
        </div>
        <div className="settings-info">
          <div>
            <span>Application</span>
            <strong>Network Stats</strong>
          </div>
          <div>
            <span>Data storage</span>
            <strong>SQLite database</strong>
          </div>
          <div>
            <span>Reset backups</span>
            <strong>Created automatically before reset</strong>
          </div>
        </div>
      </section>

      <section className="panel danger-zone">
        <div className="danger-zone-heading">
          <div className="danger-zone-icon"><AlertTriangle size={19} /></div>
          <div>
            <h2>Danger Zone</h2>
            <p>Actions here can permanently remove application data.</p>
          </div>
        </div>

        <div className="danger-zone-action">
          <div className="danger-zone-copy">
            <h3>Reset all data and configurations</h3>
            <p>
              Permanently deletes configured devices, monitoring targets,
              measurements, discovery history, schedules, and application settings.
              A database backup is created before anything is deleted.
            </p>
            <p className="danger-zone-preserve">
              The application installation, database migrations, and backup files are preserved.
            </p>
          </div>

          {!resetArmed && !backupFile && (
            <button
              className="danger-button"
              type="button"
              onClick={() => {
                setResetArmed(true);
                setError("");
              }}
            >
              Reset application data
            </button>
          )}
        </div>

        {resetArmed && (
          <form className="reset-confirmation" onSubmit={submitReset}>
            <p>
              This action cannot be undone. Type <strong>RESET</strong> below
              to enable the final confirmation.
            </p>
            <label>
              Confirmation
              <input
                autoComplete="off"
                autoFocus
                value={confirmation}
                onChange={(event) => setConfirmation(event.target.value)}
                placeholder="Type RESET"
                disabled={resetting}
              />
            </label>
            <div className="form-actions">
              <button
                className="secondary-button"
                type="button"
                disabled={resetting}
                onClick={() => {
                  setResetArmed(false);
                  setConfirmation("");
                  setError("");
                }}
              >
                Cancel
              </button>
              <button
                className="danger-button"
                type="submit"
                disabled={confirmation !== "RESET" || resetting}
              >
                {resetting ? "Creating backup and resetting..." : "Confirm permanent reset"}
              </button>
            </div>
          </form>
        )}

        {error && <div className="reset-error" role="alert">{error}</div>}

        {backupFile && (
          <div className="reset-success" role="status">
            <strong>Application data successfully reset.</strong>
            <span>Pre-reset backup: <code>{backupFile}</code></span>
            <span>Your application is ready to configure again.</span>
          </div>
        )}
      </section>
    </>
  );
}

function LatestMeasurement({ measurement }: { measurement?: Measurement }) {
  if (!measurement) {
    return <span className="latest-empty">No data yet</span>;
  }

  return (
    <span className={`latest-result ${measurement.is_available ? "success" : "failure"}`}>
      <span className="result-indicator" />
      {measurement.latency_ms === null ? "—" : `${measurement.latency_ms.toFixed(1)} ms`}
    </span>
  );
}

function MetricCard({
  title,
  value,
  unit,
  icon,
  description,
}: {
  title: string;
  value: string;
  unit: string;
  icon: React.ReactNode;
  description: string;
}) {
  return (
    <div className="metric-card">
      <div className="metric-top">
        <span>{title}</span>
        <div className="metric-icon">{icon}</div>
      </div>
      <div className="metric-value">
        {value}<span>{unit}</span>
      </div>
      <div className="metric-description">{description}</div>
    </div>
  );
}

export default App;
