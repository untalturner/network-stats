import { type FormEvent, useCallback, useEffect, useState } from "react";
import {
  Clock3,
  RefreshCw,
  ChevronDown,
  ChevronRight,
  Activity,
  Pencil,
  X,
  Save,
  Play,
  SkipForward,
  Pause,
} from "lucide-react";

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
  schedule_type: "interval" | "cron";
  cron_expression: string | null;
  timezone: string;
  start_at: string | null;
  end_at: string | null;
  schedule_is_customized: boolean;
  skip_next_run: boolean;
  is_paused: boolean;
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

type ScheduleDraft = {
  schedule_type: "interval" | "cron";
  interval_seconds: string;
  cron_expression: string;
  timezone: string;
  start_at: string;
  end_at: string;
  is_enabled: boolean;
};

const emptyDraft: ScheduleDraft = {
  schedule_type: "interval",
  interval_seconds: "60",
  cron_expression: "",
  timezone: "UTC",
  start_at: "",
  end_at: "",
  is_enabled: true,
};

async function apiRequest<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(`/api/v1${path}`, options);

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

function parseApiDateTime(value: string): Date {
  // Database DateTime values are stored as UTC without a timezone suffix.
  // Explicitly mark those values as UTC before parsing them in the browser.
  const hasTimezone = /(?:Z|[+-]\\d{2}:\\d{2})$/i.test(value);
  return new Date(hasTimezone ? value : `${value}Z`);
}

function formatDate(value: string | null | undefined): string {
  if (!value) return "—";
  const date = parseApiDateTime(value);
  return Number.isNaN(date.getTime()) ? "—" : date.toLocaleString();
}

function toLocalDateTime(value: string | null): string {
  if (!value) return "";
  const date = parseApiDateTime(value);
  if (Number.isNaN(date.getTime())) return "";
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60000);
  return local.toISOString().slice(0, 16);
}

function executionLabel(status: string): string {
  return status.charAt(0).toUpperCase() + status.slice(1);
}

function scheduleDescription(job: ScheduledJob): string {
  if (job.schedule_type === "cron") {
    return job.cron_expression ?? "Invalid cron expression";
  }
  return job.interval_seconds == null
    ? "No interval configured"
    : `Every ${job.interval_seconds} seconds`;
}

