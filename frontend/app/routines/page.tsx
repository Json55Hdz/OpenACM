'use client';

import { useState, useEffect, useCallback } from 'react';
import {
  CalendarClock,
  Play,
  Trash2,
  ToggleLeft,
  ToggleRight,
  Clock,
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
  MoreHorizontal,
} from 'lucide-react';
import { AppLayout } from '@/components/layout/app-layout';
import { useAuthStore } from '@/stores/auth-store';

// ─── Types ────────────────────────────────────────────────

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

// ─── Helpers ──────────────────────────────────────────────

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

const DAY_LABELS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
const DAY_SHORT  = ['M', 'T', 'W', 'T', 'F', 'S', 'S'];

// Status → dot class
function statusDotClass(status: string): string {
  if (status === 'active')  return 'dot dot-ok';
  if (status === 'pending') return 'dot dot-warn';
  return 'dot dot-idle';
}

// Status → left-border color
function statusBorderColor(status: string): string {
  if (status === 'active')  return 'var(--acm-ok)';
  if (status === 'pending') return 'var(--acm-warn)';
  return 'var(--acm-fg-4)';
}

// Deterministic app color from name — uses oklch DATA colors (not UI accents)
const APP_COLORS = [
  'oklch(0.62 0.18 250)',  // blue  — VS Code
  'oklch(0.84 0.16 82)',   // amber — Chrome
  'oklch(0.73 0.16 145)',  // green — Linear
  'oklch(0.66 0.18 300)',  // purple — Figma
  'oklch(0.72 0.18 55)',   // orange — Slack
  'oklch(0.70 0.15 195)',  // teal
  'oklch(0.65 0.14 20)',   // red
  'oklch(0.68 0.12 320)',  // pink
];

function appColorOklch(name: string): string {
  let h = 0;
  for (const c of name) h = (h * 31 + c.charCodeAt(0)) & 0xff;
  return APP_COLORS[h % APP_COLORS.length];
}

// ─── Confidence Bar ───────────────────────────────────────

function ConfidenceBar({ value }: { value: number }) {
  const pct = Math.round(value * 100);
  const fill = pct >= 80 ? 'var(--acm-ok)' : pct >= 70 ? 'var(--acm-warn)' : 'var(--acm-fg-4)';
  return (
    <div className="flex items-center gap-2">
      <div
        className="flex-1 h-1 rounded-full overflow-hidden"
        style={{ background: 'var(--acm-border)' }}
      >
        <div
          className="h-full rounded-full transition-all"
          style={{ width: `${pct}%`, background: fill }}
        />
      </div>
      <span className="mono text-[11px] shrink-0" style={{ color: fill }}>
        {pct}%
      </span>
    </div>
  );
}

// ─── Trigger Info ─────────────────────────────────────────

