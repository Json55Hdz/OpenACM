'use client';

import { useEffect, useState, useCallback } from 'react';
import { AppLayout } from '@/components/layout/app-layout';
import { useStats, useActivityHistory, useMediaFiles, useDetailedStats } from '@/hooks/use-api';
import { useDashboardStore } from '@/stores/dashboard-store';
import { ActivityChart } from '@/components/dashboard/activity-chart';
import { StatsCard } from '@/components/dashboard/stats-card';
import { ChannelList } from '@/components/dashboard/channel-list';
import { EventLog } from '@/components/dashboard/event-log';
import {
  MessageSquare,
  Hash,
  Wrench,
  Radio,
  Download,
  FileImage,
  File,
  Box,
  Cpu,
  TrendingUp,
  Info,
  ArrowUp,
  ArrowDown,
  DollarSign,
  Zap,
  BarChart2,
  Calendar,
  ChevronDown,
  X,
  HelpCircle,
} from 'lucide-react';
import { useAuthStore } from '@/stores/auth-store';

function fileIcon(ext: string) {
  if (['.png', '.jpg', '.jpeg', '.gif', '.webp'].includes(ext))
    return <FileImage size={16} color="var(--acm-accent)" />;
  if (['.glb', '.gltf', '.obj', '.stl', '.blend'].includes(ext))
    return <Box size={16} color="var(--acm-fg-3)" />;
  return <File size={16} color="var(--acm-fg-4)" />;
}

