'use client';

import { useState } from 'react';
import { Clock, CheckCircle2, AlertCircle, Loader2, ChevronDown, ChevronUp, HelpCircle } from 'lucide-react';
import { useAPI } from '@/hooks/use-api';
import { Task, TASK_DOT } from './shared';

export function TaskRow({ task, swarmId, onAction }: { task: Task; swarmId: number; onAction?: () => void }) {
  const [expanded, setExpanded] = useState(false);
  const [mode, setMode] = useState<null | 'retry' | 'complete'>(null);
  const [notes, setNotes] = useState('');
  const [manualResult, setManualResult] = useState('');
  const [loading, setLoading] = useState(false);
  const { fetchAPI } = useAPI();

  const handleRetry = async () => {
    setLoading(true);
    try {
      await fetchAPI(`/api/swarms/${swarmId}/tasks/${task.id}/retry`, {
        method: 'POST',
        body: JSON.stringify({ user_notes: notes }),
      });
      setMode(null); setNotes('');
      onAction?.();
    } catch (e) { /* ignore, fetchAPI toasts */ }
    setLoading(false);
  };

  const handleComplete = async () => {
    if (!manualResult.trim()) return;
    setLoading(true);
    try {
      await fetchAPI(`/api/swarms/${swarmId}/tasks/${task.id}/complete`, {
        method: 'POST',
        body: JSON.stringify({ result: manualResult }),
      });
      setMode(null); setManualResult('');
      onAction?.();
    } catch (e) { /* ignore */ }
    setLoading(false);
  };

  const isFailed = task.status === 'failed';

  return (
    <div className={`border rounded-lg p-3 transition-colors ${
      task.status === 'running'  ? 'border-l-2 border-l-[var(--acm-accent)] border-[var(--acm-border)]' :
      task.status === 'waiting'  ? 'border-l-2 border-l-[var(--acm-warn)] border-[var(--acm-border)]' :
      isFailed                   ? 'border-l-2 border-l-[var(--acm-err)] border-[var(--acm-border)]' :
      task.status === 'completed'? 'border-[var(--acm-border)] bg-[var(--acm-card)]' :
                                   'border-[var(--acm-border)]'
    }`}>
      <div className="flex items-start gap-3">
        <div className="flex items-center gap-1.5 flex-shrink-0 pt-0.5">
          <span className={`dot ${TASK_DOT[task.status] || 'dot-idle'}`} />
          {task.status === 'running' && <Loader2 size={10} className="animate-spin text-[var(--acm-accent)]" />}
          {task.status === 'completed' && <CheckCircle2 size={10} className="text-[var(--acm-ok)]" />}
          {task.status === 'failed' && <AlertCircle size={10} className="text-[var(--acm-err)]" />}
          {task.status === 'pending' && <Clock size={10} className="text-[var(--acm-fg-4)]" />}
          {task.status === 'waiting' && <HelpCircle size={10} className="text-[var(--acm-warn)]" />}
        </div>
        <div className="flex-1 min-w-0">
          <p className="text-[var(--acm-fg)] text-[13px] font-medium">{task.title}</p>
          {task.worker_name && (
            <p className="text-[var(--acm-fg-4)] mono text-[11px] mt-0.5">→ {task.worker_name}</p>
          )}
        </div>
        <div className="flex items-center gap-1 flex-shrink-0">
          {isFailed && mode === null && (
            <>
              <button
                onClick={() => setMode('retry')}
                className="text-[11px] px-2 py-0.5 rounded border border-[var(--acm-warn)] text-[var(--acm-warn)] hover:bg-[oklch(0.84_0.16_82/0.08)] transition-colors"
              >
                Retry
              </button>
              <button
                onClick={() => setMode('complete')}
                className="text-[11px] px-2 py-0.5 rounded border border-[var(--acm-ok)] text-[var(--acm-ok)] hover:bg-[oklch(0.55_0.12_160/0.1)] transition-colors"
              >
                Complete
              </button>
            </>
          )}
          {task.result && (
            <button
              onClick={() => setExpanded(v => !v)}
              className="text-[var(--acm-fg-4)] hover:text-[var(--acm-fg-3)] ml-1 transition-colors"
            >
              {expanded ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
            </button>
          )}
        </div>
      </div>

      {expanded && task.result && (
        <div className="mt-2 text-[11px] text-[var(--acm-fg-3)] bg-[var(--acm-elev)] border border-[var(--acm-border)] rounded-lg p-3 max-h-64 overflow-auto whitespace-pre-wrap mono">
          {task.result}
        </div>
      )}

      {/* Retry with guidance */}
      {mode === 'retry' && (
        <div className="acm-card mt-3 p-3 space-y-2">
          <p className="label text-[var(--acm-warn)]">Retry — add instructions for the worker (optional):</p>
          <textarea
            value={notes}
            onChange={e => setNotes(e.target.value)}
            placeholder="E.g.: The file is already at src/foo.py, read it first. Use a simpler approach..."
            rows={3}
            className="w-full text-[11px] bg-[var(--acm-elev)] border border-[var(--acm-border)] rounded-lg p-2 text-[var(--acm-fg)] placeholder-[var(--acm-fg-4)] resize-none outline-none focus:border-[var(--acm-accent)] transition-colors"
          />
          <div className="flex gap-2">
            <button
              onClick={handleRetry}
              disabled={loading}
              className="btn-primary text-[11px] px-3 py-1 disabled:opacity-50 flex items-center gap-1"
            >
              {loading && <Loader2 size={10} className="animate-spin" />}
              Retry
            </button>
            <button
              onClick={() => setMode(null)}
              className="btn-secondary text-[11px] px-3 py-1"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* Manual completion */}
      {mode === 'complete' && (
        <div className="acm-card mt-3 p-3 space-y-2">
          <p className="label text-[var(--acm-ok)]">Complete manually — enter the result:</p>
          <textarea
            value={manualResult}
            onChange={e => setManualResult(e.target.value)}
            placeholder="Describe what was done, which files were created, and any output relevant to dependent tasks..."
            rows={5}
            className="w-full text-[11px] bg-[var(--acm-elev)] border border-[var(--acm-border)] rounded-lg p-2 text-[var(--acm-fg)] placeholder-[var(--acm-fg-4)] resize-none outline-none focus:border-[var(--acm-accent)] transition-colors"
          />
          <div className="flex gap-2">
            <button
              onClick={handleComplete}
              disabled={loading || !manualResult.trim()}
              className="btn-primary text-[11px] px-3 py-1 disabled:opacity-50 flex items-center gap-1"
            >
              {loading && <Loader2 size={10} className="animate-spin" />}
              Mark as completed
            </button>
            <button
              onClick={() => setMode(null)}
              className="btn-secondary text-[11px] px-3 py-1"
            >
              Cancel
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

// ─── Shared Markdown renderer ─────────────────────────────────────────────────
