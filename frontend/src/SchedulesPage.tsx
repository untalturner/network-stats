import { useCallback, useEffect, useState } from "react";
import { Clock3, RefreshCw, ChevronDown, ChevronRight, Activity } from "lucide-react";

type Execution = {
  id: number;
  job_id: number | null;
  job_name: string | null;
  started_at: string;
  finished_at: string | null;
  status: string;
  error: string | null;
};

type ScheduledJob = {
  id: number;
  name: string;
  job_type: string;
  interval_seconds: number | null;
  is_enabled: boolean;
  target_id: number | null;
  created_at: string;
  updated_at: string;
  latest_execution: Execution | null;
};

type SchedulerStatus = {
  is_running: boolean;
  active_jobs: number;
  jobs: { id: string; name: string; next_run_at: string | null }[];
};

async function apiRequest<T>(path: string): Promise<T> {
  const response = await fetch(`/api/v1${path}`);
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

function formatDate(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "—" : date.toLocaleString();
}

function executionLabel(status: string): string {
  return status.charAt(0).toUpperCase() + status.slice(1);
}

export default function SchedulesPage() {
  const [jobs, setJobs] = useState<ScheduledJob[]>([]);
  const [scheduler, setScheduler] = useState<SchedulerStatus | null>(null);
  const [histories, setHistories] = useState<Record<number, Execution[]>>({});
  const [expandedJob, setExpandedJob] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const loadData = useCallback(async () => {
    setLoading(true);
    setError("");

    try {
      const [jobData, schedulerData] = await Promise.all([
        apiRequest<ScheduledJob[]>("/jobs"),
        apiRequest<SchedulerStatus>("/scheduler/status"),
      ]);
      setJobs(jobData);
      setScheduler(schedulerData);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load scheduled jobs.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadData();
  }, [loadData]);

  async function toggleHistory(jobId: number) {
    if (expandedJob === jobId) {
      setExpandedJob(null);
      return;
    }

    setExpandedJob(jobId);

    if (histories[jobId]) return;

    try {
      const history = await apiRequest<Execution[]>(`/jobs/${jobId}/executions?limit=50`);
      setHistories((current) => ({ ...current, [jobId]: history }));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load execution history.");
    }
  }

  const enabledJobs = jobs.filter((job) => job.is_enabled).length;

  return (
    <>
      <div className="page-heading">
        <div>
          <div className="eyebrow">AUTOMATION</div>
          <h1>Schedules &amp; Jobs</h1>
          <p>Monitor scheduled tasks, their next execution and recent run history.</p>
        </div>
        <button className="secondary-button refresh-button" type="button" onClick={() => void loadData()} disabled={loading}>
          <RefreshCw size={14} className={loading ? "spin" : ""} />
          Refresh
        </button>
      </div>

      {error && <div className="error-banner" role="alert">{error}</div>}

      <div className="metric-grid">
        <div className="metric-card">
          <div className="metric-top"><span>Scheduled jobs</span><div className="metric-icon"><Clock3 /></div></div>
          <div className="metric-value">{jobs.length}</div>
          <div className="metric-description">Persisted monitoring jobs</div>
        </div>
        <div className="metric-card">
          <div className="metric-top"><span>Enabled jobs</span><div className="metric-icon"><Activity /></div></div>
          <div className="metric-value">{enabledJobs}</div>
          <div className="metric-description">Configured to run automatically</div>
        </div>
        <div className="metric-card">
          <div className="metric-top"><span>Active scheduler jobs</span><div className="metric-icon"><RefreshCw /></div></div>
          <div className="metric-value">{scheduler?.active_jobs ?? "—"}</div>
          <div className="metric-description">Currently registered with the scheduler</div>
        </div>
        <div className="metric-card">
          <div className="metric-top"><span>Scheduler status</span><div className="metric-icon"><Clock3 /></div></div>
          <div className="metric-value scheduler-status-value">
            {scheduler ? (scheduler.is_running ? "Running" : "Stopped") : "—"}
          </div>
          <div className="metric-description">Background scheduling service</div>
        </div>
      </div>

      <section className="panel schedules-panel">
        <div className="panel-heading">
          <div>
            <h2>Scheduled jobs</h2>
            <p>Jobs are generated from your connectivity monitoring targets.</p>
          </div>
        </div>

        {loading ? (
          <div className="table-state">Loading scheduled jobs...</div>
        ) : jobs.length === 0 ? (
          <div className="table-state">
            <div className="chart-icon"><Clock3 size={23} /></div>
            <strong>No scheduled jobs yet</strong>
            <span>Create a connectivity target to automatically add its monitoring schedule.</span>
          </div>
        ) : (
          <div className="schedules-list">
            {jobs.map((job) => {
              const schedulerJob = scheduler?.jobs.find((item) => item.id === `target-${job.target_id}`);
              const expanded = expandedJob === job.id;
              const history = histories[job.id] ?? [];

              return (
                <article className="schedule-item" key={job.id}>
                  <div className="schedule-main">
                    <div className="schedule-title-group">
                      <div className="schedule-icon"><Clock3 size={17} /></div>
                      <div>
                        <strong>{job.name}</strong>
                        <span>Job #{job.id} · {job.job_type.replaceAll("_", " ")}</span>
                      </div>
                    </div>
                    <span className={`schedule-state ${job.is_enabled ? "enabled" : "disabled"}`}>
                      {job.is_enabled ? "Enabled" : "Disabled"}
                    </span>
                  </div>

                  <div className="schedule-details">
                    <div><span>Interval</span><strong>{job.interval_seconds == null ? "—" : `${job.interval_seconds}s`}</strong></div>
                    <div><span>Next run</span><strong>{formatDate(schedulerJob?.next_run_at)}</strong></div>
                    <div><span>Last execution</span><strong>{formatDate(job.latest_execution?.started_at)}</strong></div>
                    <div>
                      <span>Last result</span>
                      <strong className={`execution-status ${job.latest_execution?.status ?? "unknown"}`}>
                        {job.latest_execution ? executionLabel(job.latest_execution.status) : "No executions"}
                      </strong>
                    </div>
                  </div>

                  {job.latest_execution?.error && (
                    <div className="schedule-error">Latest error: {job.latest_execution.error}</div>
                  )}

                  <button className="schedule-history-toggle" type="button" onClick={() => void toggleHistory(job.id)}>
                    {expanded ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
                    {expanded ? "Hide execution history" : "View execution history"}
                  </button>

                  {expanded && (
                    <div className="schedule-history">
                      {!histories[job.id] ? (
                        <div className="history-empty">Loading execution history...</div>
                      ) : history.length === 0 ? (
                        <div className="history-empty">No executions recorded for this job.</div>
                      ) : (
                        <div className="history-table-wrapper">
                          <table className="history-table">
                            <thead>
                              <tr><th>Started</th><th>Finished</th><th>Status</th><th>Error</th></tr>
                            </thead>
                            <tbody>
                              {history.map((execution) => (
                                <tr key={execution.id}>
                                  <td>{formatDate(execution.started_at)}</td>
                                  <td>{formatDate(execution.finished_at)}</td>
                                  <td><span className={`execution-status ${execution.status}`}>{executionLabel(execution.status)}</span></td>
                                  <td>{execution.error ?? "—"}</td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      )}
                    </div>
                  )}
                </article>
              );
            })}
          </div>
        )}
      </section>
    </>
  );
}
