'use client';

import { useState, useEffect, useCallback } from 'react';
import {
  Clock,
  Play,
  Trash2,
  ToggleLeft,
  ToggleRight,
  Plus,
  Edit2,
  X,
  CheckCircle,
  XCircle,
  Loader2,
  ChevronDown,
  ChevronUp,
  RefreshCw,
  Terminal,
  Activity,
} from 'lucide-react';
import { AppLayout } from '@/components/layout/app-layout';
import { useAuthStore } from '@/stores/auth-store';
import { translations } from '@/lib/translations';

const t = translations.cron;

// ─── Types ───────────────────────────────────────────────

type ActionType = 'run_skill' | 'run_routine' | 'analyze_patterns' | 'custom_command' | 'run_swarm_template';
type JobStatus = 'pending' | 'success' | 'error' | 'running';

interface CronJob {
  id: number;
  name: string;
  description: string;
  cron_expr: string;
  action_type: ActionType;
  action_payload: string; // JSON string
  is_enabled: number;
  last_run: string | null;
  next_run: string | null;
  run_count: number;
  last_status: JobStatus;
  last_output: string | null;
  created_at: string;
}

interface CronRun {
  id: number;
  job_id: number;
  job_name: string;
  started_at: string;
  finished_at: string | null;
  status: 'running' | 'success' | 'error';
  output: string | null;
  error: string | null;
  triggered_by: 'scheduler' | 'manual';
}

interface CronStatus {
  running: boolean;
  job_count: number;
  enabled_count: number;
  next_job_name: string | null;
  next_job_at: string | null;
}

interface JobFormData {
  name: string;
  description: string;
  cron_expr: string;
  action_type: ActionType;
  action_payload: Record<string, unknown>;
  is_enabled: boolean;
}

// ─── Cron Expression Helpers ─────────────────────────────

const PRESETS: { label: string; expr: string }[] = [
  { label: t.presets.everyMinute,   expr: '*/5 * * * *' },
  { label: t.presets.everyHour,     expr: '0 * * * *' },
  { label: t.presets.everyDay,      expr: '0 0 * * *' },
  { label: t.presets.everyWeekday,  expr: '0 9 * * 1-5' },
  { label: t.presets.everyMonday,   expr: '0 8 * * 1' },
];

function describeCron(expr: string): string {
  const shortcuts: Record<string, string> = {
    '@hourly': 'Every hour',
    '@daily': 'Every day at midnight',
    '@weekly': 'Every week on Sunday at midnight',
    '@monthly': 'Every month on the 1st at midnight',
  };
  if (shortcuts[expr.trim()]) return shortcuts[expr.trim()];
  const parts = expr.trim().split(/\s+/);
  if (parts.length !== 5) return expr;
  const [min, hour, dom, , dow] = parts;
  const days: Record<string, string> = {
    '0': 'Sun', '1': 'Mon', '2': 'Tue', '3': 'Wed',
    '4': 'Thu', '5': 'Fri', '6': 'Sat',
  };
  const dowLabel = dow === '*' ? 'every day' : `on ${dow.split(',').map(d => days[d] || d).join(', ')}`;
  const timeLabel = (min === '*' && hour === '*') ? 'every minute'
    : (min === '0' && hour === '*') ? 'every hour'
    : (min.startsWith('*/') && hour === '*') ? `every ${min.slice(2)} min`
    : `at ${hour.padStart(2, '0')}:${min.padStart(2, '0')}`;
  const domLabel = dom === '*' ? '' : ` on day ${dom}`;
  return `${timeLabel}${domLabel} ${dowLabel}`;
}

// ─── Misc Helpers ─────────────────────────────────────────

function formatDate(iso: string | null): string {
  if (!iso) return t.never;
  try {
    return new Date(iso).toLocaleString(undefined, {
      day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit',
    });
  } catch { return t.never; }
}

function parsePayload(raw: string | undefined): Record<string, unknown> {
  if (!raw) return {};
  try { return JSON.parse(raw); } catch { return {}; }
}

// ─── Status dot helper ────────────────────────────────────