function formatSize(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatTokens(v: number) {
  if (v >= 1_000_000) return `${(v / 1_000_000).toFixed(2)}M`;
  if (v >= 1000) return `${(v / 1000).toFixed(1)}K`;
  return String(v);
}

function SectionHeader({ title, description }: { title: string; description?: string }) {
  return (
    <div className="mb-4">
      <h3 className="text-sm font-semibold" style={{ color: 'var(--acm-fg)' }}>{title}</h3>
      {description && (
        <p className="text-xs mt-0.5" style={{ color: 'var(--acm-fg-4)' }}>{description}</p>
      )}
    </div>
  );
}

function MiniStatRow({ label, value, accent }: { label: string; value: string; accent?: string }) {
  return (
    <div
      className="flex items-center justify-between py-1.5"
      style={{ borderBottom: '1px solid var(--acm-border)' }}
    >
      <span className="text-xs" style={{ color: 'var(--acm-fg-4)' }}>{label}</span>
      <span
        className="mono text-xs font-medium"
        style={{ color: accent ? 'var(--acm-accent)' : 'var(--acm-fg-2)' }}
      >
        {value}
      </span>
    </div>
  );
}

// ── Date range presets ──────────────────────────────────────────────────────
type DatePreset = 'today' | '7d' | '30d' | '90d' | 'all' | 'custom';

function toISODate(d: Date): string {
  return d.toISOString().slice(0, 10);
}

function presetDates(preset: DatePreset): { from: string | undefined; to: string | undefined } {
  const today = toISODate(new Date());
  if (preset === 'today') return { from: today, to: today };
  if (preset === '7d') {
    const d = new Date(); d.setDate(d.getDate() - 6);
    return { from: toISODate(d), to: today };
  }
  if (preset === '30d') {
    const d = new Date(); d.setDate(d.getDate() - 29);
    return { from: toISODate(d), to: today };
  }
  if (preset === '90d') {
    const d = new Date(); d.setDate(d.getDate() - 89);
    return { from: toISODate(d), to: today };
  }
  return { from: undefined, to: undefined }; // all / custom
}

const PRESET_LABELS: Record<DatePreset, string> = {
  today: 'Hoy',
  '7d': 'Últimos 7 días',
  '30d': 'Últimos 30 días',
  '90d': 'Últimos 90 días',
  all: 'Todo el tiempo',
  custom: 'Personalizado',
};

function DateRangePicker({
  dateFrom, dateTo, onApply,
}: {
  dateFrom: string | undefined;
  dateTo: string | undefined;
  onApply: (from: string | undefined, to: string | undefined) => void;
}) {
  const [open, setOpen] = useState(false);
  const [preset, setPreset] = useState<DatePreset>('all');
  const [customFrom, setCustomFrom] = useState('');
  const [customTo, setCustomTo] = useState('');

  const activeLabel = dateFrom
    ? `${dateFrom} → ${dateTo || 'hoy'}`
    : PRESET_LABELS.all;

  const selectPreset = (p: DatePreset) => {
    setPreset(p);
    if (p !== 'custom') {
      const { from, to } = presetDates(p);
      onApply(from, to);
      setOpen(false);
    }
  };

  const applyCustom = () => {
    onApply(customFrom || undefined, customTo || undefined);
    setOpen(false);
  };

  const clearFilter = (e: React.MouseEvent) => {
    e.stopPropagation();
    setPreset('all');
    onApply(undefined, undefined);
  };

  return (
    <div className="relative">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-2 px-3 py-1.5 text-sm transition-colors"
        style={{
          background: 'var(--acm-elev)',
          border: '1px solid var(--acm-border)',
          borderRadius: 'var(--acm-radius)',
          color: 'var(--acm-fg-2)',
        }}
      >
        <Calendar size={14} color="var(--acm-fg-4)" />
        <span className="max-w-[180px] truncate">{activeLabel}</span>
        {dateFrom && (
          <X
            size={12}
            color="var(--acm-fg-4)"
            className="ml-1 hover:opacity-80"
            onClick={clearFilter}
          />
        )}
        <ChevronDown size={12} color="var(--acm-fg-4)" />
      </button>

      {open && (
        <div
          className="absolute right-0 top-full mt-1 z-50 w-64 p-3 shadow-xl"
          style={{
            background: 'var(--acm-card)',
            border: '1px solid var(--acm-border-strong)',
            borderRadius: 'var(--acm-radius)',
          }}
        >
          <p className="label mb-2 px-1">Rango de fechas</p>
          <div className="space-y-0.5 mb-3">
            {(['today', '7d', '30d', '90d', 'all'] as DatePreset[]).map((p) => {
              const isActive = preset === p && !dateFrom === (p === 'all');
              return (
                <button
                  key={p}
                  onClick={() => selectPreset(p)}
                  className="w-full text-left px-3 py-1.5 text-sm transition-colors"
                  style={{
                    borderRadius: 'var(--acm-radius)',
                    background: isActive ? 'var(--acm-accent)' : 'transparent',
                    color: isActive ? 'oklch(0.18 0.015 80)' : 'var(--acm-fg-2)',
                    fontWeight: isActive ? 600 : 400,
                  }}
                >
                  {PRESET_LABELS[p]}
                </button>
              );
            })}
            <button
              onClick={() => setPreset('custom')}
              className="w-full text-left px-3 py-1.5 text-sm transition-colors"
              style={{
                borderRadius: 'var(--acm-radius)',
                background: preset === 'custom' ? 'var(--acm-accent)' : 'transparent',
                color: preset === 'custom' ? 'oklch(0.18 0.015 80)' : 'var(--acm-fg-2)',
                fontWeight: preset === 'custom' ? 600 : 400,
              }}
            >
              {PRESET_LABELS.custom}
            </button>
          </div>

          {preset === 'custom' && (
            <div
              className="space-y-2 pt-3"
              style={{ borderTop: '1px solid var(--acm-border)' }}
            >
              <div>
                <label className="label mb-1 block">Desde</label>
                <input
                  type="date"
                  value={customFrom}
                  onChange={(e) => setCustomFrom(e.target.value)}
                  className="acm-input"
                />
              </div>
              <div>
                <label className="label mb-1 block">Hasta</label>
                <input
                  type="date"
                  value={customTo}
                  onChange={(e) => setCustomTo(e.target.value)}
                  className="acm-input"
                />
              </div>
              <button onClick={applyCustom} className="btn-primary w-full justify-center">
                Aplicar
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function ModelBreakdownTable({ models }: { models: Array<{
  model: string;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  cost: number;
  requests: number;
  avg_elapsed_ms: number;
}> }) {
  if (!models || models.length === 0) {
    return (
      <p className="text-xs text-center py-4" style={{ color: 'var(--acm-fg-4)' }}>
        No model usage recorded yet
      </p>
    );
  }
  const maxTokens = Math.max(...models.map(m => m.total_tokens), 1);
  return (
    <div className="space-y-3">
      {models.map((m) => (
        <div key={m.model} className="space-y-1">
          <div className="flex items-center justify-between">
            <span
              className="mono text-xs truncate max-w-[200px]"
              style={{ color: 'var(--acm-fg-2)' }}
            >
              {m.model}
            </span>
            <div className="flex items-center gap-3 text-xs" style={{ color: 'var(--acm-fg-4)' }}>
              <span>{m.requests} calls</span>
              {m.cost > 0 ? (
                <span className="mono" style={{ color: 'var(--acm-accent)' }}>
                  ${m.cost.toFixed(4)}
                </span>
              ) : (
                <span
                  className="relative group flex items-center gap-0.5 cursor-help"
                  style={{ color: 'var(--acm-fg-4)' }}
                >
                  <HelpCircle size={11} />
                  <span>no price</span>
                  <span
                    className="pointer-events-none absolute bottom-full right-0 mb-1.5 w-56 px-3 py-2 text-xs leading-snug opacity-0 group-hover:opacity-100 transition-opacity z-50 shadow-lg"
                    style={{
                      background: 'var(--acm-elev)',
                      border: '1px solid var(--acm-border-strong)',
                      borderRadius: 'var(--acm-radius)',
                      color: 'var(--acm-fg-2)',
                    }}
                  >
                    <span
                      className="font-semibold block mb-1"
                      style={{ color: 'var(--acm-fg)' }}
                    >
                      No pricing data
                    </span>
                    <span style={{ color: 'var(--acm-fg-3)' }}>
                      &ldquo;{m.model}&rdquo; isn&apos;t in LiteLLM&apos;s pricing database yet — cost can&apos;t be calculated automatically for this model.
                    </span>
                  </span>
                </span>
              )}
            </div>
          </div>
          {/* Token bars: ok = input, accent = output */}
          <div className="flex gap-1 h-1.5">
            <div
              className="rounded-full"
              style={{
                background: 'var(--acm-ok)',
                opacity: 0.7,
                width: `${(m.prompt_tokens / (m.total_tokens || 1)) * (m.total_tokens / maxTokens) * 100}%`,
              }}
              title={`Input: ${formatTokens(m.prompt_tokens)}`}
            />
            <div
              className="rounded-full"
              style={{
                background: 'var(--acm-accent)',
                opacity: 0.6,
                width: `${(m.completion_tokens / (m.total_tokens || 1)) * (m.total_tokens / maxTokens) * 100}%`,
              }}
              title={`Output: ${formatTokens(m.completion_tokens)}`}
            />
          </div>
          <div className="flex gap-4 text-[10px]">
            <span className="mono" style={{ color: 'var(--acm-ok)', opacity: 0.8 }}>
              ↑ {formatTokens(m.prompt_tokens)}
            </span>
            <span className="mono" style={{ color: 'var(--acm-accent)', opacity: 0.7 }}>
              ↓ {formatTokens(m.completion_tokens)}
            </span>
            {m.avg_elapsed_ms > 0 && (
              <span className="mono" style={{ color: 'var(--acm-fg-4)' }}>
                {(m.avg_elapsed_ms / 1000).toFixed(1)}s avg
              </span>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}

export default function DashboardPage() {
  const [dateFrom, setDateFrom] = useState<string | undefined>(undefined);
  const [dateTo, setDateTo] = useState<string | undefined>(undefined);

  const handleDateApply = useCallback((from: string | undefined, to: string | undefined) => {
    setDateFrom(from);
    setDateTo(to);
  }, []);

  const { data: stats, isLoading: statsLoading } = useStats();
  const { data: history, isLoading: historyLoading } = useActivityHistory();
  const { data: mediaFiles } = useMediaFiles();
  const { data: detailed } = useDetailedStats(dateFrom, dateTo);
  const { setStats, setOnline } = useDashboardStore();
  const token = useAuthStore((s) => s.token);

  useEffect(() => {
    if (stats) {
      setStats({
        messagesToday: stats.messages_today || 0,
        tokensToday: stats.tokens_today || 0,
        toolCalls: stats.total_tool_calls || 0,
        activeConversations: stats.active_conversations || 0,
        currentModel: stats.current_model || 'Unknown',
      });
      setOnline(true);
    }
  }, [stats, setStats, setOnline]);

  const totalTokensAllTime = Math.max(
    stats?.total_tokens || 0,
    stats?.total_requests !== undefined ? 0 : 0,
  );

  return (
    <AppLayout>
      <div className="p-6 lg:p-8" style={{ background: 'var(--acm-base)', minHeight: '100%' }}>

        {/* ── Header ── */}
        <header className="mb-8">
          <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-4">
            <div>
              <span className="acm-breadcrumb">OpenACM</span>
              <h1 className="text-2xl font-bold" style={{ color: 'var(--acm-fg)' }}>
                Dashboard
              </h1>
              <p className="text-sm mt-1" style={{ color: 'var(--acm-fg-3)' }}>
                Real-time activity monitor and usage statistics
              </p>
            </div>

            {/* Active model badge */}
            <div className="flex items-center gap-3">
              <div
                className="flex items-center gap-2.5 px-4 py-2"
                style={{
                  background: 'var(--acm-card)',
                  border: '1px solid var(--acm-border)',
                  borderRadius: '99px',
                }}
              >
                <Cpu size={15} color="var(--acm-accent)" />
                <div className="text-right">
                  <div
                    className="text-sm font-medium leading-none"
                    style={{ color: 'var(--acm-fg-2)' }}
                  >
                    {stats?.current_model || 'Loading...'}
                  </div>
                  {stats?.current_provider && (
                    <div className="text-xs mt-0.5" style={{ color: 'var(--acm-fg-4)' }}>
                      {stats.current_provider}
                    </div>
                  )}
                </div>
              </div>
            </div>
          </div>
        </header>

        {/* ── Today's Activity ── */}
        <div className="mb-8">
          <div className="flex items-center gap-2 mb-4">
            <TrendingUp size={14} color="var(--acm-fg-4)" />
            <span className="label">Today&apos;s Activity</span>
            <span className="text-xs" style={{ color: 'var(--acm-fg-4)' }}>— resets at midnight</span>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            <StatsCard
              icon={<MessageSquare size={22} color="var(--acm-accent)" />}
              accentClass="bg-amber-500/10"
              value={stats?.messages_today || 0}
              label="Messages Today"
              subtitle="LLM requests and responses sent since midnight"
              secondary={stats?.total_messages}
              secondaryLabel="All time"
              loading={statsLoading}
            />
            <StatsCard
              icon={<Hash size={22} color="var(--acm-accent)" />}
              accentClass="bg-amber-500/10"
              value={stats?.tokens_today || 0}
              label="Tokens Today"
              subtitle="Prompt + completion tokens consumed today (input + output)"
              secondary={totalTokensAllTime}
              secondaryLabel="All time"
              loading={statsLoading}
              formatter={formatTokens}
            />
            <StatsCard
              icon={<Wrench size={22} color="var(--acm-accent)" />}
              accentClass="bg-amber-500/10"
              value={stats?.total_tool_calls || 0}
              label="Tool Executions"
              subtitle="Total tool calls made by the AI since installation (run_command, browser, etc.)"
              loading={statsLoading}
            />
            <StatsCard
              icon={<Radio size={22} color="var(--acm-fg-3)" />}
              accentClass="bg-amber-500/10"
              value={stats?.active_conversations || 0}
              label="Active Sessions"
              subtitle="Unique user + channel combinations with messages in the last 24 hours"
              loading={statsLoading}
            />
          </div>
        </div>

        {/* ── Token Analytics ── */}
        <div className="mb-8">
          <div className="flex items-center justify-between gap-2 mb-4">
            <div className="flex items-center gap-2">
              <BarChart2 size={14} color="var(--acm-fg-4)" />
              <span className="label">Token Analytics</span>
              {!dateFrom && (
                <span className="text-xs" style={{ color: 'var(--acm-fg-4)' }}>
                  — all-time totals
                </span>
              )}
              {dateFrom && (
                <span className="mono text-xs" style={{ color: 'var(--acm-accent)', opacity: 0.8 }}>
                  — {dateFrom}{dateTo && dateTo !== dateFrom ? ` → ${dateTo}` : ''}
                </span>
              )}
            </div>
            <DateRangePicker dateFrom={dateFrom} dateTo={dateTo} onApply={handleDateApply} />
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            <StatsCard
              icon={<ArrowUp size={22} color="var(--acm-fg-3)" />}
              accentClass="bg-amber-500/10"
              value={detailed?.totals?.prompt_tokens || 0}
              label="Input Tokens"
              subtitle={`Tokens enviados al LLM (mensajes + contexto del sistema)${dateFrom ? '' : ' — todo el tiempo'}`}
              secondary={dateFrom ? detailed?.today?.prompt_tokens : undefined}
              secondaryLabel="Hoy"
              loading={!detailed}
              formatter={formatTokens}
            />
            <StatsCard
              icon={<ArrowDown size={22} color="var(--acm-fg-3)" />}
              accentClass="bg-amber-500/10"
              value={detailed?.totals?.completion_tokens || 0}
              label="Output Tokens"
              subtitle={`Tokens generados por el LLM (respuestas + tool calls)${dateFrom ? '' : ' — todo el tiempo'}`}
              secondary={dateFrom ? detailed?.today?.completion_tokens : undefined}
              secondaryLabel="Hoy"
              loading={!detailed}
              formatter={formatTokens}
            />
            <StatsCard
              icon={<DollarSign size={22} color="var(--acm-accent)" />}
              accentClass="bg-amber-500/10"
              value={detailed?.totals?.cost || 0}
              label="Costo estimado"
              subtitle="Estimado en USD basado en precios del modelo (modelos locales = $0)"
              secondary={dateFrom ? detailed?.today?.cost : undefined}
              secondaryLabel="Hoy"
              loading={!detailed}
              formatter={(v) => v === 0 ? '$0.00' : `$${Number(v).toFixed(4)}`}
            />
            <StatsCard
              icon={<Zap size={22} color="var(--acm-fg-3)" />}
              accentClass="bg-amber-500/10"
              value={detailed?.totals?.requests || 0}
              label="LLM Calls"
              subtitle="Llamadas al API del LLM (cada iteración del tool loop = 1 llamada)"
              secondary={dateFrom ? detailed?.today?.requests : undefined}
              secondaryLabel="Hoy"
              loading={!detailed}
            />
          </div>
        </div>

        {/* ── Dashboard Grid ── */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">

          {/* Activity Chart — 2/3 width */}
          <div className="acm-card lg:col-span-2 p-6">
            <SectionHeader
              title="14-Day Activity History"
              description="Blue bars = number of LLM API calls per day. Purple line = total tokens consumed (input + output, in thousands)."
            />
            <ActivityChart data={history || []} loading={historyLoading} />
            {!historyLoading && history && history.length > 0 && (
              <div className="mt-3 flex items-start gap-1.5 text-xs" style={{ color: 'var(--acm-fg-4)' }}>
                <Info size={11} color="var(--acm-fg-4)" className="mt-0.5 flex-shrink-0" />
                <span>
                  Tokens are logged per LLM call. High token days usually mean complex multi-step tasks with many tool iterations.
                </span>
              </div>
            )}
          </div>

          {/* Right column: Channels + Model Breakdown */}
          <div className="flex flex-col gap-6">
            <div className="acm-card p-6">
              <SectionHeader
                title="Active Channels"
                description="Interfaces where the AI is reachable."
              />
              <ChannelList />
            </div>

            <div className="acm-card p-6">
              <SectionHeader
                title="By Model"
                description={`Token usage and cost per model. Green = input, amber = output.${dateFrom ? ` · ${dateFrom}${dateTo && dateTo !== dateFrom ? ` → ${dateTo}` : ''}` : ''}`}
              />
              <ModelBreakdownTable models={detailed?.by_model || []} />
              {detailed?.totals && (
                <div className="mt-4 pt-3" style={{ borderTop: '1px solid var(--acm-border)' }}>
                  <MiniStatRow
                    label="Input / Output ratio"
                    value={`${((detailed.totals.prompt_tokens / Math.max(detailed.totals.total_tokens, 1)) * 100).toFixed(0)}% / ${((detailed.totals.completion_tokens / Math.max(detailed.totals.total_tokens, 1)) * 100).toFixed(0)}%`}
                  />
                  <MiniStatRow
                    label="Avg output per call"
                    value={detailed.totals.requests > 0
                      ? `${formatTokens(Math.round(detailed.totals.completion_tokens / detailed.totals.requests))} tokens`
                      : '—'}
                  />
                  <MiniStatRow
                    label="Avg cost per request"
                    value={detailed.totals.requests > 0
                      ? `$${(detailed.totals.cost / detailed.totals.requests).toFixed(5)}`
                      : '$0.00'}
                    accent="var(--acm-accent)"
                  />
                </div>
              )}
            </div>
          </div>

          {/* Live Events — full width */}
          <div className="acm-card lg:col-span-3 p-6">
            <SectionHeader
              title="Live Event Stream"
              description="Real-time feed of system events: messages received, LLM calls, tool executions, and results. Newest events appear at the top."
            />
            <EventLog />
          </div>

          {/* File Browser — full width */}
          <div className="acm-card lg:col-span-3 p-6">
            <SectionHeader
              title={`Generated Files  (${mediaFiles?.length ?? 0})`}
              description="Files created by the AI during tool use — screenshots, Python plots, PDFs, 3D models, and other exports. All files are stored locally in the workspace folder."
            />
            {!mediaFiles || mediaFiles.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-10 text-center gap-2">
                <File size={32} color="var(--acm-fg-4)" />
                <p className="text-sm" style={{ color: 'var(--acm-fg-3)' }}>No files yet</p>
                <p className="text-xs max-w-sm" style={{ color: 'var(--acm-fg-4)' }}>
                  When the AI uses tools like{' '}
                  <span className="mono" style={{ color: 'var(--acm-fg-3)' }}>screenshot</span>,{' '}
                  <span className="mono" style={{ color: 'var(--acm-fg-3)' }}>run_python</span>{' '}
                  (with matplotlib), or generates documents, the files will appear here for download.
                </p>
              </div>
            ) : (
              <div className="overflow-x-auto acm-scroll">
                <table className="w-full text-sm">
                  <thead>
                    <tr
                      className="text-left"
                      style={{ borderBottom: '1px solid var(--acm-border)' }}
                    >
                      <th
                        className="pb-2 pr-4 font-medium label"
                        style={{ color: 'var(--acm-fg-4)' }}
                      >
                        File
                      </th>
                      <th
                        className="pb-2 pr-4 font-medium label"
                        style={{ color: 'var(--acm-fg-4)' }}
                      >
                        Size
                      </th>
                      <th
                        className="pb-2 pr-4 font-medium label"
                        style={{ color: 'var(--acm-fg-4)' }}
                      >
                        Modified
                      </th>
                      <th className="pb-2 font-medium" />
                    </tr>
                  </thead>
                  <tbody>
                    {mediaFiles.map((f) => (
                      <tr
                        key={f.name}
                        className="transition-colors"
                        style={{ borderBottom: '1px solid var(--acm-border)' }}
                        onMouseEnter={(e) => {
                          (e.currentTarget as HTMLTableRowElement).style.background =
                            'var(--acm-elev)';
                        }}
                        onMouseLeave={(e) => {
                          (e.currentTarget as HTMLTableRowElement).style.background = '';
                        }}
                      >
                        <td className="py-2.5 pr-4">
                          <div className="flex items-center gap-2">
                            {fileIcon(f.ext)}
                            <span
                              className="mono text-xs truncate max-w-xs"
                              style={{ color: 'var(--acm-fg-2)' }}
                            >
                              {f.name}
                            </span>
                          </div>
                        </td>
                        <td className="py-2.5 pr-4 mono text-xs" style={{ color: 'var(--acm-fg-3)' }}>
                          {formatSize(f.size)}
                        </td>
                        <td className="py-2.5 pr-4 mono text-xs" style={{ color: 'var(--acm-fg-3)' }}>
                          {new Date(f.modified).toLocaleString()}
                        </td>
                        <td className="py-2.5">
                          <a
                            href={`/api/media/${f.name}?download=true&token=${token}`}
                            download={f.name}
                            className="btn-secondary"
                            style={{ fontSize: '12px', padding: '5px 10px' }}
                          >
                            <Download size={11} />
                            Download
                          </a>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

        </div>
      </div>
    </AppLayout>
  );
}