function TriggerInfo({ routine }: { routine: Routine }) {
  const td = parseJson<TriggerData>(routine.trigger_data, {});
  if (routine.trigger_type === 'time_based' && td.hour !== undefined) {
    const h = td.hour.toString().padStart(2, '0');
    const m = (td.minute ?? 0).toString().padStart(2, '0');
    const days = td.days_of_week?.map(d => DAY_SHORT[d] ?? '?').join('') ?? '';
    return (
      <span className="mono text-[11px]" style={{ color: 'var(--acm-fg-4)' }}>
        <Clock size={9} className="inline mr-1" />
        {h}:{m}{days && ` · ${days}`}
      </span>
    );
  }
  return (
    <span className="mono text-[11px]" style={{ color: 'var(--acm-fg-4)' }}>
      <Zap size={9} className="inline mr-1" />manual
    </span>
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
  const initialApps    = parseJson<AppInfo[]>(routine.apps, []);
  const initialTrigger = parseJson<TriggerData>(routine.trigger_data, {});

  const [apps, setApps]             = useState<AppInfo[]>(initialApps);
  const [triggerType, setTriggerType] = useState<Routine['trigger_type']>(routine.trigger_type);
  const [hour, setHour]             = useState(initialTrigger.hour ?? 9);
  const [minute, setMinute]         = useState(initialTrigger.minute ?? 0);
  const [days, setDays]             = useState<number[]>(initialTrigger.days_of_week ?? [0, 1, 2, 3, 4]);
  const [newAppName, setNewAppName] = useState('');
  const [newProcName, setNewProcName] = useState('');
  const [newExePath, setNewExePath] = useState('');
  const [saving, setSaving]         = useState(false);
  const [error, setError]           = useState('');

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
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Save failed');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/70 backdrop-blur-sm z-50 flex items-center justify-center p-4">
      <div
        className="w-full max-w-lg shadow-2xl flex flex-col"
        style={{
          background: 'var(--acm-base)',
          border: '1px solid var(--acm-border)',
          borderRadius: '12px',
        }}
      >
        {/* Modal header */}
        <div
          className="flex items-center justify-between px-5 py-4"
          style={{ borderBottom: '1px solid var(--acm-border)' }}
        >
          <div className="flex items-center gap-2">
            <Settings2 size={15} style={{ color: 'var(--acm-accent)' }} />
            <h2 className="text-[15px] font-semibold" style={{ color: 'var(--acm-fg)' }}>
              Edit Routine
            </h2>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded transition-colors"
            style={{ color: 'var(--acm-fg-4)' }}
          >
            <X size={16} />
          </button>
        </div>

        {/* Modal body */}
        <div className="p-5 space-y-5 max-h-[65vh] overflow-y-auto acm-scroll">

          {error && (
            <div
              className="flex items-center gap-2 px-3 py-2 rounded text-[12px]"
              style={{
                background: 'color-mix(in srgb, var(--acm-err) 10%, transparent)',
                border: '1px solid color-mix(in srgb, var(--acm-err) 30%, transparent)',
                color: 'var(--acm-err)',
              }}
            >
              <span className="dot dot-err shrink-0" />
              {error}
            </div>
          )}

          {/* Apps */}
          <div>
            <span className="label block mb-3">Apps</span>
            <div className="space-y-2 mb-3">
              {apps.map((app, i) => (
                <div
                  key={i}
                  className="rounded-lg p-3 space-y-2"
                  style={{ background: 'var(--acm-card)', border: '1px solid var(--acm-border)' }}
                >
                  <div className="flex items-center gap-2">
                    <span
                      className="w-2 h-2 rounded-full shrink-0"
                      style={{ background: appColorOklch(app.app_name) }}
                    />
                    <span className="flex-1 text-[13px] font-medium truncate" style={{ color: 'var(--acm-fg)' }}>
                      {app.app_name}
                    </span>
                    <span className="mono text-[11px]" style={{ color: 'var(--acm-fg-4)' }}>
                      {app.process_name}
                    </span>
                    <button
                      onClick={() => setApps(p => p.filter((_, idx) => idx !== i))}
                      className="p-0.5 rounded transition-colors"
                      style={{ color: 'var(--acm-fg-4)' }}
                    >
                      <X size={12} />
                    </button>
                  </div>
                  <input
                    className="acm-input w-full text-[12px]"
                    placeholder="Exe path (optional)"
                    value={app.exe_path || ''}
                    onChange={e => setApps(p => p.map((a, idx) => idx === i ? { ...a, exe_path: e.target.value } : a))}
                  />
                </div>
              ))}
              {apps.length === 0 && (
                <p className="text-[12px] italic" style={{ color: 'var(--acm-fg-4)' }}>
                  No apps configured — add one below
                </p>
              )}
            </div>
            {/* Add app row */}
            <div className="space-y-2">
              <div className="flex gap-2">
                <input
                  className="acm-input flex-1 text-[13px]"
                  placeholder="App name (e.g. Chrome)"
                  value={newAppName}
                  onChange={e => setNewAppName(e.target.value)}
                  onKeyDown={e => e.key === 'Enter' && addApp()}
                />
                <input
                  className="acm-input w-28 text-[13px]"
                  placeholder="process"
                  value={newProcName}
                  onChange={e => setNewProcName(e.target.value)}
                  onKeyDown={e => e.key === 'Enter' && addApp()}
                />
                <button onClick={addApp} className="btn-secondary px-2 py-1">
                  <Plus size={13} />
                </button>
              </div>
              <input
                className="acm-input w-full text-[12px]"
                placeholder="Exe path for new app (optional)"
                value={newExePath}
                onChange={e => setNewExePath(e.target.value)}
              />
            </div>
          </div>

          {/* Trigger type */}
          <div>
            <span className="label block mb-3">Trigger type</span>
            <div className="flex gap-2">
              {(['manual', 'time_based'] as const).map(t => (
                <button
                  key={t}
                  onClick={() => setTriggerType(t)}
                  className="px-3 py-1.5 rounded text-[13px] transition-colors"
                  style={
                    triggerType === t
                      ? {
                          background: 'var(--acm-accent-tint)',
                          border: '1px solid color-mix(in srgb, var(--acm-accent) 40%, transparent)',
                          color: 'var(--acm-accent)',
                        }
                      : {
                          background: 'transparent',
                          border: '1px solid var(--acm-border)',
                          color: 'var(--acm-fg-3)',
                        }
                  }
                >
                  {t === 'manual' ? 'Manual' : 'Time-based (auto)'}
                </button>
              ))}
            </div>
          </div>

          {/* Time config */}
          {triggerType === 'time_based' && (
            <div
              className="space-y-4 rounded-lg p-4"
              style={{ background: 'var(--acm-card)', border: '1px solid var(--acm-border)' }}
            >
              <div className="flex gap-4">
                <div>
                  <span className="label block mb-2">Hour (0–23)</span>
                  <input
                    type="number" min={0} max={23}
                    className="acm-input w-20 mono text-[14px]"
                    value={hour}
                    onChange={e => setHour(Math.min(23, Math.max(0, Number(e.target.value))))}
                  />
                </div>
                <div>
                  <span className="label block mb-2">Minute</span>
                  <input
                    type="number" min={0} max={59}
                    className="acm-input w-20 mono text-[14px]"
                    value={minute}
                    onChange={e => setMinute(Math.min(59, Math.max(0, Number(e.target.value))))}
                  />
                </div>
              </div>
              <div>
                <span className="label block mb-2">Days</span>
                <div className="flex gap-1.5">
                  {DAY_SHORT.map((label, i) => (
                    <button
                      key={i}
                      onClick={() => toggleDay(i)}
                      className="w-8 h-8 rounded text-[11px] font-semibold mono transition-colors"
                      style={
                        days.includes(i)
                          ? { background: 'var(--acm-accent)', color: 'oklch(0.18 0.015 80)' }
                          : { background: 'var(--acm-elev)', color: 'var(--acm-fg-4)', border: '1px solid var(--acm-border)' }
                      }
                    >
                      {label}
                    </button>
                  ))}
                </div>
              </div>
              <p className="text-[11px] italic" style={{ color: 'var(--acm-fg-4)' }}>
                Activating this routine creates a cron job at{' '}
                <span className="mono">{String(hour).padStart(2, '0')}:{String(minute).padStart(2, '0')}</span>.
              </p>
            </div>
          )}
        </div>

        {/* Modal footer */}
        <div
          className="flex justify-end gap-2 px-5 py-4"
          style={{ borderTop: '1px solid var(--acm-border)' }}
        >
          <button
            onClick={onClose}
            className="px-4 py-2 text-[13px] rounded transition-colors"
            style={{ color: 'var(--acm-fg-3)' }}
          >
            Cancel
          </button>
          <button
            onClick={handleSave}
            disabled={saving}
            className="btn-primary text-[13px]"
          >
            {saving ? 'Saving…' : 'Save changes'}
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
  const [running, setRunning]       = useState(false);
  const [editing, setEditing]       = useState(false);
  const [nameInput, setNameInput]   = useState(routine.name);
  const [menuOpen, setMenuOpen]     = useState(false);

  const apps     = parseJson<AppInfo[]>(routine.apps, []);
  const isActive = routine.status === 'active';
  const pct      = Math.round(routine.confidence * 100);

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
    <div
      className="acm-card flex overflow-hidden"
      style={{ borderLeft: `4px solid ${statusBorderColor(routine.status)}` }}
    >
      {/* Main body */}
      <div className="flex-1 p-4 space-y-3 min-w-0">

        {/* Name row */}
        <div className="flex items-start justify-between gap-2">
          <div className="flex-1 min-w-0">
            {editing ? (
              <div className="flex items-center gap-2">
                <input
                  className="acm-input flex-1 text-[14px] font-semibold"
                  value={nameInput}
                  onChange={e => setNameInput(e.target.value)}
                  onKeyDown={e => {
                    if (e.key === 'Enter') handleSaveName();
                    if (e.key === 'Escape') { setEditing(false); setNameInput(routine.name); }
                  }}
                  autoFocus
                />
                <button onClick={handleSaveName} style={{ color: 'var(--acm-ok)' }}>
                  <Check size={14} />
                </button>
                <button onClick={() => { setEditing(false); setNameInput(routine.name); }} style={{ color: 'var(--acm-fg-4)' }}>
                  <X size={14} />
                </button>
              </div>
            ) : (
              <div className="flex items-center gap-2 group">
                <h3 className="text-[14px] font-semibold truncate" style={{ color: 'var(--acm-fg)' }}>
                  {routine.name}
                </h3>
                <button
                  onClick={() => setEditing(true)}
                  className="opacity-0 group-hover:opacity-100 transition-opacity"
                  style={{ color: 'var(--acm-fg-4)' }}
                >
                  <Edit2 size={11} />
                </button>
              </div>
            )}

            {/* Status badge + trigger */}
            <div className="flex items-center gap-2 mt-1 flex-wrap">
              <span className="flex items-center gap-1.5">
                <span className={statusDotClass(routine.status)} />
                <span className="mono text-[10px] uppercase tracking-[0.08em]" style={{ color: 'var(--acm-fg-4)' }}>
                  {routine.status}
                </span>
              </span>
              <span style={{ color: 'var(--acm-fg-4)' }} className="text-[10px]">·</span>
              <TriggerInfo routine={routine} />
              {routine.cron_job_id && (
                <>
                  <span style={{ color: 'var(--acm-fg-4)' }} className="text-[10px]">·</span>
                  <span className="mono text-[10px]" style={{ color: 'var(--acm-accent)' }}>auto</span>
                </>
              )}
            </div>
          </div>

          {/* Dots menu */}
          <div className="relative shrink-0">
            <button
              onClick={() => setMenuOpen(v => !v)}
              className="p-1 rounded transition-colors"
              style={{ color: 'var(--acm-fg-4)' }}
            >
              <MoreHorizontal size={15} />
            </button>
            {menuOpen && (
              <div
                className="absolute right-0 top-7 z-30 rounded-lg shadow-xl py-1 min-w-[130px]"
                style={{ background: 'var(--acm-elev)', border: '1px solid var(--acm-border)' }}
                onMouseLeave={() => setMenuOpen(false)}
              >
                <button
                  onClick={() => { onEdit(routine); setMenuOpen(false); }}
                  className="w-full text-left px-3 py-2 text-[12px] transition-colors hover:bg-[var(--acm-card)]"
                  style={{ color: 'var(--acm-fg-2)' }}
                >
                  Edit apps &amp; trigger
                </button>
                <button
                  onClick={() => { onDelete(routine.id); setMenuOpen(false); }}
                  className="w-full text-left px-3 py-2 text-[12px] transition-colors hover:bg-[var(--acm-card)]"
                  style={{ color: 'var(--acm-err)' }}
                >
                  Delete
                </button>
              </div>
            )}
          </div>
        </div>

        {/* Description */}
        {routine.description && (
          <p className="text-[12px] italic leading-snug" style={{ color: 'var(--acm-fg-4)' }}>
            {routine.description}
          </p>
        )}

        {/* App chips */}
        {apps.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {apps.map((app, i) => (
              <span
                key={i}
                className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] mono"
                style={{
                  background: `color-mix(in srgb, ${appColorOklch(app.app_name)} 12%, transparent)`,
                  border: `1px solid color-mix(in srgb, ${appColorOklch(app.app_name)} 25%, transparent)`,
                  color: appColorOklch(app.app_name),
                }}
              >
                {app.app_name}
              </span>
            ))}
          </div>
        )}

        {/* Confidence + runs */}
        <div className="space-y-1.5">
          <div className="flex items-center justify-between">
            <span className="text-[10px]" style={{ color: 'var(--acm-fg-4)' }}>Confidence</span>
            <span className="mono text-[11px]" style={{ color: 'var(--acm-fg-3)' }}>
              {pct}% · {routine.run_count} runs
            </span>
          </div>
          <ConfidenceBar value={routine.confidence} />
        </div>

        {/* Last run + actions */}
        <div
          className="flex items-center gap-2 pt-2"
          style={{ borderTop: '1px solid var(--acm-border)' }}
        >
          <span className="mono text-[10px] flex-1" style={{ color: 'var(--acm-fg-4)' }}>
            Last: {formatDate(routine.last_run)}
          </span>

          <button
            onClick={() => onToggle(routine.id, routine.status)}
            className="btn-secondary text-[11px] px-2.5 py-1"
          >
            {isActive
              ? <><ToggleRight size={13} style={{ color: 'var(--acm-ok)' }} />Deactivate</>
              : <><ToggleLeft size={13} />Activate</>}
          </button>

          <button
            onClick={handleRun}
            disabled={running}
            className="btn-primary text-[11px] px-2.5 py-1"
          >
            <Play size={11} className={running ? 'animate-pulse' : ''} />
            {running ? 'Running…' : 'Run now'}
          </button>
        </div>
      </div>
    </div>
  );
}

