'use client';

import { useState, useEffect, useCallback } from 'react';
import {
  CalendarClock,
  Play,
  Trash2,
  ToggleLeft,
  ToggleRight,
  Clock,
  BarChart2,
  Zap,
  Activity,
  Sparkles,
  RefreshCw,
  Edit2,
  Check,
  X,
  ShieldCheck,
  ShieldOff,
  Plus,
  Settings2,
} from 'lucide-react';
import { AppLayout } from '@/components/layout/app-layout';
import { useAuthStore } from '@/stores/auth-store';

// ─── Types ───────────────────────────────────────────────

interface AppInfo {
  app_name: string;
  process_name: string;
  exe_path?: string;
}

interface TriggerData {
  hour?: number;
  minute?: number;
  days_of_week?: number[];
}

interface Routine {
  id: number;
  name: string;
  description: string;
  trigger_type: 'time_based' | 'manual' | 'app_triggered';
  trigger_data: string;
  apps: string;
  confidence: number;
  status: 'pending' | 'active' | 'inactive';
  last_run: string | null;
  run_count: number;
  occurrence_count: number;
  cron_job_id: number | null;
  created_at: string;
}

interface AppStat {
  app_name: string;
  process_name: string;
  total_seconds: number;
  session_count: number;
}

interface ActivityStats {
  apps: AppStat[];
  total_hours: number;
  session_count: number;
}

interface WatcherStatus {
  running: boolean;
  current_app: string | null;
  current_title: string | null;
  sessions_recorded: number;
  encrypted: boolean;
  key_path: string | null;
}

// ─── Helpers ─────────────────────────────────────────────

function parseJson<T>(raw: string, fallback: T): T {
  try { return JSON.parse(raw) as T; } catch { return fallback; }
}

function formatSeconds(secs: number): string {
  if (secs < 60) return `${Math.round(secs)}s`;
  if (secs < 3600) return `${Math.round(secs / 60)}m`;
  return `${(secs / 3600).toFixed(1)}h`;
}

function formatDate(iso: string | null): string {
  if (!iso) return 'Never';
  try {
    return new Date(iso).toLocaleString(undefined, {
      day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit',
    });
  } catch { return 'Never'; }
}

const DAY_LABELS = ['L', 'M', 'X', 'J', 'V', 'S', 'D'];

const STATUS_COLORS: Record<string, string> = {
  pending:  'bg-yellow-500/15 text-yellow-400 border-yellow-500/30',
  active:   'bg-green-500/15  text-green-400  border-green-500/30',
  inactive: 'bg-slate-500/15  text-slate-400  border-slate-500/30',
};

const APP_PALETTE = [
  'bg-blue-500/20 text-blue-300',
  'bg-purple-500/20 text-purple-300',
  'bg-green-500/20 text-green-300',
  'bg-orange-500/20 text-orange-300',
  'bg-pink-500/20 text-pink-300',
  'bg-cyan-500/20 text-cyan-300',
  'bg-indigo-500/20 text-indigo-300',
  'bg-red-500/20 text-red-300',
];

function appColor(name: string): string {
  let h = 0;
  for (const c of name) h = (h * 31 + c.charCodeAt(0)) & 0xff;
  return APP_PALETTE[h % APP_PALETTE.length];
}

// ─── Sub-components ───────────────────────────────────────

function ConfidenceBar({ value }: { value: number }) {
  const pct = Math.round(value * 100);
  const color = pct >= 75 ? 'bg-green-500' : pct >= 50 ? 'bg-yellow-500' : 'bg-slate-500';
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-1.5 bg-slate-700 rounded-full overflow-hidden">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs text-slate-400 tabular-nums w-8 text-right">{pct}%</span>
    </div>
  );
}

function TriggerBadge({ routine }: { routine: Routine }) {
  const td = parseJson<TriggerData>(routine.trigger_data, {});
  if (routine.trigger_type === 'time_based' && td.hour !== undefined) {
    const h = td.hour.toString().padStart(2, '0');
    const m = (td.minute ?? 0).toString().padStart(2, '0');
    const days = td.days_of_week?.map(d => DAY_LABELS[d] ?? '?').join('') ?? '';
    return (
      <div className="flex items-center gap-1.5 text-xs text-slate-400">
        <Clock size={11} />
        <span>Triggers at {h}:{m}</span>
        {days && <span className="ml-1 text-slate-500">({days})</span>}
      </div>
    );
  }
  return (
    <div className="flex items-center gap-1.5 text-xs text-slate-500">
      <Zap size={11} />
      <span>Manual trigger</span>
    </div>
  );
}