function StatusDot({ status }: { status: JobStatus }) {
  if (status === 'success') return <span className="dot dot-ok" />;
  if (status === 'error')   return <span className="dot dot-err" />;
  if (status === 'running') return <span className="dot dot-accent acm-pulse" />;
  return <span className="dot dot-idle" />;
}

// ─── Action Payload Editor ────────────────────────────────

function PayloadEditor({
  actionType,
  payload,
  onChange,
}: {
  actionType: ActionType;
  payload: Record<string, unknown>;
  onChange: (p: Record<string, unknown>) => void;
}) {
  switch (actionType) {
    case 'run_skill':
      return (
        <div>
          <label className="label block mb-2">{t.skillName}</label>
          <input
            type="text"
            className="acm-input w-full"
            placeholder="e.g. daily_summary"
            value={String(payload.skill_name ?? '')}
            onChange={e => onChange({ ...payload, skill_name: e.target.value })}
          />
        </div>
      );
    case 'run_routine':
      return (
        <div>
          <label className="label block mb-2">{t.routineId}</label>
          <input
            type="number"
            className="acm-input w-full"
            placeholder="Routine ID"
            value={String(payload.routine_id ?? '')}
            onChange={e => onChange({ ...payload, routine_id: parseInt(e.target.value) || 0 })}
          />
        </div>
      );
    case 'analyze_patterns':
      return (
        <p className="text-[12px] text-[var(--acm-fg-4)] italic">
          No configuration needed — runs the pattern analyzer automatically.
        </p>
      );
    case 'custom_command':
      return (
        <div className="space-y-3">
          <div>
            <label className="label block mb-2">{t.command}</label>
            <textarea
              rows={2}
              className="mono w-full bg-[var(--acm-card)] border-b border-[var(--acm-border)] text-[var(--acm-fg)] outline-none focus:border-b-[var(--acm-accent)] px-0 py-2 text-[13px] resize-none"
              placeholder="e.g. python /path/to/script.py"
              value={String(payload.command ?? '')}
              onChange={e => onChange({ ...payload, command: e.target.value })}
            />
          </div>
          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="checkbox"
              className="rounded border-[var(--acm-border)]"
              checked={payload.shell !== false}
              onChange={e => onChange({ ...payload, shell: e.target.checked })}
            />
            <span className="text-[12px] text-[var(--acm-fg-3)]">{t.shellMode}</span>
          </label>
        </div>
      );
    case 'run_swarm_template':
      return (
        <div className="space-y-3">
          <div>
            <label className="label block mb-2">Template ID</label>
            <input
              type="number"
              className="acm-input w-full"
              placeholder="Swarm template ID (create one in the API)"
              value={String(payload.template_id ?? '')}
              onChange={e => onChange({ ...payload, template_id: parseInt(e.target.value) || 0 })}
            />
          </div>
          <div>
            <label className="label block mb-2">Goal Override (optional)</label>
            <textarea
              rows={2}
              className="w-full bg-[var(--acm-card)] border-b border-[var(--acm-border)] text-[var(--acm-fg)] outline-none focus:border-b-[var(--acm-accent)] px-0 py-2 text-[13px] resize-none"
              placeholder="Leave empty to use template goal. Use {date} placeholder."
              value={String(payload.goal_override ?? '')}
              onChange={e => onChange({ ...payload, goal_override: e.target.value })}
            />
          </div>
          <p className="text-[12px] text-[var(--acm-fg-4)]">
            Creates a new swarm instance from the template every time this job fires.
            Use the <code className="mono bg-[var(--acm-elev)] px-1 rounded text-[var(--acm-fg-3)]">/api/swarm-templates</code> endpoint to manage templates.
          </p>
        </div>
      );
  }
}

// ─── Job Form Modal ───────────────────────────────────────

