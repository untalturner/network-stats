import { useCallback, useEffect, useState, type FormEvent } from "react";
import { Clock3, Pencil, RefreshCw, Search, ShieldCheck, X } from "lucide-react";

type ManagedDevice = {
  id: number;
  name: string;
  hostname: string | null;
  ip_address: string | null;
  mac_address: string | null;
  device_type: string | null;
  notes: string | null;
  is_active: boolean;
  first_seen_at: string;
  last_seen_at: string | null;
};

type DeviceEditForm = {
  name: string;
  hostname: string;
  ip_address: string;
  device_type: string;
  notes: string;
};

type DiscoveryResult = {
  id: number;
  scan_id: number;
  device_id: number | null;
  device_name: string | null;
  ip_address: string;
  mac_address: string | null;
  hostname: string | null;
  discovery_method: string;
  response_time_ms: number | null;
  icmp_latency_ms: number | null;
  icmp_is_available: boolean | null;
  icmp_error: string | null;
  open_ports: number[];
  discovered_at: string;
};

type DiscoveryScan = {
  id: number;
  network_cidr: string;
  status: "pending" | "running" | "completed" | "failed" | string;
  started_at: string | null;
  finished_at: string | null;
  devices_found: number;
  error: string | null;
  created_at: string;
  results: DiscoveryResult[];
};

type DiscoveryStats = {
  total_scans: number;
  active_scans: number;
  total_observations: number;
  discovered_devices: number;
  enrolled_devices: number;
};

type EnrollmentForm = {
  name: string;
  device_type: string;
  notes: string;
};

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
      // Keep the HTTP status message.
    }
    throw new Error(message);
  }

  return response.json() as Promise<T>;
}

function formatDate(value: string | null): string {
  return value ? new Date(value).toLocaleString() : "—";
}