// ─── Activity Bar Chart ───────────────────────────────────

function ActivityBar({ apps }: { apps: AppStat[] }) {
  const total = apps.reduce((s, a) => s + a.total_seconds, 0) || 1;
  const topApps = apps.slice(0, 6);
  const otherSecs = apps.slice(6).reduce((s, a) => s + a.total_seconds, 0);

  const segments = [
    ...topApps.map((a, i) => ({
      label: a.app_name,
      pct: (a.total_seconds / total) * 100,
      color: APP_COLORS[i % APP_COLORS.length],
    })),
    ...(otherSecs > 0
      ? [{ label: 'Others', pct: (otherSecs / total) * 100, color: 'oklch(0.42 0.008 255)' }]
      : []),
  ];

  return (
    <div className="space-y-3">
      {/* Horizontal striped bar */}
      <div className="flex h-3 rounded-full overflow-hidden gap-px">
        {segments.map((s, i) => (
          <div
            key={i}
            title={`${s.label} — ${s.pct.toFixed(1)}%`}
            style={{ width: `${s.pct}%`, background: s.color, minWidth: s.pct > 2 ? undefined : '2px' }}
          />
        ))}
      </div>
      {/* Legend */}
      <div className="flex flex-wrap gap-x-4 gap-y-1">
        {segments.map((s, i) => (
          <span key={i} className="flex items-center gap-1.5 text-[11px]" style={{ color: 'var(--acm-fg-3)' }}>
            <span className="w-2 h-2 rounded-full shrink-0" style={{ background: s.color }} />
            {s.label}
          </span>
        ))}
      </div>
    </div>
  );
}

