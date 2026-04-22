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

const STATUS_STYLES: Record<string, string> = {
  pending: 'bg-yellow-500/15 text-yellow-400 border border-yellow-500/30',
  success: 'bg-green-500/15 text-green-400 border border-green-500/30',
  error:   'bg-red-500/15 text-red-400 border border-red-500/30',
  running: 'bg-blue-500/15 text-blue-400 border border-blue-500/30 animate-pulse',
};

const ACTION_STYLES: Record<ActionType, string> = {
  run_skill:           'bg-purple-500/15 text-purple-400 border border-purple-500/30',
  run_routine:         'bg-cyan-500/15 text-cyan-400 border border-cyan-500/30',
  analyze_patterns:    'bg-orange-500/15 text-orange-400 border border-orange-500/30',
  custom_command:      'bg-slate-500/15 text-slate-400 border border-slate-500/30',
  run_swarm_template:  'bg-amber-500/15 text-amber-400 border border-amber-500/30',
};

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
          <label className="block text-xs text-slate-400 mb-1">{t.skillName}</label>
          <input
            type="text"
            className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-blue-500"
            placeholder="e.g. daily_summary"
            value={String(payload.skill_name ?? '')}
            onChange={e => onChange({ ...payload, skill_name: e.target.value })}
          />
        </div>
      );
    case 'run_routine':
      return (
        <div>
          <label className="block text-xs text-slate-400 mb-1">{t.routineId}</label>
          <input
            type="number"
            className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-blue-500"
            placeholder="Routine ID"
            value={String(payload.routine_id ?? '')}
            onChange={e => onChange({ ...payload, routine_id: parseInt(e.target.value) || 0 })}
          />
        </div>
      );
    case 'analyze_patterns':
      return (
        <p className="text-xs text-slate-500 italic">
          No configuration needed — runs the pattern analyzer automatically.
        </p>
      );
    case 'custom_command':
      return (
        <div className="space-y-3">
          <div>
            <label className="block text-xs text-slate-400 mb-1">{t.command}</label>
            <textarea
              rows={2}
              className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm font-mono text-slate-200 focus:outline-none focus:border-blue-500"
              placeholder="e.g. python /path/to/script.py"
              value={String(payload.command ?? '')}
              onChange={e => onChange({ ...payload, command: e.target.value })}
            />
          </div>
          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="checkbox"
              className="rounded border-slate-600"
              checked={payload.shell !== false}
              onChange={e => onChange({ ...payload, shell: e.target.checked })}
            />
            <span className="text-xs text-slate-400">{t.shellMode}</span>
          </label>
        </div>
      );
    case 'run_swarm_template':
      return (
        <div className="space-y-3">
          <div>
            <label className="block text-xs text-slate-400 mb-1">Template ID</label>
            <input
              type="number"
              className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-blue-500"
              placeholder="Swarm template ID (create one in the API)"
              value={String(payload.template_id ?? '')}
              onChange={e => onChange({ ...payload, template_id: parseInt(e.target.value) || 0 })}
            />
          </div>
          <div>
            <label className="block text-xs text-slate-400 mb-1">Goal Override (optional)</label>
            <textarea
              rows={2}
              className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-blue-500"
              placeholder="Leave empty to use template goal. Use {date} placeholder."
              value={String(payload.goal_override ?? '')}
              onChange={e => onChange({ ...payload, goal_override: e.target.value })}
            />
          </div>
          <p className="text-xs text-slate-500">
            Creates a new swarm instance from the template every time this job fires.
            Use the <code className="bg-slate-800 px-1 rounded">/api/swarm-templates</code> endpoint to manage templates.
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
    <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50 p-4">
      <div className="bg-slate-900 border border-slate-700 rounded-2xl w-full max-w-lg shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between p-5 border-b border-slate-800">
          <h2 className="text-lg font-semibold text-slate-100">
            {job ? t.editJob : t.newJob}
          </h2>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-200 transition-colors">
            <X size={20} />
          </button>
        </div>

        {/* Body */}
        <div className="p-5 space-y-4 max-h-[70vh] overflow-y-auto">
          {error && (
            <div className="bg-red-500/10 border border-red-500/30 rounded-lg px-3 py-2 text-sm text-red-400">
              {error}
            </div>
          )}

          {/* Name */}
          <div>
            <label className="block text-xs font-medium text-slate-400 mb-1">{t.jobName}</label>
            <input
              type="text"
              className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-blue-500"
              placeholder="e.g. Daily Analysis"
              value={form.name}
              onChange={e => setForm({ ...form, name: e.target.value })}
            />
          </div>

          {/* Description */}
          <div>
            <label className="block text-xs font-medium text-slate-400 mb-1">{t.description}</label>
            <input
              type="text"
              className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-blue-500"
              placeholder="Optional description"
              value={form.description}
              onChange={e => setForm({ ...form, description: e.target.value })}
            />
          </div>

          {/* Cron Expression */}
          <div>
            <label className="block text-xs font-medium text-slate-400 mb-1">
              {t.cronExpression}
              <span className="ml-2 font-mono text-slate-500 text-xs">{t.cronHint}</span>
            </label>
            <input
              type="text"
              className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm font-mono text-slate-200 focus:outline-none focus:border-blue-500"
              placeholder="0 9 * * 1-5"
              value={form.cron_expr}
              onChange={e => setForm({ ...form, cron_expr: e.target.value })}
            />
            <p className="mt-1 text-xs text-blue-400/80 italic">{describeCron(form.cron_expr)}</p>
            {/* Presets */}
            <div className="mt-2 flex flex-wrap gap-1">
              {PRESETS.map(p => (
                <button
                  key={p.expr}
                  onClick={() => setForm({ ...form, cron_expr: p.expr })}
                  className="px-2 py-0.5 text-xs rounded-md bg-slate-700 hover:bg-slate-600 text-slate-300 transition-colors"
                >
                  {p.label}
                </button>
              ))}
            </div>
          </div>

          {/* Action Type */}
          <div>
            <label className="block text-xs font-medium text-slate-400 mb-1">{t.actionType}</label>
            <select
              className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-blue-500"
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
            <label className="block text-xs font-medium text-slate-400 mb-1">{t.actionPayload}</label>
            <PayloadEditor
              actionType={form.action_type}
              payload={form.action_payload}
              onChange={p => setForm({ ...form, action_payload: p })}
            />
          </div>

          {/* Enabled */}
          <label className="flex items-center gap-3 cursor-pointer">
            <div
              onClick={() => setForm({ ...form, is_enabled: !form.is_enabled })}
              className={`w-10 h-5 rounded-full transition-colors ${form.is_enabled ? 'bg-blue-600' : 'bg-slate-600'} relative`}
            >
              <span className={`absolute top-0.5 w-4 h-4 rounded-full bg-white shadow transition-transform ${form.is_enabled ? 'translate-x-5' : 'translate-x-0.5'}`} />
            </div>
            <span className="text-sm text-slate-300">{form.is_enabled ? t.enabled : 'Disabled'}</span>
          </label>
        </div>

        {/* Footer */}
        <div className="flex justify-end gap-3 p-5 border-t border-slate-800">
          <button
            onClick={onClose}
            className="px-4 py-2 rounded-lg text-sm text-slate-400 hover:text-slate-200 hover:bg-slate-800 transition-colors"
          >
            {translations.common.cancel}
          </button>
          <button
            onClick={handleSave}
            disabled={saving}
            className="flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium bg-blue-600 hover:bg-blue-500 text-white disabled:opacity-60 disabled:cursor-not-allowed transition-colors"
          >
            {saving ? <Loader2 size={14} className="animate-spin" /> : null}
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

  return (
    <div className={`bg-slate-800/50 border ${job.is_enabled ? 'border-slate-700' : 'border-slate-700/50 opacity-60'} rounded-xl p-4 space-y-3`}>
      {/* Top row */}
      <div className="flex items-start gap-3">
        <div className="mt-0.5 p-2 rounded-lg bg-slate-700/50">
          <Clock size={16} className={job.is_enabled ? 'text-blue-400' : 'text-slate-500'} />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <h3 className="text-sm font-semibold text-slate-100 truncate">{job.name}</h3>
            <span className={`text-xs px-2 py-0.5 rounded-full ${ACTION_STYLES[job.action_type]}`}>
              {t.actionTypes[job.action_type]}
            </span>
            <span className={`text-xs px-2 py-0.5 rounded-full ${STATUS_STYLES[job.last_status] ?? STATUS_STYLES.pending}`}>
              {t.status[job.last_status] ?? job.last_status}
            </span>
          </div>
          {job.description && (
            <p className="text-xs text-slate-400 mt-0.5 truncate">{job.description}</p>
          )}
          <div className="flex items-center gap-2 mt-1 flex-wrap">
            <code className="text-xs font-mono bg-slate-900/60 px-2 py-0.5 rounded text-blue-300">
              {job.cron_expr}
            </code>
            <span className="text-xs text-slate-500 italic">{describeCron(job.cron_expr)}</span>
          </div>
          {payloadSummary && (
            <p className="text-xs text-slate-500 mt-0.5 font-mono truncate">{payloadSummary}</p>
          )}
        </div>
        {/* Actions */}
        <div className="flex items-center gap-1 shrink-0">
          <button
            onClick={() => onToggle(job.id)}
            title={job.is_enabled ? 'Disable' : 'Enable'}
            className="p-1.5 rounded-lg text-slate-400 hover:text-slate-200 hover:bg-slate-700 transition-colors"
          >
            {job.is_enabled ? <ToggleRight size={18} className="text-blue-400" /> : <ToggleLeft size={18} />}
          </button>
          <button
            onClick={handleTrigger}
            disabled={triggering}
            title={t.triggerNow}
            className="p-1.5 rounded-lg text-slate-400 hover:text-green-400 hover:bg-slate-700 transition-colors disabled:opacity-50"
          >
            {triggering ? <Loader2 size={16} className="animate-spin" /> : <Play size={16} />}
          </button>
          <button
            onClick={() => onEdit(job)}
            title="Edit"
            className="p-1.5 rounded-lg text-slate-400 hover:text-blue-400 hover:bg-slate-700 transition-colors"
          >
            <Edit2 size={16} />
          </button>
          <button
            onClick={() => onDelete(job.id)}
            title="Delete"
            className="p-1.5 rounded-lg text-slate-400 hover:text-red-400 hover:bg-slate-700 transition-colors"
          >
            <Trash2 size={16} />
          </button>
        </div>
      </div>

      {/* Stats row */}
      <div className="flex items-center gap-4 text-xs text-slate-500 border-t border-slate-700/50 pt-2">
        <span>{t.lastRun}: <span className="text-slate-400">{formatDate(job.last_run)}</span></span>
        <span>{t.nextRun}: <span className="text-slate-400">{formatDate(job.next_run)}</span></span>
        <span>{t.runCount}: <span className="text-slate-400">{job.run_count}</span></span>
        {job.last_output && (
          <button
            onClick={() => setExpanded(!expanded)}
            className="ml-auto flex items-center gap-1 text-slate-500 hover:text-slate-300 transition-colors"
          >
            Last output {expanded ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
          </button>
        )}
      </div>

      {expanded && job.last_output && (
        <pre className="text-xs font-mono bg-slate-900/80 rounded-lg p-3 text-slate-300 max-h-32 overflow-auto whitespace-pre-wrap border border-slate-700/50">
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
        <Loader2 size={20} className="animate-spin text-slate-500" />
      </div>
    );
  }
  if (!runs.length) {
    return <p className="text-center text-slate-500 text-sm py-6">No runs recorded yet.</p>;
  }
  return (
    <div className="space-y-1">
      {runs.map(run => (
        <div
          key={run.id}
          className="flex items-start gap-3 py-2 px-3 rounded-lg hover:bg-slate-800/50 transition-colors"
        >
          <div className="mt-0.5">
            {run.status === 'success' ? (
              <CheckCircle size={14} className="text-green-400" />
            ) : run.status === 'error' ? (
              <XCircle size={14} className="text-red-400" />
            ) : (
              <Loader2 size={14} className="animate-spin text-blue-400" />
            )}
          </div>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-xs font-medium text-slate-300">{run.job_name}</span>
              {run.triggered_by === 'manual' && (
                <span className="text-xs bg-yellow-500/15 text-yellow-400 border border-yellow-500/30 px-1.5 py-0.5 rounded">manual</span>
              )}
            </div>
            <p className="text-xs text-slate-500">{formatDate(run.started_at)}</p>
            {(run.output || run.error) && (
              <p className="text-xs font-mono text-slate-400 truncate mt-0.5">
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
      <div className="p-6 max-w-4xl mx-auto space-y-6">

        {/* Header */}
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div>
            <h1 className="text-2xl font-bold text-slate-100 flex items-center gap-2">
              <Clock size={24} className="text-blue-400" />
              {t.title}
            </h1>
            <p className="text-slate-400 text-sm mt-1">{t.subtitle}</p>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={fetchJobs}
              className="p-2 rounded-lg text-slate-400 hover:text-slate-200 hover:bg-slate-800 transition-colors"
              title="Refresh"
            >
              <RefreshCw size={16} />
            </button>
            <button
              onClick={openNew}
              className="flex items-center gap-2 px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-500 text-white text-sm font-medium transition-colors"
            >
              <Plus size={16} />
              {t.newJob}
            </button>
          </div>
        </div>

        {/* Stats bar */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <div className="bg-slate-800/50 border border-slate-700 rounded-xl p-4">
            <p className="text-xs text-slate-400">{t.totalJobs}</p>
            <p className="text-2xl font-bold text-slate-100 mt-1">{jobs.length}</p>
          </div>
          <div className="bg-slate-800/50 border border-slate-700 rounded-xl p-4">
            <p className="text-xs text-slate-400">{t.enabledJobs}</p>
            <p className="text-2xl font-bold text-green-400 mt-1">{enabledCount}</p>
          </div>
          <div className="bg-slate-800/50 border border-slate-700 rounded-xl p-4">
            <p className="text-xs text-slate-400">Scheduler</p>
            <div className="flex items-center gap-2 mt-1">
              <span className={`w-2 h-2 rounded-full ${status?.running ? 'bg-green-500 animate-pulse' : 'bg-red-500'}`} />
              <p className="text-sm font-semibold text-slate-200">
                {status?.running ? t.schedulerRunning : t.schedulerStopped}
              </p>
            </div>
          </div>
          <div className="bg-slate-800/50 border border-slate-700 rounded-xl p-4">
            <p className="text-xs text-slate-400">{t.nextExecution}</p>
            {status?.next_job_name ? (
              <>
                <p className="text-xs font-medium text-blue-300 mt-1 truncate">{status.next_job_name}</p>
                <p className="text-xs text-slate-500">{formatDate(status.next_job_at)}</p>
              </>
            ) : (
              <p className="text-sm text-slate-500 mt-1">—</p>
            )}
          </div>
        </div>

        {/* Job list */}
        {loading ? (
          <div className="flex justify-center py-12">
            <Loader2 size={24} className="animate-spin text-slate-500" />
          </div>
        ) : jobs.length === 0 ? (
          <div className="text-center py-16 border border-dashed border-slate-700 rounded-2xl">
            <Activity size={40} className="mx-auto text-slate-600 mb-3" />
            <p className="text-slate-400 font-medium">{t.noJobs}</p>
            <p className="text-slate-500 text-sm mt-1">{t.noJobsDesc}</p>
            <button
              onClick={openNew}
              className="mt-4 flex items-center gap-2 px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-500 text-white text-sm font-medium transition-colors mx-auto"
            >
              <Plus size={14} />
              {t.newJob}
            </button>
          </div>
        ) : (
          <div className="space-y-3">
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
        <div className="border border-slate-700 rounded-xl overflow-hidden">
          <button
            onClick={() => setShowHistory(!showHistory)}
            className="w-full flex items-center justify-between px-5 py-4 text-sm font-medium text-slate-300 hover:bg-slate-800/50 transition-colors"
          >
            <span className="flex items-center gap-2">
              <Terminal size={16} className="text-slate-400" />
              {t.history}
            </span>
            {showHistory ? <ChevronUp size={16} className="text-slate-500" /> : <ChevronDown size={16} className="text-slate-500" />}
          </button>
          {showHistory && (
            <div className="px-4 pb-4 border-t border-slate-700">
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