export default function SchedulesPage() {
  const [jobs, setJobs] = useState<ScheduledJob[]>([]);
  const [scheduler, setScheduler] = useState<SchedulerStatus | null>(null);
  const [histories, setHistories] = useState<Record<number, Execution[]>>({});
  const [expandedJob, setExpandedJob] = useState<number | null>(null);
  const [editingJobId, setEditingJobId] = useState<number | null>(null);
  const [draft, setDraft] = useState<ScheduleDraft>(emptyDraft);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [actingJobId, setActingJobId] = useState<number | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

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

  function openEditor(job: ScheduledJob) {
    setEditingJobId(job.id);
    setDraft({
      schedule_type: job.schedule_type,
      interval_seconds: String(job.interval_seconds ?? 60),
      cron_expression: job.cron_expression ?? "",
      timezone: job.timezone || "UTC",
      start_at: toLocalDateTime(job.start_at),
      end_at: toLocalDateTime(job.end_at),
      is_enabled: job.is_enabled,
    });
    setError("");
    setNotice("");
  }

  function closeEditor() {
    setEditingJobId(null);
    setDraft(emptyDraft);
  }

  async function saveSchedule(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    if (editingJobId === null || saving) return;

    if (draft.schedule_type === "cron" && !draft.cron_expression.trim()) {
      setError("Enter a five-field cron expression.");
      return;
    }

    const payload = {
      schedule_type: draft.schedule_type,
      interval_seconds:
        draft.schedule_type === "interval"
          ? Number(draft.interval_seconds)
          : null,
      cron_expression:
        draft.schedule_type === "cron"
          ? draft.cron_expression.trim()
          : null,
      timezone: draft.timezone.trim(),
      start_at: draft.start_at
        ? new Date(draft.start_at).toISOString()
        : null,
      end_at: draft.end_at
        ? new Date(draft.end_at).toISOString()
        : null,
      is_enabled: draft.is_enabled,
    };

    setSaving(true);
    setError("");
    setNotice("");

    try {
      await apiRequest<ScheduledJob>(
        `/jobs/${editingJobId}/schedule`,
        {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        },
      );

      closeEditor();
      await loadData();
      setNotice("Schedule saved successfully.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save schedule.");
    } finally {
      setSaving(false);
    }
  }

  async function performJobAction(
    jobId: number,
    action: "run" | "skip-next" | "pause" | "resume",
  ) {
    if (actingJobId !== null) return;

    setActingJobId(jobId);
    setError("");
    setNotice("");

    try {
      const result = await apiRequest<{ job_id: number; message: string }>(
        `/jobs/${jobId}/${action}`,
        { method: "POST" },
      );

      setNotice(result.message);
      await loadData();

      if (expandedJob === jobId) {
        const history = await apiRequest<Execution[]>(
          `/jobs/${jobId}/executions?limit=50`,
        );
        setHistories((current) => ({ ...current, [jobId]: history }));
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not perform job action.");
    } finally {
      setActingJobId(null);
    }
  }

  async function toggleHistory(jobId: number) {
    if (expandedJob === jobId) {
      setExpandedJob(null);
      return;
    }

    setExpandedJob(jobId);

    if (histories[jobId]) return;

    try {
      const history = await apiRequest<Execution[]>(
        `/jobs/${jobId}/executions?limit=50`,
      );
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
          <p>Configure monitoring schedules, inspect upcoming runs and review execution history.</p>
        </div>
        <button
          className="secondary-button refresh-button"
          type="button"
          onClick={() => void loadData()}
          disabled={loading}
        >
          <RefreshCw size={14} className={loading ? "spin" : ""} />
          Refresh
        </button>
      </div>

      {error && <div className="error-banner" role="alert">{error}</div>}
      {notice && (
        <div className="discovery-notice" role="status">
          <span>{notice}</span>
          <button type="button" onClick={() => setNotice("")} aria-label="Dismiss notification">
            <X size={15} />
          </button>
        </div>
      )}

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
            <p>Uncustomized jobs inherit their interval from the associated monitoring target.</p>
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
              const schedulerJob = scheduler?.jobs.find(
                (item) => item.id === `target-${job.target_id}`,
              );
              const expanded = expandedJob === job.id;
              const editing = editingJobId === job.id;
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
                    <span className={`schedule-state ${job.is_paused ? "paused" : job.is_enabled ? "enabled" : "disabled"}`}>
                      {job.is_paused ? "Paused" : job.is_enabled ? "Enabled" : "Disabled"}
                    </span>
                  </div>

                  <div className="schedule-details">
                    <div><span>Schedule</span><strong>{scheduleDescription(job)}</strong></div>
                    <div><span>Timezone</span><strong>{job.timezone}</strong></div>
                    <div><span>Next run</span><strong>{formatDate(schedulerJob?.next_run_at)}</strong></div>
                    <div><span>Last execution</span><strong>{formatDate(job.latest_execution?.started_at)}</strong></div>
                    <div>
                      <span>Last result</span>
                      <strong className={`execution-status ${job.latest_execution?.status ?? "unknown"}`}>
                        {job.latest_execution ? executionLabel(job.latest_execution.status) : "No executions"}
                      </strong>
                    </div>
                    <div>
                      <span>Configuration</span>
                      <strong>{job.schedule_is_customized ? "Custom schedule" : "Inherited from target"}</strong>
                    </div>
                    <div>
                      <span>Skip next</span>
                      <strong>{job.skip_next_run ? "Armed" : "No"}</strong>
                    </div>
                  </div>

                  {(job.start_at || job.end_at) && (
                    <div className="schedule-date-range">
                      {job.start_at && <span>Starts: {formatDate(job.start_at)}</span>}
                      {job.end_at && <span>Ends: {formatDate(job.end_at)}</span>}
                    </div>
                  )}

                  {job.latest_execution?.error && (
                    <div className="schedule-error">Latest error: {job.latest_execution.error}</div>
                  )}

                  <div className="schedule-actions">
                    <button
                      className="secondary-button schedule-control-button"
                      type="button"
                      onClick={() => void performJobAction(job.id, job.is_paused ? "resume" : "pause")}
                      disabled={actingJobId !== null || (!job.is_paused && !job.is_enabled)}
                    >
                      {job.is_paused ? <Play size={14} /> : <Pause size={14} />}
                      {job.is_paused ? "Resume" : "Pause"}
                    </button>

                    <button
                      className="secondary-button schedule-control-button"
                      type="button"
                      onClick={() => void performJobAction(job.id, "run")}
                      disabled={!job.is_enabled || actingJobId !== null || !scheduler?.is_running}
                      title={!scheduler?.is_running ? "Scheduler is stopped" : "Queue an immediate run"}
                    >
                      <Play size={14} />
                      {actingJobId === job.id ? "Working..." : "Run now"}
                    </button>

                    <button
                      className="secondary-button schedule-control-button"
                      type="button"
                      onClick={() => void performJobAction(job.id, "skip-next")}
                      disabled={actingJobId !== null || job.skip_next_run}
                      title={job.skip_next_run ? "Next scheduled run is already marked to be skipped" : "Skip the next scheduled execution"}
                    >
                      <SkipForward size={14} />
                      {job.skip_next_run ? "Skip armed" : "Skip next"}
                    </button>

                    <button
                      className="secondary-button"
                      type="button"
                      onClick={() => editing ? closeEditor() : openEditor(job)}
                      disabled={saving}
                    >
                      {editing ? <X size={14} /> : <Pencil size={14} />}
                      {editing ? "Close editor" : "Edit schedule"}
                    </button>

                    <button
                      className="schedule-history-toggle"
                      type="button"
                      onClick={() => void toggleHistory(job.id)}
                    >
                      {expanded ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
                      {expanded ? "Hide execution history" : "View execution history"}
                    </button>
                  </div>

                  {editing && (
                    <form className="schedule-editor target-form" onSubmit={saveSchedule}>
                      <div className="schedule-editor-heading">
                        <div>
                          <h3>Edit schedule</h3>
                          <p>Changes are saved to this job, independently of its target interval.</p>
                        </div>
                      </div>

                      <label>
                        Schedule type
                        <select
                          value={draft.schedule_type}
                          onChange={(event) =>
                            setDraft({
                              ...draft,
                              schedule_type: event.target.value as "interval" | "cron",
                            })
                          }
                        >
                          <option value="interval">Repeat at an interval</option>
                          <option value="cron">Custom cron expression</option>
                        </select>
                      </label>

                      {draft.schedule_type === "interval" ? (
                        <label>
                          Interval (seconds)
                          <input
                            type="number"
                            min={5}
                            max={86400}
                            required
                            value={draft.interval_seconds}
                            onChange={(event) =>
                              setDraft({ ...draft, interval_seconds: event.target.value })
                            }
                          />
                        </label>
                      ) : (
                        <label>
                          Cron expression
                          <input
                            type="text"
                            required
                            maxLength={120}
                            value={draft.cron_expression}
                            onChange={(event) =>
                              setDraft({ ...draft, cron_expression: event.target.value })
                            }
                            placeholder="0 9 * * mon-fri"
                          />
                          <span className="schedule-field-hint">
                            Five fields: minute hour day month day-of-week.
                          </span>
                        </label>
                      )}

                      <label>
                        Timezone (IANA)
                        <input
                          type="text"
                          required
                          maxLength={64}
                          value={draft.timezone}
                          onChange={(event) =>
                            setDraft({ ...draft, timezone: event.target.value })
                          }
                          placeholder="Europe/Madrid"
                        />
                      </label>

                      <label>
                        Start date and time (your local time, optional)
                        <input
                          type="datetime-local"
                          value={draft.start_at}
                          onChange={(event) =>
                            setDraft({ ...draft, start_at: event.target.value })
                          }
                        />
                      </label>

                      <label>
                        End date and time (your local time, optional)
                        <input
                          type="datetime-local"
                          value={draft.end_at}
                          onChange={(event) =>
                            setDraft({ ...draft, end_at: event.target.value })
                          }
                        />
                      </label>

                      <label className="form-checkbox">
                        <input
                          type="checkbox"
                          checked={draft.is_enabled}
                          onChange={(event) =>
                            setDraft({ ...draft, is_enabled: event.target.checked })
                          }
                        />
                        Enable this scheduled job
                      </label>

                      <div className="schedule-editor-note">
                        A disabled monitoring target still prevents its connectivity job from running, even when this schedule is enabled.
                      </div>

                      <div className="form-actions">
                        <button
                          className="secondary-button"
                          type="button"
                          onClick={closeEditor}
                          disabled={saving}
                        >
                          Cancel
                        </button>
                        <button className="primary-button" type="submit" disabled={saving}>
                          <Save size={14} />
                          {saving ? "Saving..." : "Save schedule"}
                        </button>
                      </div>
                    </form>
                  )}

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