// ─── App Usage Row ────────────────────────────────────────

function AppStatRow({ stat, max }: { stat: AppStat; max: number }) {
  const pct = max > 0 ? (stat.total_seconds / max) * 100 : 0;
  const color = appColorOklch(stat.app_name);
  return (
    <div className="flex items-center gap-3">
      <span className="w-2 h-2 rounded-full shrink-0" style={{ background: color }} />
      <span className="text-[12px] w-28 truncate" style={{ color: 'var(--acm-fg-2)' }}>{stat.app_name}</span>
      <div
        className="flex-1 h-1 rounded-full overflow-hidden"
        style={{ background: 'var(--acm-border)' }}
      >
        <div
          className="h-full rounded-full"
          style={{ width: `${pct}%`, background: color }}
        />
      </div>
      <span className="mono text-[11px] w-10 text-right" style={{ color: 'var(--acm-fg-4)' }}>
        {formatSeconds(stat.total_seconds)}
      </span>
      <span className="mono text-[10px] w-14 text-right" style={{ color: 'var(--acm-fg-4)' }}>
        {stat.session_count} sess
      </span>
    </div>
  );
}

// ─── Main Page ────────────────────────────────────────────

export default function RoutinesPage() {
  const token   = useAuthStore(s => s.token);
  const headers: Record<string, string> = token ? { Authorization: `Bearer ${token}` } : {};

  const [tab, setTab]                   = useState<'routines' | 'activity'>('routines');
  const [routines, setRoutines]         = useState<Routine[]>([]);
  const [stats, setStats]               = useState<ActivityStats>({ apps: [], total_hours: 0, session_count: 0 });
  const [watcher, setWatcher]           = useState<WatcherStatus>({
    running: false, current_app: null, current_title: null,
    sessions_recorded: 0, encrypted: false, key_path: null,
  });
  const [loading, setLoading]           = useState(true);
  const [analyzing, setAnalyzing]       = useState(false);
  const [toast, setToast]               = useState<{ msg: string; ok: boolean } | null>(null);
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
          ? (updated.cron_job_id ? 'Activated — cron job created' : 'Activated')
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
        showToast(
          data.new_routines > 0
            ? `Found ${data.new_routines} new routine(s)`
            : 'No new patterns found',
          data.new_routines > 0,
        );
        fetchAll();
      }
    } finally { setAnalyzing(false); }
  };

  const maxSecs     = stats.apps[0]?.total_seconds ?? 1;
  const activeCount = routines.filter(r => r.status === 'active').length;

  return (
    <AppLayout>
      <div className="flex flex-col min-h-0 p-6 space-y-6">

        {/* Toast */}
        {toast && (
          <div
            className="fixed top-5 right-5 z-50 px-4 py-2.5 rounded-lg text-[13px] font-medium shadow-xl"
            style={{
              background: toast.ok ? 'var(--acm-ok)' : 'var(--acm-err)',
              color: 'oklch(0.14 0.01 160)',
            }}
          >
            {toast.msg}
          </div>
        )}

        {/* Header */}
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div>
            <span className="acm-breadcrumb">/ routines</span>
            <h1 className="text-[22px] font-semibold tracking-[-0.01em]" style={{ color: 'var(--acm-fg)' }}>
              Routines
            </h1>
            <p className="text-[12px] mt-0.5" style={{ color: 'var(--acm-fg-3)' }}>
              {routines.length} detected · {activeCount} active
            </p>
          </div>

          <div className="flex items-center gap-2">
            {/* Watcher pill */}
            <div
              className="flex items-center gap-2 px-3 py-1.5 rounded-full"
              style={{ border: '1px solid var(--acm-border)', background: 'var(--acm-card)' }}
            >
              <span className={`dot dot-${watcher.running ? 'accent acm-pulse' : 'idle'}`} />
              <span className="mono text-[11px]" style={{ color: 'var(--acm-fg-3)' }}>
                Watcher · {watcher.running ? 'running' : 'stopped'}
              </span>
            </div>

            <button
              onClick={fetchAll}
              className="p-2 rounded transition-colors"
              style={{ border: '1px solid var(--acm-border)', color: 'var(--acm-fg-4)' }}
              title="Refresh"
            >
              <RefreshCw size={14} />
            </button>

            <button
              onClick={handleAnalyze}
              disabled={analyzing}
              className="btn-primary text-[13px]"
            >
              {analyzing
                ? <><RefreshCw size={13} className="animate-spin" />Analyzing…</>
                : <><Sparkles size={13} />Analyze now</>}
            </button>
          </div>
        </div>

        {/* Stats row */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <div className="acm-card p-4">
            <span className="label block mb-2">Hours monitored</span>
            <span className="text-[22px] font-semibold mono" style={{ color: 'var(--acm-fg)' }}>
              {stats.total_hours.toFixed(1)}h
            </span>
          </div>
          <div className="acm-card p-4">
            <span className="label block mb-2">Sessions</span>
            <span className="text-[22px] font-semibold mono" style={{ color: 'var(--acm-fg)' }}>
              {stats.session_count}
            </span>
          </div>
          <div className="acm-card p-4">
            <span className="label block mb-2">Routines detected</span>
            <span className="text-[22px] font-semibold mono" style={{ color: 'var(--acm-fg)' }}>
              {routines.length}
            </span>
          </div>
          <div className="acm-card p-4">
            <span className="label block mb-2">Current app</span>
            <p
              className="text-[13px] font-medium truncate mt-1"
              style={{ color: watcher.current_app ? 'var(--acm-fg)' : 'var(--acm-fg-4)' }}
            >
              {watcher.current_app ?? '—'}
            </p>
          </div>
        </div>

        {/* Encryption banner */}
        <div
          className="flex items-start gap-3 p-4 rounded-lg"
          style={
            watcher.encrypted
              ? {
                  background: 'color-mix(in srgb, var(--acm-ok) 8%, transparent)',
                  border: '1px solid color-mix(in srgb, var(--acm-ok) 25%, transparent)',
                }
              : {
                  background: 'color-mix(in srgb, var(--acm-warn) 8%, transparent)',
                  border: '1px solid color-mix(in srgb, var(--acm-warn) 25%, transparent)',
                }
          }
        >
          {watcher.encrypted
            ? <ShieldCheck size={16} className="shrink-0 mt-0.5" style={{ color: 'var(--acm-ok)' }} />
            : <ShieldOff size={16} className="shrink-0 mt-0.5" style={{ color: 'var(--acm-warn)' }} />}
          <div className="min-w-0">
            <p className="text-[13px] font-medium" style={{ color: watcher.encrypted ? 'var(--acm-ok)' : 'var(--acm-warn)' }}>
              {watcher.encrypted
                ? 'Activity data is encrypted'
                : 'Activity data is stored unencrypted'}
            </p>
            <p className="text-[11px] mt-0.5" style={{ color: 'var(--acm-fg-4)' }}>
              {watcher.encrypted
                ? `All app names and window titles are encrypted with a local AES key that never leaves your machine.`
                : 'Restart OpenACM to generate a local encryption key.'}
              {watcher.encrypted && watcher.key_path && (
                <span className="block mono mt-0.5 truncate" style={{ color: 'var(--acm-fg-4)' }}>
                  {watcher.key_path}
                </span>
              )}
            </p>
          </div>
        </div>

        {/* Tabs */}
        <div
          className="flex gap-0.5 p-1 rounded-lg w-fit"
          style={{ background: 'var(--acm-card)', border: '1px solid var(--acm-border)' }}
        >
          {(['routines', 'activity'] as const).map(tabKey => (
            <button
              key={tabKey}
              onClick={() => setTab(tabKey)}
              className="px-4 py-1.5 rounded text-[13px] font-medium transition-colors"
              style={
                tab === tabKey
                  ? { background: 'var(--acm-accent)', color: 'oklch(0.18 0.015 80)' }
                  : { color: 'var(--acm-fg-3)' }
              }
            >
              {tabKey === 'routines' ? 'Routines' : 'App Activity'}
            </button>
          ))}
        </div>

        {/* ── Tab: Routines ─────────────────────────────────── */}
        {tab === 'routines' && (
          loading ? (
            <div className="flex items-center justify-center h-40" style={{ color: 'var(--acm-fg-4)' }}>
              <RefreshCw size={16} className="animate-spin mr-2" /> Loading…
            </div>
          ) : routines.length === 0 ? (
            <div
              className="flex flex-col items-center justify-center py-20 text-center rounded-xl"
              style={{ border: '1px dashed var(--acm-border)' }}
            >
              <CalendarClock size={40} className="mb-4" style={{ color: 'var(--acm-fg-4)' }} />
              <p className="text-[14px] font-medium" style={{ color: 'var(--acm-fg-3)' }}>
                No routines detected yet
              </p>
              <p className="text-[12px] mt-1 max-w-sm" style={{ color: 'var(--acm-fg-4)' }}>
                OpenACM monitors your app usage and detects patterns automatically.
                Check back in a few days, or run the analyzer now.
              </p>
              <button
                onClick={handleAnalyze}
                disabled={analyzing}
                className="btn-primary mt-5 text-[13px]"
              >
                <Sparkles size={13} /> Analyze now
              </button>
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
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

        {/* ── Tab: Activity ─────────────────────────────────── */}
        {tab === 'activity' && (
          <div className="space-y-4">

            {/* Activity summary card */}
            <div className="acm-card p-5 space-y-4">
              <div className="flex items-start justify-between gap-4">
                <div>
                  <span className="label block mb-1">Active apps · today</span>
                  <span className="text-[28px] font-semibold mono" style={{ color: 'var(--acm-fg)' }}>
                    {stats.apps.length}
                  </span>
                </div>
                <div className="text-right">
                  <span className="text-[11px] mono" style={{ color: 'var(--acm-fg-4)' }}>
                    {stats.total_hours.toFixed(1)}h tracked
                  </span>
                  <br />
                  <span className="text-[11px] mono" style={{ color: 'var(--acm-fg-4)' }}>
                    {stats.session_count} sessions
                  </span>
                </div>
              </div>

              {stats.apps.length > 0
                ? <ActivityBar apps={stats.apps} />
                : (
                  <p className="text-[12px] italic text-center py-3" style={{ color: 'var(--acm-fg-4)' }}>
                    No activity recorded yet
                  </p>
                )}

              <p className="mono text-[10px]" style={{ color: 'var(--acm-fg-4)' }}>
                {stats.apps.length} apps tracked · {watcher.encrypted ? 'encrypted' : 'unencrypted'}
              </p>
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">

              {/* Top apps by time */}
              <div className="acm-card p-5">
                <span className="label block mb-4">Top apps by usage</span>
                {stats.apps.length === 0 ? (
                  <p className="text-[12px] text-center py-6" style={{ color: 'var(--acm-fg-4)' }}>
                    No data yet
                  </p>
                ) : (
                  <div className="space-y-3">
                    {stats.apps.slice(0, 12).map((app, i) => (
                      <AppStatRow key={i} stat={app} max={maxSecs} />
                    ))}
                  </div>
                )}
              </div>

              {/* Monitor status */}
              <div className="acm-card p-5">
                <span className="label block mb-4">Monitor status</span>
                <div className="space-y-3">
                  {[
                    { label: 'Status',            value: watcher.running ? 'Active' : 'Inactive', hi: watcher.running },
                    { label: 'Encryption',        value: watcher.encrypted ? 'AES-128 local key' : 'None' },
                    { label: 'Current app',       value: watcher.current_app ?? '—' },
                    { label: 'Window title',      value: watcher.current_title ?? '—', truncate: true },
                    { label: 'Sessions recorded', value: watcher.sessions_recorded.toString() },
                    { label: 'Total hours',       value: `${stats.total_hours.toFixed(1)}h` },
                    { label: 'Total sessions',    value: stats.session_count.toString() },
                  ].map(({ label, value, hi, truncate }) => (
                    <div key={label} className="flex items-center justify-between gap-4">
                      <span className="text-[11px] shrink-0" style={{ color: 'var(--acm-fg-4)' }}>{label}</span>
                      <span
                        className={`text-[12px] font-medium text-right mono ${truncate ? 'truncate max-w-[55%]' : ''}`}
                        style={{ color: hi ? 'var(--acm-ok)' : 'var(--acm-fg-2)' }}
                      >
                        {value}
                      </span>
                    </div>
                  ))}
                </div>
                <div
                  className="mt-4 p-3 rounded-lg"
                  style={{ background: 'var(--acm-elev)', border: '1px solid var(--acm-border)' }}
                >
                  <p className="text-[11px] leading-relaxed" style={{ color: 'var(--acm-fg-4)' }}>
                    The monitor records which app is focused and for how long. After a few days,
                    OpenACM detects patterns and creates routine suggestions automatically.
                  </p>
                </div>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Edit Modal */}
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