function DiscoveryPage() {
  const [networkCidr, setNetworkCidr] = useState("192.168.50.0/24");
  const [devices, setDevices] = useState<ManagedDevice[]>([]);
  const [devicesLoading, setDevicesLoading] = useState(true);
  const [editingDeviceId, setEditingDeviceId] = useState<number | null>(null);
  const [deviceForm, setDeviceForm] = useState<DeviceEditForm | null>(null);
  const [savingDevice, setSavingDevice] = useState(false);
  const [scans, setScans] = useState<DiscoveryScan[]>([]);
  const [results, setResults] = useState<DiscoveryResult[]>([]);
  const [stats, setStats] = useState<DiscoveryStats | null>(null);
  const [selectedScanId, setSelectedScanId] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [enrollingId, setEnrollingId] = useState<number | null>(null);
  const [enrollmentForms, setEnrollmentForms] = useState<
    Record<number, EnrollmentForm>
  >({});

  const loadDevices = useCallback(async () => {
    setDevicesLoading(true);
    try {
      const data = await apiRequest<ManagedDevice[]>("/devices?limit=500");
      setDevices(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load managed devices.");
    } finally {
      setDevicesLoading(false);
    }
  }, []);

  const loadDiscovery = useCallback(async () => {
    try {
      const [scanData, resultData, statsData] = await Promise.all([
        apiRequest<DiscoveryScan[]>("/discovery/scans?limit=50"),
        apiRequest<DiscoveryResult[]>("/discovery/results?limit=500"),
        apiRequest<DiscoveryStats>("/discovery/stats"),
      ]);
      setScans(scanData);
      setResults(resultData);
      setStats(statsData);
      setError("");
      return scanData;
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Could not load discovery data.",
      );
      return null;
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadDiscovery();
    void loadDevices();
  }, [loadDiscovery, loadDevices]);

  useEffect(() => {
    const hasActiveScan = scans.some(
      (scan) => scan.status === "pending" || scan.status === "running",
    );
    if (!hasActiveScan) return;

    const interval = window.setInterval(() => {
      void loadDiscovery();
    }, 2000);

    return () => window.clearInterval(interval);
  }, [scans, loadDiscovery]);

  async function startScan(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setStarting(true);
    setError("");
    setNotice("");

    try {
      const scan = await apiRequest<DiscoveryScan>("/discovery/scans", {
        method: "POST",
        body: JSON.stringify({ network_cidr: networkCidr.trim() }),
      });
      setSelectedScanId(scan.id);
      setNotice(`Scan #${scan.id} was queued.`);
      await loadDiscovery();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not start scan.");
    } finally {
      setStarting(false);
    }
  }

  async function enrollResult(
    event: FormEvent<HTMLFormElement>,
    result: DiscoveryResult,
  ) {
    event.preventDefault();
    setEnrollingId(result.id);
    setError("");
    setNotice("");

    const form = enrollmentForms[result.id] ?? {
      name: result.hostname ?? result.ip_address,
      device_type: "",
      notes: "",
    };

    try {
      const device = await apiRequest<{ id: number; name: string }>(
        `/discovery/results/${result.id}/enroll`,
        {
          method: "POST",
          body: JSON.stringify({
            name: form.name.trim() || null,
            device_type: form.device_type.trim() || null,
            notes: form.notes.trim() || null,
          }),
        },
      );
      setNotice(`"${device.name}" is now in managed inventory.`);
      await Promise.all([loadDiscovery(), loadDevices()]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not enroll device.");
    } finally {
      setEnrollingId(null);
    }
  }

  function beginDeviceEdit(device: ManagedDevice) {
    setEditingDeviceId(device.id);
    setDeviceForm({
      name: device.name,
      hostname: device.hostname ?? "",
      ip_address: device.ip_address ?? "",
      device_type: device.device_type ?? "",
      notes: device.notes ?? "",
    });
    setError("");
    setNotice("");
  }

  function cancelDeviceEdit() {
    setEditingDeviceId(null);
    setDeviceForm(null);
  }

  async function saveDevice(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (editingDeviceId === null || deviceForm === null) return;

    setSavingDevice(true);
    setError("");
    setNotice("");

    try {
      const updated = await apiRequest<ManagedDevice>(
        `/devices/${editingDeviceId}`,
        {
          method: "PATCH",
          body: JSON.stringify({
            name: deviceForm.name.trim(),
            hostname: deviceForm.hostname.trim() || null,
            ip_address: deviceForm.ip_address.trim() || null,
            device_type: deviceForm.device_type.trim() || null,
            notes: deviceForm.notes.trim() || null,
          }),
        },
      );

      setDevices((current) =>
        current.map((device) => device.id === updated.id ? updated : device),
      );
      setNotice(`"${updated.name}" was updated.`);
      cancelDeviceEdit();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not update device.");
    } finally {
      setSavingDevice(false);
    }
  }

  const visibleResults = results.filter(
    (result) => selectedScanId === null || result.scan_id === selectedScanId,
  );
  return (
    <div className="discovery-page">
      <div className="page-heading">
        <div>
          <div className="eyebrow">NETWORK INVENTORY</div>
          <h1>Network Discovery</h1>
          <p>
            Find TCP-accessible devices on your network, review their details,
            and choose which ones to add to managed inventory.
          </p>
        </div>
      </div>

      {error && (
        <div className="error-banner" role="alert">
          <span>{error}</span>
          <button type="button" onClick={() => setError("")} aria-label="Dismiss error">
            <X size={16} />
          </button>
        </div>
      )}
      {notice && (
        <div className="discovery-notice" role="status">
          <ShieldCheck size={15} />
          {notice}
          <button type="button" onClick={() => setNotice("")} aria-label="Dismiss message">
            <X size={15} />
          </button>
        </div>
      )}

      <section className="panel managed-devices-panel">
        <div className="panel-heading">
          <div>
            <h2>Managed devices</h2>
            <p>Devices you've enrolled and manage in Network Stats.</p>
          </div>
          <button
            className="secondary-button refresh-button"
            type="button"
            onClick={() => void loadDevices()}
            disabled={devicesLoading}
          >
            <RefreshCw size={14} className={devicesLoading ? "spin" : ""} />
            Refresh
          </button>
        </div>

        {devicesLoading ? (
          <div className="table-state">Loading managed devices...</div>
        ) : devices.length === 0 ? (
          <div className="table-state">
            No managed devices yet. Enroll a device from the discovery results below.
          </div>
        ) : (
          <div className="managed-device-list">
            {devices.map((device) => (
              <article className="managed-device" key={device.id}>
                <div className="managed-device-heading">
                  <div>
                    <strong>{device.name}</strong>
                    <span>
                      {device.ip_address || "No IP address"}
                      {device.hostname ? ` · ${device.hostname}` : ""}
                      {` · Device #${device.id}`}
                    </span>
                  </div>
                  <div className="managed-device-actions">
                    <span className={`discovery-status ${device.is_active ? "completed" : "pending"}`}>
                      {device.is_active ? "Active" : "Inactive"}
                    </span>
                    <button
                      className="secondary-button"
                      type="button"
                      onClick={() => beginDeviceEdit(device)}
                      disabled={savingDevice}
                    >
                      <Pencil size={13} />
                      Edit
                    </button>
                  </div>
                </div>

                <div className="managed-device-details">
                  <div><span>MAC address</span><strong>{device.mac_address || "—"}</strong></div>
                  <div><span>Type</span><strong>{device.device_type || "Unspecified"}</strong></div>
                  <div><span>First seen</span><strong>{formatDate(device.first_seen_at)}</strong></div>
                  <div><span>Last seen</span><strong>{formatDate(device.last_seen_at)}</strong></div>
                  {device.notes && <div className="managed-device-notes"><span>Notes</span><strong>{device.notes}</strong></div>}
                </div>

                {editingDeviceId === device.id && deviceForm && (
                  <form className="target-form managed-device-form" onSubmit={(event) => void saveDevice(event)}>
                    <label>
                      Device name
                      <input required maxLength={150} value={deviceForm.name}
                        onChange={(event) => setDeviceForm({ ...deviceForm, name: event.target.value })} />
                    </label>
                    <label>
                      Hostname
                      <input maxLength={255} value={deviceForm.hostname}
                        onChange={(event) => setDeviceForm({ ...deviceForm, hostname: event.target.value })} />
                    </label>
                    <label>
                      IP address
                      <input value={deviceForm.ip_address}
                        onChange={(event) => setDeviceForm({ ...deviceForm, ip_address: event.target.value })}
                        placeholder="192.168.50.10" />
                    </label>
                    <label>
                      Device type
                      <input maxLength={50} value={deviceForm.device_type}
                        onChange={(event) => setDeviceForm({ ...deviceForm, device_type: event.target.value })}
                        placeholder="router, server, laptop..." />
                    </label>
                    <label>
                      Notes
                      <input value={deviceForm.notes}
                        onChange={(event) => setDeviceForm({ ...deviceForm, notes: event.target.value })} />
                    </label>
                    <div className="form-actions">
                      <button className="secondary-button" type="button" onClick={cancelDeviceEdit} disabled={savingDevice}>
                        Cancel
                      </button>
                      <button className="primary-button" type="submit" disabled={savingDevice || !deviceForm.name.trim()}>
                        {savingDevice ? "Saving..." : "Save changes"}
                      </button>
                    </div>
                  </form>
                )}
              </article>
            ))}
          </div>
        )}
      </section>

      <section className="panel discovery-scan-panel">
        <div className="panel-heading">
          <div>
            <h2>Start a network scan</h2>
            <p>Enter an IPv4 network in CIDR notation. Networks larger than /24 are not supported.</p>
          </div>
          <div className="metric-icon"><Search /></div>
        </div>
        <form className="discovery-scan-form" onSubmit={startScan}>
          <label>
            Network CIDR
            <input
              required
              value={networkCidr}
              onChange={(event) => setNetworkCidr(event.target.value)}
              placeholder="192.168.50.0/24"
              aria-label="Network CIDR"
            />
          </label>
          <button className="primary-button" type="submit" disabled={starting}>
            <Search size={15} />
            {starting ? "Starting..." : "Start scan"}
          </button>
        </form>
        <p className="discovery-method-note">
          Current method: TCP port scanning. Devices that reject all scanned ports may not be detected.
        </p>
      </section>

      <div className="metric-grid discovery-metrics">
        <div className="metric-card">
          <div className="metric-top"><span>Scans recorded</span><div className="metric-icon"><Clock3 /></div></div>
          <div className="metric-value">{stats?.total_scans ?? "—"}</div>
          <div className="metric-description">All scans in the database</div>
        </div>
        <div className="metric-card">
          <div className="metric-top"><span>Active scans</span><div className="metric-icon"><RefreshCw /></div></div>
          <div className="metric-value">{stats?.active_scans ?? "—"}</div>
          <div className="metric-description">Pending or currently running</div>
        </div>
        <div className="metric-card">
          <div className="metric-top"><span>Unique discovered devices</span><div className="metric-icon"><Search /></div></div>
          <div className="metric-value">{stats?.discovered_devices ?? "—"}</div>
          <div className="metric-description">Distinct devices across all scans</div>
        </div>
        <div className="metric-card">
          <div className="metric-top"><span>Enrolled devices</span><div className="metric-icon"><ShieldCheck /></div></div>
          <div className="metric-value">{stats?.enrolled_devices ?? "—"}</div>
          <div className="metric-description">Distinct managed devices seen in discovery</div>
        </div>
      </div>

      <section className="panel discovery-history-panel">
        <div className="panel-heading">
          <div>
            <h2>Scan history</h2>
            <p>Choose a scan to inspect its discovered hosts.</p>
          </div>
          <button
            className="secondary-button refresh-button"
            type="button"
            onClick={() => void loadDiscovery()}
            disabled={loading}
          >
            <RefreshCw size={14} className={loading ? "spin" : ""} />
            Refresh
          </button>
        </div>

        {loading ? (
          <div className="table-state">Loading discovery history...</div>
        ) : scans.length === 0 ? (
          <div className="table-state">No scans yet. Start a scan to discover devices.</div>
        ) : (
          <div className="table-wrapper">
            <table className="targets-table discovery-table">
              <thead>
                <tr>
                  <th>Network</th>
                  <th>Status</th>
                  <th>Devices found</th>
                  <th>Started</th>
                  <th>Finished</th>
                  <th>Details</th>
                </tr>
              </thead>
              <tbody>
                {scans.map((scan) => (
                  <tr key={scan.id}>
                    <td><strong className="target-name">{scan.network_cidr}</strong><span className="target-id">Scan #{scan.id}</span></td>
                    <td><span className={`discovery-status ${scan.status}`}>{scan.status}</span></td>
                    <td>{scan.devices_found}</td>
                    <td>{formatDate(scan.started_at ?? scan.created_at)}</td>
                    <td>{formatDate(scan.finished_at)}</td>
                    <td>
                      <button
                        className="secondary-button"
                        type="button"
                        onClick={() => setSelectedScanId(scan.id)}
                      >
                        View results
                      </button>
                      {scan.error && <div className="discovery-scan-error">{scan.error}</div>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="panel discovery-results-panel">
        <div className="panel-heading">
          <div>
            <h2>Discovered devices</h2>
            <p>
              {selectedScanId === null
                ? "Results from all scans"
                : `Results from scan #${selectedScanId}`}
            </p>
          </div>
          {selectedScanId !== null && (
            <button className="secondary-button" type="button" onClick={() => setSelectedScanId(null)}>
              Show all results
            </button>
          )}
        </div>

        {visibleResults.length === 0 ? (
          <div className="table-state">
            {loading ? "Loading discovered devices..." : "No discovered devices for this selection."}
          </div>
        ) : (
          <div className="discovery-result-list">
            {visibleResults.map((result) => {
              const form = enrollmentForms[result.id] ?? {
                name: result.hostname ?? result.ip_address,
                device_type: "",
                notes: "",
              };

              return (
                <article className="discovery-result" key={result.id}>
                  <div className="discovery-result-heading">
                    <div>
                      <strong>{result.device_name || result.hostname || result.ip_address}</strong>
                      <span>{result.ip_address} · Result #{result.id}</span>
                    </div>
                    {result.device_id !== null ? (
                      <span className="discovery-status completed">Enrolled · Device #{result.device_id}</span>
                    ) : (
                      <span className="discovery-status pending">Not enrolled</span>
                    )}
                  </div>

                  <div className="discovery-result-details">
                    <div><span>Hostname</span><strong>{result.hostname ?? "Not available"}</strong></div>
                    <div><span>MAC address</span><strong className="mono">{result.mac_address ?? "Not available"}</strong></div>
                    <div><span>TCP connect</span><strong>{result.response_time_ms === null ? "—" : `${result.response_time_ms.toFixed(2)} ms`}</strong></div>
                    <div><span>ICMP ping</span><strong>{result.icmp_is_available === true && result.icmp_latency_ms !== null ? `${result.icmp_latency_ms.toFixed(2)} ms` : result.icmp_is_available === false ? "No reply" : "Not measured"}</strong></div>
                    <div><span>Method</span><strong>{result.discovery_method}</strong></div>
                    <div className="discovery-ports"><span>Open TCP ports</span><strong>{result.open_ports.length ? result.open_ports.join(", ") : "None reported"}</strong></div>
                  </div>

                  {result.device_id === null && (
                    <details className="discovery-enroll">
                      <summary>Review and enroll device</summary>
                      <form
                        className="target-form"
                        onSubmit={(event) => void enrollResult(event, result)}
                      >
                        <label>
                          Device name
                          <input
                            required
                            maxLength={150}
                            value={form.name}
                            onChange={(event) =>
                              setEnrollmentForms((current) => ({
                                ...current,
                                [result.id]: { ...form, name: event.target.value },
                              }))
                            }
                          />
                        </label>
                        <label>
                          Device type (optional)
                          <input
                            maxLength={50}
                            value={form.device_type}
                            onChange={(event) =>
                              setEnrollmentForms((current) => ({
                                ...current,
                                [result.id]: { ...form, device_type: event.target.value },
                              }))
                            }
                            placeholder="e.g. router, server, laptop"
                          />
                        </label>
                        <label className="discovery-notes-field">
                          Notes (optional)
                          <input
                            value={form.notes}
                            onChange={(event) =>
                              setEnrollmentForms((current) => ({
                                ...current,
                                [result.id]: { ...form, notes: event.target.value },
                              }))
                            }
                            placeholder="Location, owner, or other notes"
                          />
                        </label>
                        <div className="form-actions">
                          <button className="primary-button" type="submit" disabled={enrollingId !== null}>
                            {enrollingId === result.id ? "Enrolling..." : "Confirm enrollment"}
                          </button>
                        </div>
                      </form>
                    </details>
                  )}
                </article>
              );
            })}
          </div>
        )}
      </section>
    </div>
  );
}

export default DiscoveryPage;