// ─── Edit Routine Modal ───────────────────────────────────

function EditRoutineModal({
  routine,
  onClose,
  onSaved,
  authHeader,
}: {
  routine: Routine;
  onClose: () => void;
  onSaved: (updated: Routine) => void;
  authHeader: Record<string, string>;
}) {
  const initialApps = parseJson<AppInfo[]>(routine.apps, []);
  const initialTrigger = parseJson<TriggerData>(routine.trigger_data, {});

  const [apps, setApps] = useState<AppInfo[]>(initialApps);
  const [triggerType, setTriggerType] = useState<Routine['trigger_type']>(routine.trigger_type);
  const [hour, setHour] = useState(initialTrigger.hour ?? 9);
  const [minute, setMinute] = useState(initialTrigger.minute ?? 0);
  const [days, setDays] = useState<number[]>(initialTrigger.days_of_week ?? [0, 1, 2, 3, 4]);
  const [newAppName, setNewAppName] = useState('');
  const [newProcName, setNewProcName] = useState('');
  const [newExePath, setNewExePath] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  const addApp = () => {
    const name = newAppName.trim();
    if (!name) return;
    setApps(p => [...p, {
      app_name: name,
      process_name: newProcName.trim() || name.toLowerCase(),
      exe_path: newExePath.trim(),
    }]);
    setNewAppName('');
    setNewProcName('');
    setNewExePath('');
  };

  const toggleDay = (d: number) =>
    setDays(p => p.includes(d) ? p.filter(x => x !== d) : [...p, d].sort((a, b) => a - b));

  const handleSave = async () => {
    setSaving(true);
    setError('');
    const trigger_data = triggerType === 'time_based'
      ? { hour, minute, days_of_week: days }
      : {};
    try {
      const res = await fetch(`/api/routines/${routine.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...authHeader },
        body: JSON.stringify({ apps, trigger_type: triggerType, trigger_data }),
      });
      if (!res.ok) throw new Error(await res.text());
      onSaved(await res.json());
      onClose();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/60 z-50 flex items-center justify-center p-4">
      <div className="bg-slate-900 border border-slate-700 rounded-xl w-full max-w-lg p-6 space-y-5 overflow-y-auto max-h-[90vh]">
        <h2 className="text-lg font-semibold text-white flex items-center gap-2">
          <Settings2 size={18} className="text-blue-400" /> Edit Routine
        </h2>

        {/* Apps list */}
        <div>
          <label className="block text-xs text-slate-400 mb-2">Apps</label>
          <div className="space-y-2 mb-3">
            {apps.map((app, i) => (
              <div key={i} className="bg-slate-800 border border-slate-700 rounded-lg p-2 space-y-1.5">
                <div className="flex items-center gap-2">
                  <span className="flex-1 text-sm text-slate-200 font-medium truncate">{app.app_name}</span>
                  <span className="text-xs text-slate-500">{app.process_name}</span>
                  <button onClick={() => setApps(p => p.filter((_, idx) => idx !== i))} className="text-slate-500 hover:text-red-400 p-0.5">
                    <X size={12} />
                  </button>
                </div>
                <input
                  className="w-full bg-slate-900 border border-slate-700 rounded px-2 py-1 text-xs text-slate-300 focus:outline-none focus:border-blue-500"
                  placeholder="Exe path (optional, e.g. C:\Program Files\App\app.exe)"
                  value={app.exe_path || ''}
                  onChange={e => setApps(p => p.map((a, idx) => idx === i ? { ...a, exe_path: e.target.value } : a))}
                />
              </div>
            ))}
            {apps.length === 0 && <p className="text-xs text-slate-500 italic">No apps — add one below</p>}
          </div>
          <div className="space-y-2">
            <div className="flex gap-2">
              <input
                className="flex-1 bg-slate-800 border border-slate-700 rounded-lg px-3 py-1.5 text-sm text-slate-200 focus:outline-none focus:border-blue-500"
                placeholder="App name (e.g. Chrome)"
                value={newAppName}
                onChange={e => setNewAppName(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && addApp()}
              />
              <input
                className="w-28 bg-slate-800 border border-slate-700 rounded-lg px-3 py-1.5 text-sm text-slate-200 focus:outline-none focus:border-blue-500"
                placeholder="process"
                value={newProcName}
                onChange={e => setNewProcName(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && addApp()}
              />
              <button
                onClick={addApp}
                className="px-3 py-1.5 rounded-lg bg-blue-600/20 border border-blue-600/30 text-blue-400 hover:bg-blue-600/30 transition-colors"
              >
                <Plus size={14} />
              </button>
            </div>
            <input
              className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-1.5 text-sm text-slate-200 focus:outline-none focus:border-blue-500"
              placeholder="Exe path for new app (optional)"
              value={newExePath}
              onChange={e => setNewExePath(e.target.value)}
            />
          </div>
        </div>

        {/* Trigger type */}
        <div>
          <label className="block text-xs text-slate-400 mb-2">Trigger type</label>
          <div className="flex gap-2">
            {(['manual', 'time_based'] as const).map(t => (
              <button
                key={t}
                onClick={() => setTriggerType(t)}
                className={`px-3 py-1.5 rounded-lg text-sm border transition-colors ${
                  triggerType === t
                    ? 'bg-blue-600/20 border-blue-600/30 text-blue-400'
                    : 'border-slate-700 text-slate-400 hover:text-slate-300'
                }`}
              >
                {t === 'manual' ? 'Manual' : 'Time-based (auto)'}
              </button>
            ))}
          </div>
        </div>

        {/* Time config */}
        {triggerType === 'time_based' && (
          <div className="space-y-3 bg-slate-800/50 border border-slate-700 rounded-xl p-4">
            <div className="flex gap-4">
              <div>
                <label className="block text-xs text-slate-400 mb-1">Hour (0–23)</label>
                <input
                  type="number" min={0} max={23}
                  className="w-20 bg-slate-800 border border-slate-700 rounded-lg px-3 py-1.5 text-sm text-slate-200 focus:outline-none focus:border-blue-500"
                  value={hour}
                  onChange={e => setHour(Math.min(23, Math.max(0, Number(e.target.value))))}
                />
              </div>
              <div>
                <label className="block text-xs text-slate-400 mb-1">Minute</label>
                <input
                  type="number" min={0} max={59}
                  className="w-20 bg-slate-800 border border-slate-700 rounded-lg px-3 py-1.5 text-sm text-slate-200 focus:outline-none focus:border-blue-500"
                  value={minute}
                  onChange={e => setMinute(Math.min(59, Math.max(0, Number(e.target.value))))}
                />
              </div>
            </div>
            <div>
              <label className="block text-xs text-slate-400 mb-2">Days</label>
              <div className="flex gap-1.5">
                {DAY_LABELS.map((label, i) => (
                  <button
                    key={i}
                    onClick={() => toggleDay(i)}
                    className={`w-9 h-9 rounded-lg text-xs font-semibold transition-colors ${
                      days.includes(i)
                        ? 'bg-blue-600 text-white'
                        : 'bg-slate-800 text-slate-400 hover:bg-slate-700'
                    }`}
                  >
                    {label}
                  </button>
                ))}
              </div>
            </div>
            <p className="text-xs text-slate-500">
              Activating this routine will create a cron job that runs it automatically at {String(hour).padStart(2, '0')}:{String(minute).padStart(2, '0')}.
            </p>
          </div>
        )}

        {error && <p className="text-red-400 text-xs">{error}</p>}

        <div className="flex gap-2 pt-1">
          <button
            onClick={onClose}
            className="flex-1 px-4 py-2 rounded-lg border border-slate-700 text-slate-300 hover:bg-slate-800 text-sm transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={handleSave}
            disabled={saving}
            className="flex-1 px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium disabled:opacity-60 transition-colors"
          >
            {saving ? 'Saving...' : 'Save changes'}
          </button>
        </div>
      </div>
    </div>
  );
}

// ─── Routine Card ─────────────────────────────────────────

function RoutineCard({
  routine, onRun, onToggle, onDelete, onRename, onEdit,
}: {
  routine: Routine;
  onRun: (id: number) => Promise<void>;
  onToggle: (id: number, status: string) => Promise<void>;
  onDelete: (id: number) => void;
  onRename: (id: number, name: string) => Promise<void>;
  onEdit: (routine: Routine) => void;
}) {
  const [running, setRunning] = useState(false);
  const [editing, setEditing] = useState(false);
  const [nameInput, setNameInput] = useState(routine.name);

  const apps = parseJson<AppInfo[]>(routine.apps, []);
  const isActive = routine.status === 'active';

  const handleRun = async () => {
    setRunning(true);
    try { await onRun(routine.id); } finally { setRunning(false); }
  };

  const handleSaveName = async () => {
    if (nameInput.trim() && nameInput !== routine.name) {
      await onRename(routine.id, nameInput.trim());
    }
    setEditing(false);
  };

  return (
    <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl p-5 flex flex-col gap-4 hover:border-slate-600/60 transition-colors">

      {/* Header */}
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          {editing ? (
            <div className="flex items-center gap-2">
              <input
                className="flex-1 bg-slate-700 border border-slate-600 rounded-lg px-3 py-1 text-sm text-white focus:outline-none focus:border-blue-500"
                value={nameInput}
                onChange={e => setNameInput(e.target.value)}
                onKeyDown={e => { if (e.key === 'Enter') handleSaveName(); if (e.key === 'Escape') setEditing(false); }}
                autoFocus
              />
              <button onClick={handleSaveName} className="text-green-400 hover:text-green-300"><Check size={15} /></button>
              <button onClick={() => { setEditing(false); setNameInput(routine.name); }} className="text-slate-400 hover:text-slate-300"><X size={15} /></button>
            </div>
          ) : (
            <div className="flex items-center gap-2 group">
              <h3 className="text-white font-semibold text-sm leading-snug truncate">{routine.name}</h3>
              <button onClick={() => setEditing(true)} className="opacity-0 group-hover:opacity-100 text-slate-500 hover:text-slate-300 transition-opacity">
                <Edit2 size={12} />
              </button>
            </div>
          )}

          <div className="mt-1"><TriggerBadge routine={routine} /></div>

          {routine.description && (
            <p className="text-xs text-slate-500 mt-1 italic leading-snug">{routine.description}</p>
          )}
        </div>

        <span className={`shrink-0 text-xs px-2 py-0.5 rounded-full border font-medium ${STATUS_COLORS[routine.status] ?? STATUS_COLORS.inactive}`}>
          {routine.status.charAt(0).toUpperCase() + routine.status.slice(1)}
        </span>
      </div>

      {/* Apps */}
      <div className="flex flex-wrap gap-1.5">
        {apps.length === 0
          ? <span className="text-xs text-slate-500 italic">No apps configured</span>
          : apps.map((app, i) => (
            <span key={i} className={`text-xs px-2 py-0.5 rounded-full font-medium ${appColor(app.app_name)}`}>
              {app.app_name}
            </span>
          ))}
      </div>

      {/* Confidence */}
      <div>
        <div className="flex justify-between text-xs text-slate-500 mb-1">
          <span>Confidence</span>
          <span>{routine.occurrence_count}× detected</span>
        </div>
        <ConfidenceBar value={routine.confidence} />
      </div>

      {/* Meta */}
      <div className="flex items-center gap-4 text-xs text-slate-500">
        <span>{routine.run_count} runs</span>
        <span>·</span>
        <span>Last: {formatDate(routine.last_run)}</span>
        {routine.cron_job_id && (
          <span className="inline-flex items-center gap-1 text-green-400 ml-auto">
            <Clock size={10} /> auto
          </span>
        )}
      </div>

      {/* Actions */}
      <div className="flex items-center gap-2 pt-1 border-t border-slate-700/50">
        <button
          onClick={handleRun}
          disabled={running}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-blue-600/20 hover:bg-blue-600/30 text-blue-400 border border-blue-600/30 text-xs font-medium transition-colors disabled:opacity-50"
        >
          <Play size={12} className={running ? 'animate-pulse' : ''} />
          {running ? 'Running...' : 'Run now'}
        </button>

        <button
          onClick={() => onToggle(routine.id, routine.status)}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-slate-700/50 hover:bg-slate-700 text-slate-300 border border-slate-600/30 text-xs font-medium transition-colors"
        >
          {isActive
            ? <><ToggleRight size={13} className="text-green-400" /> Deactivate</>
            : <><ToggleLeft size={13} /> Activate</>}
        </button>

        <div className="flex-1" />

        <button
          onClick={() => onEdit(routine)}
          className="p-1.5 rounded-lg text-slate-500 hover:text-blue-400 hover:bg-blue-500/10 transition-colors"
          title="Edit routine"
        >
          <Settings2 size={13} />
        </button>

        <button
          onClick={() => onDelete(routine.id)}
          className="p-1.5 rounded-lg text-slate-500 hover:text-red-400 hover:bg-red-500/10 transition-colors"
          title="Delete routine"
        >
          <Trash2 size={13} />
        </button>
      </div>
    </div>
  );
}

function AppStatRow({ stat, max }: { stat: AppStat; max: number }) {
  const pct = max > 0 ? (stat.total_seconds / max) * 100 : 0;
  const colorClass = appColor(stat.app_name).split(' ')[0];
  return (
    <div className="flex items-center gap-3">
      <span className={`w-2 h-2 rounded-full shrink-0 ${colorClass}`} />
      <span className="text-sm text-slate-300 w-32 truncate">{stat.app_name}</span>
      <div className="flex-1 h-1.5 bg-slate-700 rounded-full overflow-hidden">
        <div className={`h-full rounded-full ${colorClass.replace('/20', '/60')}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs text-slate-500 tabular-nums w-12 text-right">{formatSeconds(stat.total_seconds)}</span>
      <span className="text-xs text-slate-600 tabular-nums w-14 text-right">{stat.session_count} sess.</span>
    </div>
  );
}

function StatCard({ icon, label, value }: { icon: React.ReactNode; label: string; value: string }) {
  return (
    <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl p-4 flex items-center gap-3">
      <div className="shrink-0">{icon}</div>
      <div className="min-w-0">
        <div className="text-xs text-slate-500 truncate">{label}</div>
        <div className="text-lg font-bold text-white tabular-nums">{value}</div>
      </div>
    </div>
  );
}

function InfoRow({ label, value, accent, truncate }: { label: string; value: string; accent?: string; truncate?: boolean }) {
  return (
    <div className="flex items-center justify-between gap-4">
      <span className="text-xs text-slate-500 shrink-0">{label}</span>
      <span className={`text-xs font-medium text-right ${accent ?? 'text-slate-300'} ${truncate ? 'truncate max-w-[60%]' : ''}`}>{value}</span>
    </div>
  );
}

// ─── Main page ────────────────────────────────────────────

export default function RoutinesPage() {
  const token = useAuthStore(s => s.token);
  const headers: Record<string, string> = token ? { Authorization: `Bearer ${token}` } : {};

  const [tab, setTab] = useState<'routines' | 'activity'>('routines');
  const [routines, setRoutines] = useState<Routine[]>([]);
  const [stats, setStats] = useState<ActivityStats>({ apps: [], total_hours: 0, session_count: 0 });
  const [watcher, setWatcher] = useState<WatcherStatus>({ running: false, current_app: null, current_title: null, sessions_recorded: 0, encrypted: false, key_path: null });
  const [loading, setLoading] = useState(true);
  const [analyzing, setAnalyzing] = useState(false);
  const [toast, setToast] = useState<{ msg: string; ok: boolean } | null>(null);
  const [editingRoutine, setEditingRoutine] = useState<Routine | null>(null);

  const showToast = (msg: string, ok = true) => {
    setToast({ msg, ok });
    setTimeout(() => setToast(null), 3000);
  };

  const fetchAll = useCallback(async () => {
    try {
      const [rRes, sRes, wRes] = await Promise.all([
        fetch('/api/routines', { headers }),
        fetch('/api/activity/stats', { headers }),
        fetch('/api/watcher/status', { headers }),
      ]);
      if (rRes.ok) setRoutines(await rRes.json());
      if (sRes.ok) setStats(await sRes.json());
      if (wRes.ok) setWatcher(await wRes.json());
    } catch { /* ignore */ }
    setLoading(false);
  }, [token]);

  useEffect(() => { fetchAll(); }, [fetchAll]);

  const handleRun = async (id: number) => {
    const res = await fetch(`/api/routines/${id}/execute`, { method: 'POST', headers });
    if (res.ok) { showToast('Routine executed'); fetchAll(); }
    else showToast('Failed to execute routine', false);
  };

  const handleToggle = async (id: number, status: string) => {
    const newStatus = status === 'active' ? 'inactive' : 'active';
    const res = await fetch(`/api/routines/${id}`, {
      method: 'PUT',
      headers: { ...headers, 'Content-Type': 'application/json' },
      body: JSON.stringify({ status: newStatus }),
    });
    if (res.ok) {
      const updated: Routine = await res.json();
      showToast(
        newStatus === 'active'
          ? updated.cron_job_id ? 'Activated — cron job created' : 'Activated'
          : 'Deactivated'
      );
      fetchAll();
    }
  };

  const handleDelete = async (id: number) => {
    if (!confirm('Delete this routine?')) return;
    const res = await fetch(`/api/routines/${id}`, { method: 'DELETE', headers });
    if (res.ok) { showToast('Routine deleted'); fetchAll(); }
  };

  const handleRename = async (id: number, name: string) => {
    await fetch(`/api/routines/${id}`, {
      method: 'PUT',
      headers: { ...headers, 'Content-Type': 'application/json' },
      body: JSON.stringify({ name }),
    });
    fetchAll();
  };

  const handleAnalyze = async () => {
    setAnalyzing(true);
    try {
      const res = await fetch('/api/routines/analyze', { method: 'POST', headers });
      if (res.ok) {
        const data = await res.json();
        showToast(data.new_routines > 0 ? `Found ${data.new_routines} new routine(s)` : 'No new patterns found', data.new_routines > 0);
        fetchAll();
      }
    } finally { setAnalyzing(false); }
  };

  const maxSecs = stats.apps[0]?.total_seconds ?? 1;

  return (
    <AppLayout>
      <div className="p-6 lg:p-8 space-y-6">

        {/* Toast */}
        {toast && (
          <div className={`fixed top-5 right-5 z-50 px-4 py-2.5 rounded-lg text-sm font-medium shadow-lg ${toast.ok ? 'bg-green-600' : 'bg-red-600'} text-white`}>
            {toast.msg}
          </div>
        )}

        {/* Header */}
        <div className="flex items-start justify-between">
          <div>
            <h1 className="text-2xl font-bold text-white flex items-center gap-3">
              <CalendarClock size={24} className="text-blue-400" />
              My Routines
            </h1>
            <p className="text-slate-400 text-sm mt-1">
              Patterns detected automatically from your daily app usage
            </p>
          </div>
          <button
            onClick={handleAnalyze}
            disabled={analyzing}
            className="flex items-center gap-2 px-4 py-2 rounded-lg bg-blue-600/20 hover:bg-blue-600/30 text-blue-400 border border-blue-600/30 text-sm font-medium transition-colors disabled:opacity-50"
          >
            {analyzing
              ? <><RefreshCw size={14} className="animate-spin" /> Analyzing...</>
              : <><Sparkles size={14} /> Analyze now</>}
          </button>
        </div>

        {/* Encryption banner */}
        {watcher.encrypted ? (
          <div className="flex items-start gap-3 p-4 bg-green-500/10 border border-green-500/20 rounded-xl">
            <ShieldCheck size={18} className="text-green-400 shrink-0 mt-0.5" />
            <div className="min-w-0">
              <p className="text-sm font-medium text-green-400">Activity data is encrypted</p>
              <p className="text-xs text-green-500/70 mt-0.5">
                All app names and window titles are encrypted with a local AES key that never leaves your machine.
                {watcher.key_path && (
                  <span className="block mt-0.5 font-mono text-green-600/60 truncate">{watcher.key_path}</span>
                )}
              </p>
            </div>
          </div>
        ) : (
          <div className="flex items-start gap-3 p-4 bg-yellow-500/10 border border-yellow-500/20 rounded-xl">
            <ShieldOff size={18} className="text-yellow-400 shrink-0 mt-0.5" />
            <p className="text-sm text-yellow-400">
              Activity data is stored unencrypted. Restart OpenACM to generate a local encryption key.
            </p>
          </div>
        )}

        {/* Stats bar */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <StatCard icon={<Clock size={16} className="text-blue-400" />}     label="Hours monitored"   value={`${stats.total_hours.toFixed(1)}h`} />
          <StatCard icon={<Activity size={16} className="text-green-400" />} label="Sessions recorded"  value={stats.session_count.toString()} />
          <StatCard icon={<CalendarClock size={16} className="text-purple-400" />} label="Routines detected" value={routines.length.toString()} />
          <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl p-4 flex items-center gap-3">
            <span className={`w-2 h-2 rounded-full shrink-0 ${watcher.running ? 'bg-green-500 animate-pulse' : 'bg-slate-500'}`} />
            <div className="min-w-0">
              <div className="text-xs text-slate-500">{watcher.running ? 'Monitor active' : 'Monitor inactive'}</div>
              <div className="text-sm text-white truncate">{watcher.current_app ?? '—'}</div>
            </div>
          </div>
        </div>

        {/* Tabs */}
        <div className="flex gap-1 bg-slate-800/50 p-1 rounded-xl w-fit">
          {(['routines', 'activity'] as const).map(tabKey => (
            <button
              key={tabKey}
              onClick={() => setTab(tabKey)}
              className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${tab === tabKey ? 'bg-blue-600 text-white' : 'text-slate-400 hover:text-slate-200'}`}
            >
              {tabKey === 'routines' ? 'My Routines' : 'App Activity'}
            </button>
          ))}
        </div>

        {/* Tab: Routines */}
        {tab === 'routines' && (
          loading ? (
            <div className="flex items-center justify-center h-40 text-slate-500">
              <RefreshCw size={18} className="animate-spin mr-2" /> Loading...
            </div>
          ) : routines.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-60 text-center gap-4">
              <CalendarClock size={48} className="text-slate-600" />
              <div>
                <p className="text-slate-300 font-medium">No routines detected yet</p>
                <p className="text-slate-500 text-sm mt-1 max-w-sm">
                  OpenACM monitors your app usage and detects patterns automatically. Check back in a few days, or click Analyze now.
                </p>
              </div>
              <button
                onClick={handleAnalyze}
                disabled={analyzing}
                className="flex items-center gap-2 px-4 py-2 rounded-lg bg-blue-600/20 hover:bg-blue-600/30 text-blue-400 border border-blue-600/30 text-sm font-medium"
              >
                <Sparkles size={14} /> Analyze now
              </button>
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
              {routines.map(r => (
                <RoutineCard
                  key={r.id}
                  routine={r}
                  onRun={handleRun}
                  onToggle={handleToggle}
                  onDelete={handleDelete}
                  onRename={handleRename}
                  onEdit={setEditingRoutine}
                />
              ))}
            </div>
          )
        )}

        {/* Tab: Activity */}
        {tab === 'activity' && (
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">

            {/* Top apps */}
            <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl p-5">
              <div className="flex items-center gap-2 mb-4">
                <BarChart2 size={16} className="text-blue-400" />
                <h3 className="text-white font-semibold text-sm">Top Apps by Usage</h3>
              </div>
              {stats.apps.length === 0 ? (
                <p className="text-slate-500 text-sm text-center py-6">No data yet</p>
              ) : (
                <div className="space-y-3">
                  {stats.apps.slice(0, 12).map((app, i) => (
                    <AppStatRow key={i} stat={app} max={maxSecs} />
                  ))}
                </div>
              )}
            </div>

            {/* Watcher status */}
            <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl p-5">
              <div className="flex items-center gap-2 mb-4">
                <Activity size={16} className="text-green-400" />
                <h3 className="text-white font-semibold text-sm">Monitor Status</h3>
              </div>
              <div className="space-y-3">
                <InfoRow label="Status"            value={watcher.running ? 'Active' : 'Inactive'} accent={watcher.running ? 'text-green-400' : 'text-slate-400'} />
                <InfoRow label="Encryption"        value={watcher.encrypted ? 'AES-128 local key' : 'None'} accent={watcher.encrypted ? 'text-green-400' : 'text-yellow-400'} />
                <InfoRow label="Current app"       value={watcher.current_app ?? '—'} />
                <InfoRow label="Window"            value={watcher.current_title ?? '—'} truncate />
                <InfoRow label="Sessions recorded" value={watcher.sessions_recorded.toString()} />
                <InfoRow label="Total hours"       value={`${stats.total_hours.toFixed(1)}h`} />
                <InfoRow label="Total sessions"    value={stats.session_count.toString()} />
              </div>
              <div className="mt-4 p-3 bg-slate-700/30 rounded-lg">
                <p className="text-xs text-slate-400 leading-relaxed">
                  The monitor records which app is focused and for how long. After a few days, OpenACM will detect your patterns and create routine suggestions.
                </p>
              </div>
            </div>
          </div>
        )}
      </div>

      {editingRoutine && (
        <EditRoutineModal
          routine={editingRoutine}
          authHeader={headers}
          onClose={() => setEditingRoutine(null)}
          onSaved={(updated) => {
            setRoutines(prev => prev.map(r => r.id === updated.id ? updated : r));
            setEditingRoutine(null);
            showToast('Routine updated');
          }}
        />
      )}
    </AppLayout>
  );
}
