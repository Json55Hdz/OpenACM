'use client';

import { useState } from 'react';
import { AppLayout } from '@/components/layout/app-layout';
import { useAPI, useIsAuthenticated } from '@/hooks/use-api';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  Bug,
  Trash2,
  RefreshCw,
  ChevronDown,
  ChevronUp,
  CheckCircle,
  XCircle,
  Clock,
  AlertTriangle,
  Loader2,
  BarChart2,
} from 'lucide-react';

// ─── Types ────────────────────────────────────────────────────────────────────

interface ToolCallTrace {
  tool: string;
  args_chars: number;
  result_chars: number;
  truncated: boolean;
  elapsed_ms: number;
  error: string | null;
}

interface IterationTrace {
  iteration: number;
  message_count: number;
  context_chars: number;
  llm_elapsed_ms: number | null;
  tool_calls: ToolCallTrace[];
  error: string | null;
}

interface BrainTrace {
  id: string;
  started_at: string;
  user_message: string;
  channel_id: string;
  user_id: string;
  iterations: IterationTrace[];
  total_elapsed_ms: number;
  outcome: string;
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function formatMs(ms: number | null) {
  if (ms === null || ms === undefined) return '—';
  if (ms >= 1000) return `${(ms / 1000).toFixed(1)}s`;
  return `${ms}ms`;
}

function formatChars(n: number) {
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`;
  return `${n}`;
}

// Colors as inline style values (all from design tokens)
const OUTCOME_CONFIG: Record<string, {
  color: string;
  icon: typeof CheckCircle;
  label: string;
}> = {
  success:              { color: 'var(--acm-ok)',     icon: CheckCircle,   label: 'OK' },
  timeout:              { color: 'var(--acm-err)',    icon: XCircle,       label: 'Timeout' },
  error:                { color: 'var(--acm-err)',    icon: XCircle,       label: 'Error' },
  cancelled:            { color: 'var(--acm-warn)',   icon: AlertTriangle, label: 'Cancelled' },
  empty_response:       { color: 'var(--acm-warn)',   icon: AlertTriangle, label: 'Empty' },
  max_iterations_error: { color: 'var(--acm-warn)',   icon: AlertTriangle, label: 'Max iters' },
  running:              { color: 'var(--acm-accent)', icon: Loader2,       label: 'Running' },
};

// ─── Context bar ──────────────────────────────────────────────────────────────

function ContextBar({ chars }: { chars: number }) {
  const pct = Math.min(100, (chars / 50000) * 100);
  const barColor = chars > 40000 ? 'var(--acm-err)' : chars > 20000 ? 'var(--acm-warn)' : 'var(--acm-ok)';
  const textColor = chars > 40000 ? 'var(--acm-err)' : chars > 20000 ? 'var(--acm-warn)' : 'var(--acm-fg-4)';
  return (
    <div className="flex items-center gap-2">
      <div
        className="flex-1 rounded-full h-1.5"
        style={{ background: 'var(--acm-elev)' }}
      >
        <div
          className="h-1.5 rounded-full transition-all"
          style={{ width: `${pct}%`, background: barColor }}
        />
      </div>
      <span className="text-xs font-mono" style={{ color: textColor }}>
        {formatChars(chars)}ch
      </span>
    </div>
  );
}

// ─── Single trace card ────────────────────────────────────────────────────────

function TraceCard({ trace }: { trace: BrainTrace }) {
  const [open, setOpen] = useState(trace.outcome !== 'success');
  const cfg = OUTCOME_CONFIG[trace.outcome] || OUTCOME_CONFIG.error;
  const Icon = cfg.icon;

  const borderColor =
    trace.outcome === 'timeout' || trace.outcome === 'error'
      ? 'oklch(0.68 0.13 22 / 0.35)'
      : trace.outcome === 'success'
      ? 'var(--acm-border)'
      : 'oklch(0.82 0.1 78 / 0.35)';

  return (
    <div
      className="overflow-hidden"
      style={{
        background: 'var(--acm-card)',
        border: `1px solid ${borderColor}`,
        borderRadius: 'var(--acm-radius)',
      }}
    >
      {/* Header */}
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center gap-3 px-4 py-3 text-left transition-colors"
        style={{ background: 'transparent' }}
        onMouseEnter={(e) => { (e.currentTarget as HTMLButtonElement).style.background = 'var(--acm-elev)'; }}
        onMouseLeave={(e) => { (e.currentTarget as HTMLButtonElement).style.background = 'transparent'; }}
      >
        <Icon
          size={16}
          style={{
            color: cfg.color,
            ...(trace.outcome === 'running' ? { animation: 'spin 1s linear infinite' } : {}),
          }}
          className={trace.outcome === 'running' ? 'animate-spin' : ''}
        />

        <div className="flex-1 min-w-0">
          <p className="text-sm truncate" style={{ color: 'var(--acm-fg)' }}>
            {trace.user_message}
          </p>
          <p className="text-xs" style={{ color: 'var(--acm-fg-4)' }}>
            {trace.started_at} · {trace.channel_id}
          </p>
        </div>

        <div className="flex items-center gap-3 flex-shrink-0">
          <span className="text-xs font-medium" style={{ color: cfg.color }}>{cfg.label}</span>
          <span className="text-xs flex items-center gap-1" style={{ color: 'var(--acm-fg-4)' }}>
            <Clock size={11} /> {formatMs(trace.total_elapsed_ms)}
          </span>
          <span className="text-xs" style={{ color: 'var(--acm-fg-4)' }}>
            {trace.iterations.length} iter
          </span>
          {open
            ? <ChevronUp size={14} style={{ color: 'var(--acm-fg-4)' }} />
            : <ChevronDown size={14} style={{ color: 'var(--acm-fg-4)' }} />
          }
        </div>
      </button>

      {/* Detail */}
      {open && (
        <div
          className="px-4 py-3 space-y-4"
          style={{ borderTop: '1px solid var(--acm-border)' }}
        >
          {trace.iterations.map((iter) => (
            <div key={iter.iteration} className="space-y-2">
              <div className="flex items-center gap-3">
                <span
                  className="text-xs font-medium px-2 py-0.5 rounded mono"
                  style={{
                    color: 'var(--acm-fg-3)',
                    background: 'var(--acm-elev)',
                    border: '1px solid var(--acm-border)',
                  }}
                >
                  Iter {iter.iteration}
                </span>
                <div className="flex-1">
                  <ContextBar chars={iter.context_chars} />
                </div>
                <span className="text-xs flex items-center gap-1" style={{ color: 'var(--acm-fg-4)' }}>
                  <BarChart2 size={11} /> {iter.message_count} msgs
                </span>
                <span className="text-xs" style={{ color: 'var(--acm-fg-4)' }}>
                  LLM: {formatMs(iter.llm_elapsed_ms)}
                </span>
              </div>

              {iter.error && (
                <div
                  className="px-3 py-2 rounded"
                  style={{
                    background: 'oklch(0.68 0.13 22 / 0.08)',
                    border: '1px solid oklch(0.68 0.13 22 / 0.3)',
                  }}
                >
                  <p className="text-xs mono" style={{ color: 'var(--acm-err)' }}>{iter.error}</p>
                </div>
              )}

              {iter.tool_calls.length > 0 && (
                <div
                  className="space-y-1 pl-4"
                  style={{ borderLeft: '1px solid var(--acm-border)' }}
                >
                  {iter.tool_calls.map((tc, i) => (
                    <div key={i} className="flex items-center gap-2 text-xs">
                      <span className="mono" style={{ color: 'var(--acm-accent)' }}>{tc.tool}</span>
                      <span style={{ color: 'var(--acm-fg-4)' }}>→</span>
                      <span
                        className="mono"
                        style={{
                          color: tc.error
                            ? 'var(--acm-err)'
                            : tc.truncated
                            ? 'var(--acm-warn)'
                            : 'var(--acm-fg-3)',
                        }}
                      >
                        {tc.error
                          ? `error: ${tc.error}`
                          : `${formatChars(tc.result_chars)}ch${tc.truncated ? ' ⚠trunc' : ''}`}
                      </span>
                      <span className="ml-auto" style={{ color: 'var(--acm-fg-4)' }}>
                        {formatMs(tc.elapsed_ms)}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          ))}

          {trace.iterations.length === 0 && (
            <p className="text-xs" style={{ color: 'var(--acm-fg-4)' }}>
              No iterations captured.
            </p>
          )}
        </div>
      )}
    </div>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function DebugPage() {
  const { fetchAPI } = useAPI();
  const isAuthenticated = useIsAuthenticated();
  const queryClient = useQueryClient();

  const { data: traces = [], isLoading, refetch } = useQuery({
    queryKey: ['debug-traces'],
    queryFn: () => fetchAPI('/api/debug/traces?limit=20'),
    enabled: isAuthenticated,
    refetchInterval: 5000,
  });

  const clearMutation = useMutation({
    mutationFn: () => fetchAPI('/api/debug/traces', { method: 'DELETE' }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['debug-traces'] }),
  });

  const traceList = (traces as BrainTrace[]);
  const hasErrors = traceList.some(t => t.outcome === 'timeout' || t.outcome === 'error');

  return (
    <AppLayout>
      <div className="p-6 lg:p-8" style={{ background: 'var(--acm-base)', minHeight: '100%' }}>
        <header className="mb-8">
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
            <div>
              <span className="acm-breadcrumb">OpenACM</span>
              <h1
                className="text-2xl font-bold flex items-center gap-3"
                style={{ color: 'var(--acm-fg)' }}
              >
                <Bug size={24} style={{ color: hasErrors ? 'var(--acm-err)' : 'var(--acm-fg-3)' }} />
                Loop Traces
              </h1>
              <p className="mt-1" style={{ color: 'var(--acm-fg-3)', fontSize: 14 }}>
                Every LLM request — iterations, context, tools and timings
              </p>
            </div>

            <div className="flex gap-2">
              <button
                onClick={() => refetch()}
                className="btn-secondary flex items-center gap-2 text-sm"
              >
                <RefreshCw size={15} />
                Refresh
              </button>
              <button
                onClick={() => clearMutation.mutate()}
                disabled={clearMutation.isPending}
                className="btn-secondary flex items-center gap-2 text-sm"
                style={{ color: clearMutation.isPending ? undefined : 'var(--acm-fg-3)' }}
                onMouseEnter={(e) => { (e.currentTarget as HTMLButtonElement).style.color = 'var(--acm-err)'; (e.currentTarget as HTMLButtonElement).style.borderColor = 'var(--acm-err)'; }}
                onMouseLeave={(e) => { (e.currentTarget as HTMLButtonElement).style.color = ''; (e.currentTarget as HTMLButtonElement).style.borderColor = ''; }}
              >
                <Trash2 size={15} />
                Clear
              </button>
            </div>
          </div>
        </header>

        {/* Legend */}
        <div className="flex flex-wrap gap-4 mb-6 text-xs" style={{ color: 'var(--acm-fg-4)' }}>
          <span>
            <span style={{ color: 'var(--acm-fg-2)' }}>Context bar:</span>{' '}
            <span style={{ color: 'var(--acm-ok)' }}>green</span>=OK ·{' '}
            <span style={{ color: 'var(--acm-warn)' }}>amber</span>={'>'}20k chars ·{' '}
            <span style={{ color: 'var(--acm-err)' }}>red</span>={'>'}40k chars
          </span>
          <span>
            <span style={{ color: 'var(--acm-warn)' }}>⚠trunc</span>
            {' '}= tool result truncated to 6000 chars before sending to LLM
          </span>
          <span>
            <span style={{ color: 'var(--acm-err)' }}>Timeout</span>
            {' '}= LLM did not respond in 60s (look for huge context or truncated results)
          </span>
        </div>

        {/* Traces */}
        {isLoading ? (
          <div className="space-y-3">
            {[1, 2, 3].map(i => (
              <div
                key={i}
                className="h-14 rounded-xl animate-pulse"
                style={{ background: 'var(--acm-card)', border: '1px solid var(--acm-border)' }}
              />
            ))}
          </div>
        ) : traceList.length === 0 ? (
          <div
            className="text-center py-20 rounded-xl"
            style={{ background: 'var(--acm-card)', border: '1px solid var(--acm-border)' }}
          >
            <Bug size={48} className="mx-auto mb-4" style={{ color: 'var(--acm-border-strong)' }} />
            <h3 className="text-lg font-medium mb-2" style={{ color: 'var(--acm-fg-3)' }}>
              No traces yet
            </h3>
            <p className="text-sm" style={{ color: 'var(--acm-fg-4)' }}>
              Send a message in chat and they will appear here.
            </p>
          </div>
        ) : (
          <div className="space-y-3">
            {traceList.map((trace) => (
              <TraceCard key={trace.id} trace={trace} />
            ))}
          </div>
        )}
      </div>
    </AppLayout>
  );
}
