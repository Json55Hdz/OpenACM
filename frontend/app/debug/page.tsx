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
import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';

function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

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

const OUTCOME_CONFIG: Record<string, { color: string; icon: typeof CheckCircle; label: string }> = {
  success:             { color: 'text-green-400',  icon: CheckCircle,  label: 'OK' },
  timeout:             { color: 'text-red-400',    icon: XCircle,      label: 'Timeout' },
  error:               { color: 'text-red-400',    icon: XCircle,      label: 'Error' },
  cancelled:           { color: 'text-yellow-400', icon: AlertTriangle, label: 'Cancelled' },
  empty_response:      { color: 'text-yellow-400', icon: AlertTriangle, label: 'Empty' },
  max_iterations_error:{ color: 'text-orange-400', icon: AlertTriangle, label: 'Max iters' },
  running:             { color: 'text-blue-400',   icon: Loader2,       label: 'Running' },
};

// ─── Context bar ──────────────────────────────────────────────────────────────

function ContextBar({ chars }: { chars: number }) {
  // Warn at 20k, danger at 40k
  const pct = Math.min(100, (chars / 50000) * 100);
  const color = chars > 40000 ? 'bg-red-500' : chars > 20000 ? 'bg-yellow-500' : 'bg-blue-500';
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 bg-slate-800 rounded-full h-1.5">
        <div className={cn('h-1.5 rounded-full', color)} style={{ width: `${pct}%` }} />
      </div>
      <span className={cn('text-xs font-mono', chars > 40000 ? 'text-red-400' : chars > 20000 ? 'text-yellow-400' : 'text-slate-400')}>
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

  return (
    <div className={cn(
      'bg-slate-900 border rounded-xl overflow-hidden',
      trace.outcome === 'timeout' || trace.outcome === 'error' ? 'border-red-700/40' :
      trace.outcome === 'success' ? 'border-slate-800' : 'border-yellow-700/40',
    )}>
      {/* Header */}
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center gap-3 px-4 py-3 hover:bg-slate-800/50 transition-colors text-left"
      >
        <Icon size={16} className={cn(cfg.color, trace.outcome === 'running' && 'animate-spin')} />

        <div className="flex-1 min-w-0">
          <p className="text-sm text-white truncate">{trace.user_message}</p>
          <p className="text-xs text-slate-500">{trace.started_at} · {trace.channel_id}</p>
        </div>

        <div className="flex items-center gap-3 flex-shrink-0">
          <span className={cn('text-xs font-medium', cfg.color)}>{cfg.label}</span>
          <span className="text-xs text-slate-500 flex items-center gap-1">
            <Clock size={11} /> {formatMs(trace.total_elapsed_ms)}
          </span>
          <span className="text-xs text-slate-500">{trace.iterations.length} iter</span>
          {open ? <ChevronUp size={14} className="text-slate-500" /> : <ChevronDown size={14} className="text-slate-500" />}
        </div>
      </button>

      {/* Detail */}
      {open && (
        <div className="border-t border-slate-800 px-4 py-3 space-y-4">
          {trace.iterations.map((iter) => (
            <div key={iter.iteration} className="space-y-2">
              {/* Iteration header */}
              <div className="flex items-center gap-3">
                <span className="text-xs font-medium text-slate-400 bg-slate-800 px-2 py-0.5 rounded">
                  Iter {iter.iteration}
                </span>
                <div className="flex-1">
                  <ContextBar chars={iter.context_chars} />
                </div>
                <span className="text-xs text-slate-500 flex items-center gap-1">
                  <BarChart2 size={11} /> {iter.message_count} msgs
                </span>
                <span className="text-xs text-slate-500">
                  LLM: {formatMs(iter.llm_elapsed_ms)}
                </span>
              </div>

              {iter.error && (
                <div className="bg-red-950/40 border border-red-700/30 rounded px-3 py-2">
                  <p className="text-xs text-red-400 font-mono">{iter.error}</p>
                </div>
              )}

              {/* Tool calls */}
              {iter.tool_calls.length > 0 && (
                <div className="space-y-1 pl-4 border-l border-slate-800">
                  {iter.tool_calls.map((tc, i) => (
                    <div key={i} className="flex items-center gap-2 text-xs">
                      <span className="font-mono text-blue-400">{tc.tool}</span>
                      <span className="text-slate-600">→</span>
                      <span className={cn(
                        'font-mono',
                        tc.error ? 'text-red-400' :
                        tc.truncated ? 'text-yellow-400' : 'text-slate-400',
                      )}>
                        {tc.error ? `error: ${tc.error}` :
                          `${formatChars(tc.result_chars)}ch${tc.truncated ? ' ⚠trunc' : ''}`}
                      </span>
                      <span className="text-slate-600 ml-auto">{formatMs(tc.elapsed_ms)}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          ))}

          {trace.iterations.length === 0 && (
            <p className="text-xs text-slate-600">No iterations captured.</p>
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
      <div className="p-6 lg:p-8">
        <header className="mb-8">
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
            <div>
              <h1 className="text-3xl font-bold text-white flex items-center gap-3">
                <Bug size={28} className={hasErrors ? 'text-red-400' : 'text-slate-400'} />
                Loop Traces
              </h1>
              <p className="text-slate-400 mt-1">
                Every LLM request — iterations, context, tools and timings
              </p>
            </div>

            <div className="flex gap-2">
              <button
                onClick={() => refetch()}
                className="flex items-center gap-2 px-3 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 text-sm transition-colors"
              >
                <RefreshCw size={16} />
                Refresh
              </button>
              <button
                onClick={() => clearMutation.mutate()}
                disabled={clearMutation.isPending}
                className="flex items-center gap-2 px-3 py-2 rounded-lg bg-slate-800 hover:bg-red-900/40 text-slate-400 hover:text-red-400 text-sm transition-colors disabled:opacity-50"
              >
                <Trash2 size={16} />
                Clear
              </button>
            </div>
          </div>
        </header>

        {/* Legend */}
        <div className="flex flex-wrap gap-4 mb-6 text-xs text-slate-500">
          <span><span className="text-slate-300">Context bar:</span> blue=OK · yellow=&gt;20k chars · red=&gt;40k chars</span>
          <span><span className="text-yellow-400">⚠trunc</span> = tool result truncated to 6000 chars before sending to LLM</span>
          <span><span className="text-red-400">Timeout</span> = LLM did not respond in 60s (look for huge context or truncated results)</span>
        </div>

        {/* Traces */}
        {isLoading ? (
          <div className="space-y-3">
            {[1,2,3].map(i => <div key={i} className="h-14 bg-slate-900 rounded-xl border border-slate-800 animate-pulse" />)}
          </div>
        ) : traceList.length === 0 ? (
          <div className="text-center py-20 bg-slate-900 rounded-xl border border-slate-800">
            <Bug size={48} className="mx-auto text-slate-700 mb-4" />
            <h3 className="text-lg font-medium text-slate-400 mb-2">No traces yet</h3>
            <p className="text-sm text-slate-600">Send a message in chat and they will appear here.</p>
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