function JobModal({
  job,
  onClose,
  onSave,
}: {
  job: CronJob | null;
  onClose: () => void;
  onSave: () => void;
}) {
  const token = useAuthStore(s => s.token);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [form, setForm] = useState<JobFormData>({
    name: job?.name ?? '',
    description: job?.description ?? '',
    cron_expr: job?.cron_expr ?? '0 9 * * 1-5',
    action_type: job?.action_type ?? 'analyze_patterns',
    action_payload: parsePayload(job?.action_payload),
    is_enabled: job ? Boolean(job.is_enabled) : true,
  });

  const headers = {
    'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };

  async function handleSave() {
    if (!form.name.trim()) { setError('Name is required'); return; }
    if (!form.cron_expr.trim()) { setError('Cron expression is required'); return; }
    setSaving(true);
    setError('');
    try {
      const url = job ? `/api/cron/jobs/${job.id}` : '/api/cron/jobs';
      const method = job ? 'PUT' : 'POST';
      const res = await fetch(url, {
        method,
        headers,
        body: JSON.stringify({
          ...form,
          action_payload: form.action_payload,
        }),
      });
      if (!res.ok) {
        const d = await res.json().catch(() => ({}));
        throw new Error(d.detail || `HTTP ${res.status}`);
      }
      onSave();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Save failed');
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-black/70 backdrop-blur-sm flex items-center justify-center z-50 p-4">
      <div
        className="w-full max-w-lg shadow-2xl flex flex-col"
        style={{ background: 'var(--acm-base)', border: '1px solid var(--acm-border)', borderRadius: '12px' }}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4" style={{ borderBottom: '1px solid var(--acm-border)' }}>
          <h2 className="text-[15px] font-semibold text-[var(--acm-fg)]">
            {job ? t.editJob : t.newJob}
          </h2>
          <button
            onClick={onClose}
            className="p-1.5 rounded text-[var(--acm-fg-4)] hover:text-[var(--acm-fg)] transition-colors"
          >
            <X size={16} />
          </button>
        </div>

        {/* Body */}
        <div className="p-5 space-y-5 max-h-[70vh] overflow-y-auto acm-scroll">
          {error && (
            <div className="flex items-center gap-2 px-3 py-2 rounded text-[12px] text-[var(--acm-err)]"
              style={{ background: 'color-mix(in srgb, var(--acm-err) 10%, transparent)', border: '1px solid color-mix(in srgb, var(--acm-err) 30%, transparent)' }}>
              <span className="dot dot-err shrink-0" />
              {error}
            </div>
          )}

          {/* Name */}
          <div>
            <label className="label block mb-2">{t.jobName}</label>
            <input
              type="text"
              className="acm-input w-full"
              placeholder="e.g. Daily Analysis"
              value={form.name}
              onChange={e => setForm({ ...form, name: e.target.value })}
            />
          </div>

          {/* Description */}
          <div>
            <label className="label block mb-2">{t.description}</label>
            <input
              type="text"
              className="acm-input w-full"
              placeholder="Optional description"
              value={form.description}
              onChange={e => setForm({ ...form, description: e.target.value })}
            />
          </div>

          {/* Cron Expression */}
          <div>
            <label className="label block mb-2">
              {t.cronExpression}
              <span className="ml-2 mono text-[var(--acm-fg-4)] text-[10px] normal-case tracking-normal">{t.cronHint}</span>
            </label>
            <input
              type="text"
              className="acm-input mono w-full"
              placeholder="0 9 * * 1-5"
              value={form.cron_expr}
              onChange={e => setForm({ ...form, cron_expr: e.target.value })}
            />
            <p className="mt-1.5 text-[11px] text-[var(--acm-accent)] italic opacity-80">{describeCron(form.cron_expr)}</p>
            {/* Presets */}
            <div className="mt-2 flex flex-wrap gap-1.5">
              {PRESETS.map(p => (
                <button
                  key={p.expr}
                  onClick={() => setForm({ ...form, cron_expr: p.expr })}
                  className="btn-secondary px-2 py-0.5 text-[11px]"
                >
                  {p.label}
                </button>
              ))}
            </div>
          </div>

          {/* Action Type */}
          <div>
            <label className="label block mb-2">{t.actionType}</label>
            <select
              className="bg-[var(--acm-card)] border-b border-[var(--acm-border)] text-[var(--acm-fg)] outline-none focus:border-b-[var(--acm-accent)] px-0 py-2 appearance-none w-full text-[14px]"
              value={form.action_type}
              onChange={e => setForm({ ...form, action_type: e.target.value as ActionType, action_payload: {} })}
            >
              {(Object.keys(t.actionTypes) as ActionType[]).map(k => (
                <option key={k} value={k}>{t.actionTypes[k]}</option>
              ))}
            </select>
          </div>

          {/* Payload */}
          <div>
            <label className="label block mb-2">{t.actionPayload}</label>
            <PayloadEditor
              actionType={form.action_type}
              payload={form.action_payload}
              onChange={p => setForm({ ...form, action_payload: p })}
            />
          </div>

          {/* Enabled toggle */}
          <label className="flex items-center gap-3 cursor-pointer">
            <div
              onClick={() => setForm({ ...form, is_enabled: !form.is_enabled })}
              className={`w-9 h-[18px] rounded-full transition-colors relative shrink-0 ${form.is_enabled ? 'bg-[var(--acm-accent)]' : 'bg-[var(--acm-elev)]'}`}
              style={{ border: '1px solid var(--acm-border)' }}
            >
              <span className={`absolute top-[2px] w-[14px] h-[14px] rounded-full bg-white shadow transition-transform ${form.is_enabled ? 'translate-x-[18px]' : 'translate-x-[2px]'}`} />
            </div>
            <span className="text-[13px] text-[var(--acm-fg-2)]">{form.is_enabled ? t.enabled : 'Disabled'}</span>
          </label>
        </div>

        {/* Footer */}
        <div className="flex justify-end gap-2 px-5 py-4" style={{ borderTop: '1px solid var(--acm-border)' }}>
          <button
            onClick={onClose}
            className="px-4 py-2 text-[13px] text-[var(--acm-fg-3)] hover:text-[var(--acm-fg)] transition-colors rounded"
          >
            {translations.common.cancel}
          </button>
          <button
            onClick={handleSave}
            disabled={saving}
            className="btn-primary flex items-center gap-2 px-4 py-2 text-[13px] disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {saving && <Loader2 size={13} className="animate-spin" />}
            {saving ? 'Saving...' : translations.common.save}
          </button>
        </div>
      </div>
    </div>
  );
}

// ─── Cron Job Card ────────────────────────────────────────

function CronJobCard({
  job,
  onEdit,
  onDelete,
  onToggle,
  onTrigger,
}: {
  job: CronJob;
  onEdit: (j: CronJob) => void;
  onDelete: (id: number) => void;
  onToggle: (id: number) => void;
  onTrigger: (id: number) => void;
}) {
  const [triggering, setTriggering] = useState(false);
  const [expanded, setExpanded] = useState(false);

  async function handleTrigger() {
    setTriggering(true);
    await onTrigger(job.id);
    setTriggering(false);
  }

  const payload = parsePayload(job.action_payload);
  const payloadSummary = job.action_type === 'run_skill'
    ? String(payload.skill_name ?? '')
    : job.action_type === 'run_routine'
    ? `ID ${payload.routine_id ?? ''}`
    : job.action_type === 'custom_command'
    ? String(payload.command ?? '').slice(0, 40)
    : '';

  const status = job.last_status ?? 'pending';

  return (
    <div className={`acm-card p-4 space-y-3 transition-opacity ${!job.is_enabled ? 'opacity-50' : ''}`}>
      {/* Top row */}
      <div className="flex items-start gap-3">
        <div className="mt-0.5 p-2 rounded" style={{ background: 'var(--acm-elev)' }}>
          <Clock size={15} className={job.is_enabled ? 'text-[var(--acm-accent)]' : 'text-[var(--acm-fg-4)]'} />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <h3 className="text-[14px] font-semibold text-[var(--acm-fg)] truncate">{job.name}</h3>
            {/* Action type badge */}
            <span className="mono text-[10px] text-[var(--acm-fg-4)] px-[6px] py-[2px] border border-[var(--acm-border)] rounded-[3px] tracking-[0.06em] uppercase">
              {t.actionTypes[job.action_type]}
            </span>
            {/* Status */}
            <span className="flex items-center gap-1.5">
              <StatusDot status={status} />
              <span className="mono text-[10px] text-[var(--acm-fg-3)] uppercase tracking-[0.08em]">
                {t.status[status] ?? status}
              </span>
            </span>
          </div>
          {job.description && (
            <p className="text-[12px] text-[var(--acm-fg-3)] mt-0.5 truncate">{job.description}</p>
          )}
          <div className="flex items-center gap-2 mt-1 flex-wrap">
            <code className="mono text-[12px] text-[var(--acm-accent)] opacity-90">{job.cron_expr}</code>
            <span className="text-[11px] text-[var(--acm-fg-4)] italic">{describeCron(job.cron_expr)}</span>
          </div>
          {payloadSummary && (
            <p className="mono text-[11px] text-[var(--acm-fg-4)] mt-0.5 truncate">{payloadSummary}</p>
          )}
        </div>
        {/* Actions */}
        <div className="flex items-center gap-0.5 shrink-0">
          <button
            onClick={() => onToggle(job.id)}
            title={job.is_enabled ? 'Disable' : 'Enable'}
            className="p-1.5 rounded text-[var(--acm-fg-4)] hover:text-[var(--acm-accent)] transition-colors"
          >
            {job.is_enabled
              ? <ToggleRight size={18} className="text-[var(--acm-accent)]" />
              : <ToggleLeft size={18} />}
          </button>
          <button
            onClick={handleTrigger}
            disabled={triggering}
            title={t.triggerNow}
            className="p-1.5 rounded text-[var(--acm-fg-4)] hover:text-[var(--acm-accent)] transition-colors disabled:opacity-40"
          >
            {triggering ? <Loader2 size={15} className="animate-spin" /> : <Play size={15} />}
          </button>
          <button
            onClick={() => onEdit(job)}
            title="Edit"
            className="p-1.5 rounded text-[var(--acm-fg-4)] hover:text-[var(--acm-fg)] transition-colors"
          >
            <Edit2 size={15} />
          </button>
          <button
            onClick={() => onDelete(job.id)}
            title="Delete"
            className="p-1.5 rounded text-[var(--acm-fg-4)] hover:text-[var(--acm-err)] transition-colors"
          >
            <Trash2 size={15} />
          </button>
        </div>
      </div>

      {/* Stats row */}
      <div
        className="flex items-center gap-4 text-[11px] text-[var(--acm-fg-4)] pt-2"
        style={{ borderTop: '1px solid var(--acm-border)' }}
      >
        <span>{t.lastRun}: <span className="mono text-[var(--acm-fg-3)]">{formatDate(job.last_run)}</span></span>
        <span>{t.nextRun}: <span className="mono text-[var(--acm-fg-3)]">{formatDate(job.next_run)}</span></span>
        <span>{t.runCount}: <span className="text-[var(--acm-fg-3)]">{job.run_count}</span></span>
        {job.last_output && (
          <button
            onClick={() => setExpanded(!expanded)}
            className="ml-auto flex items-center gap-1 text-[var(--acm-fg-4)] hover:text-[var(--acm-fg-2)] transition-colors"
          >
            Last output {expanded ? <ChevronUp size={11} /> : <ChevronDown size={11} />}
          </button>
        )}
      </div>

      {expanded && job.last_output && (
        <pre
          className="mono text-[11px] text-[var(--acm-fg-3)] max-h-32 overflow-auto whitespace-pre-wrap rounded p-3 acm-scroll"
          style={{ background: 'var(--acm-elev)', border: '1px solid var(--acm-border)' }}
        >
          {job.last_output}
        </pre>
      )}
    </div>
  );
}

// ─── Run History Panel ────────────────────────────────────

function RunHistory({ runs, loading }: { runs: CronRun[]; loading: boolean }) {
  if (loading) {
    return (
      <div className="flex justify-center py-8">
        <Loader2 size={18} className="animate-spin text-[var(--acm-fg-4)]" />
      </div>
    );
  }
  if (!runs.length) {
    return <p className="text-center text-[var(--acm-fg-4)] text-[13px] py-6">No runs recorded yet.</p>;
  }
  return (
    <div className="space-y-0">
      {runs.map(run => (
        <div
          key={run.id}
          className="flex items-start gap-3 py-2.5 px-3 rounded transition-colors hover:bg-[var(--acm-elev)]"
          style={{ borderLeft: '2px solid transparent' }}
          onMouseEnter={e => (e.currentTarget.style.borderLeftColor = 'var(--acm-border-strong)')}
          onMouseLeave={e => (e.currentTarget.style.borderLeftColor = 'transparent')}
        >
          <div className="mt-0.5 shrink-0">
            {run.status === 'success' ? (
              <CheckCircle size={13} className="text-[var(--acm-ok)]" />
            ) : run.status === 'error' ? (
              <XCircle size={13} className="text-[var(--acm-err)]" />
            ) : (
              <Loader2 size={13} className="animate-spin text-[var(--acm-accent)]" />
            )}
          </div>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-[12px] font-medium text-[var(--acm-fg-2)]">{run.job_name}</span>
              {run.triggered_by === 'manual' && (
                <span className="mono text-[10px] text-[var(--acm-fg-4)] px-[5px] py-[1px] border border-[var(--acm-border)] rounded-[3px] uppercase tracking-[0.06em]">
                  manual
                </span>
              )}
            </div>
            <p className="mono text-[11px] text-[var(--acm-fg-4)]">{formatDate(run.started_at)}</p>
            {(run.output || run.error) && (
              <p className="mono text-[11px] text-[var(--acm-fg-3)] truncate mt-0.5">
                {run.error || run.output}
              </p>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}

// ─── Page ────────────────────────────────────────────────

export default function CronPage() {
  const token = useAuthStore(s => s.token);
  const [jobs, setJobs] = useState<CronJob[]>([]);
  const [runs, setRuns] = useState<CronRun[]>([]);
  const [status, setStatus] = useState<CronStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [runsLoading, setRunsLoading] = useState(true);
  const [showHistory, setShowHistory] = useState(false);
  const [modalJob, setModalJob] = useState<CronJob | null>(null);
  const [showModal, setShowModal] = useState(false);

  const headers: Record<string, string> = token ? { Authorization: `Bearer ${token}` } : {};

  const fetchJobs = useCallback(async () => {
    try {
      const [jobsRes, statusRes] = await Promise.all([
        fetch('/api/cron/jobs', { headers }),
        fetch('/api/cron/status', { headers }),
      ]);
      if (jobsRes.ok) {
        const d = await jobsRes.json();
        setJobs(Array.isArray(d) ? d : (d.jobs ?? []));
      }
      if (statusRes.ok) {
        setStatus(await statusRes.json());
      }
    } catch { /* ignore */ }
    finally { setLoading(false); }
  }, [token]);

  const fetchRuns = useCallback(async () => {
    setRunsLoading(true);
    try {
      const res = await fetch('/api/cron/runs?limit=50', { headers });
      if (res.ok) {
        const d = await res.json();
        setRuns(d.runs ?? []);
      }
    } catch { /* ignore */ }
    finally { setRunsLoading(false); }
  }, [token]);

  useEffect(() => { fetchJobs(); }, [fetchJobs]);
  useEffect(() => {
    if (showHistory) fetchRuns();
  }, [showHistory, fetchRuns]);

  async function handleDelete(id: number) {
    if (!confirm(t.deleteConfirm)) return;
    await fetch(`/api/cron/jobs/${id}`, { method: 'DELETE', headers });
    fetchJobs();
  }

  async function handleToggle(id: number) {
    await fetch(`/api/cron/jobs/${id}/toggle`, { method: 'POST', headers });
    fetchJobs();
  }

  async function handleTrigger(id: number) {
    await fetch(`/api/cron/jobs/${id}/trigger`, { method: 'POST', headers });
    fetchJobs();
    if (showHistory) fetchRuns();
  }

  function openEdit(job: CronJob) { setModalJob(job); setShowModal(true); }
  function openNew() { setModalJob(null); setShowModal(true); }

  const enabledCount = jobs.filter(j => j.is_enabled).length;

  return (
    <AppLayout>
      <div className="flex flex-col min-h-0 p-6 space-y-6">

        {/* Header */}
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div>
            <span className="acm-breadcrumb">/ cron</span>
            <h1 className="text-[22px] font-semibold tracking-[-0.01em] text-[var(--acm-fg)]">{t.title}</h1>
            <p className="text-[12px] text-[var(--acm-fg-3)] mt-1">
              {jobs.length} jobs · {enabledCount} enabled
            </p>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={fetchJobs}
              title="Refresh"
              className="p-2 rounded text-[var(--acm-fg-4)] hover:text-[var(--acm-fg)] transition-colors"
              style={{ border: '1px solid var(--acm-border)' }}
            >
              <RefreshCw size={15} />
            </button>
            <button
              onClick={openNew}
              className="btn-primary flex items-center gap-2 px-4 py-2 text-[13px]"
            >
              <Plus size={14} />
              {t.newJob}
            </button>
          </div>
        </div>

        {/* Stats bar */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <div className="acm-card p-4">
            <span className="label block mb-2">{t.totalJobs}</span>
            <span className="text-[24px] font-semibold text-[var(--acm-fg)]">{jobs.length}</span>
          </div>
          <div className="acm-card p-4">
            <span className="label block mb-2">{t.enabledJobs}</span>
            <span className="text-[24px] font-semibold text-[var(--acm-fg)]">{enabledCount}</span>
          </div>
          <div className="acm-card p-4">
            <span className="label block mb-2">Scheduler</span>
            <div className="flex items-center gap-2 mt-1">
              {status?.running
                ? <span className="dot dot-ok acm-pulse" />
                : <span className="dot dot-err" />}
              <span className="text-[13px] font-medium text-[var(--acm-fg-2)]">
                {status?.running ? t.schedulerRunning : t.schedulerStopped}
              </span>
            </div>
          </div>
          <div className="acm-card p-4">
            <span className="label block mb-2">{t.nextExecution}</span>
            {status?.next_job_name ? (
              <>
                <p className="text-[12px] font-medium text-[var(--acm-accent)] mt-1 truncate">{status.next_job_name}</p>
                <p className="mono text-[11px] text-[var(--acm-fg-4)]">{formatDate(status.next_job_at)}</p>
              </>
            ) : (
              <p className="text-[13px] text-[var(--acm-fg-4)] mt-1">—</p>
            )}
          </div>
        </div>

        {/* Job list */}
        {loading ? (
          <div className="flex justify-center py-12">
            <Loader2 size={22} className="animate-spin text-[var(--acm-fg-4)]" />
          </div>
        ) : jobs.length === 0 ? (
          <div
            className="text-center py-16 rounded-xl"
            style={{ border: '1px dashed var(--acm-border)' }}
          >
            <Activity size={36} className="mx-auto text-[var(--acm-fg-4)] mb-3" />
            <p className="text-[var(--acm-fg-3)] font-medium text-[14px]">{t.noJobs}</p>
            <p className="text-[var(--acm-fg-4)] text-[12px] mt-1">{t.noJobsDesc}</p>
            <button
              onClick={openNew}
              className="btn-primary mt-4 inline-flex items-center gap-2 px-4 py-2 text-[13px]"
            >
              <Plus size={13} />
              {t.newJob}
            </button>
          </div>
        ) : (
          <div className="space-y-2">
            {jobs.map(job => (
              <CronJobCard
                key={job.id}
                job={job}
                onEdit={openEdit}
                onDelete={handleDelete}
                onToggle={handleToggle}
                onTrigger={handleTrigger}
              />
            ))}
          </div>
        )}

        {/* Run history */}
        <div className="rounded-xl overflow-hidden" style={{ border: '1px solid var(--acm-border)' }}>
          <button
            onClick={() => setShowHistory(!showHistory)}
            className="w-full flex items-center justify-between px-5 py-3.5 text-[13px] font-medium text-[var(--acm-fg-2)] hover:bg-[var(--acm-elev)] transition-colors"
          >
            <span className="flex items-center gap-2">
              <Terminal size={14} className="text-[var(--acm-fg-4)]" />
              {t.history}
            </span>
            {showHistory
              ? <ChevronUp size={14} className="text-[var(--acm-fg-4)]" />
              : <ChevronDown size={14} className="text-[var(--acm-fg-4)]" />}
          </button>
          {showHistory && (
            <div className="px-2 pb-2 acm-scroll" style={{ borderTop: '1px solid var(--acm-border)' }}>
              <RunHistory runs={runs} loading={runsLoading} />
            </div>
          )}
        </div>

      </div>

      {/* Modal */}
      {showModal && (
        <JobModal
          job={modalJob}
          onClose={() => setShowModal(false)}
          onSave={() => { setShowModal(false); fetchJobs(); }}
        />
      )}
    </AppLayout>
  );
}
