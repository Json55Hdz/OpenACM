'use client';

import { useEffect, useRef, useState } from 'react';
import { Loader2, FlaskConical, CheckCircle2, XCircle, AlertTriangle, ShieldCheck, Infinity } from 'lucide-react';
import { useAuthStore } from '@/stores/auth-store';
import type { ValidationStep } from '@/stores/chat-store';
import { cn } from './shared';


export function ValidationBubble({
  tool,
  steps,
  done,
  passed,
}: {
  tool: string;
  steps: ValidationStep[];
  done: boolean;
  passed: boolean;
}) {
  const visibleSteps = steps.filter((s) => s.step !== '__done__');

  const stepIcon = (status: ValidationStep['status']) => {
    if (status === 'running') return <Loader2 size={13} className="animate-spin text-[var(--acm-accent)] flex-shrink-0" />;
    if (status === 'passed')  return <CheckCircle2 size={13} className="text-[var(--acm-ok)] flex-shrink-0" />;
    if (status === 'warning') return <AlertTriangle size={13} className="text-[var(--acm-warn)] flex-shrink-0" />;
    return <XCircle size={13} className="text-[var(--acm-err)] flex-shrink-0" />;
  };

  const headerColor = !done
    ? 'text-[var(--acm-fg-2)] border-[var(--acm-border-strong)] bg-[var(--acm-card)]'
    : passed
      ? 'text-[var(--acm-ok)] border-[var(--acm-border-strong)] bg-[var(--acm-card)]'
      : 'text-[var(--acm-err)] border-[var(--acm-border-strong)] bg-[var(--acm-card)]';

  const headerLabel = !done
    ? 'Validando...'
    : passed
      ? 'Tests pasados — listo para aplicar'
      : 'Tests fallaron — corrige los errores';

  return (
    <div className="flex gap-3">
      <div className="w-7 h-7 border border-[var(--acm-border)] bg-[var(--acm-card)] rounded-[6px] flex items-center justify-center flex-shrink-0 text-[var(--acm-accent)]">
        <FlaskConical size={14} />
      </div>
      <div className="flex flex-col max-w-[85%] items-start">
        <span className="mono text-[10px] text-[var(--acm-fg-4)] mb-1">Validación automática</span>
        <div className={cn('px-[14px] py-[12px] rounded-[0_8px_8px_0] border-l-2 border-l-[var(--acm-accent)] border border-[var(--acm-border)] w-full', headerColor)}>
          <div className="flex items-center gap-2 mb-3">
            {!done && <Loader2 size={13} className="animate-spin" />}
            {done && passed && <CheckCircle2 size={13} className="text-[var(--acm-ok)]" />}
            {done && !passed && <XCircle size={13} className="text-[var(--acm-err)]" />}
            <span className="mono text-[12px] font-medium">{`Tool: ${tool}`}</span>
            <span className="mono text-[10px] text-[var(--acm-fg-4)] ml-auto">{headerLabel}</span>
          </div>
          <div className="space-y-1.5">
            {visibleSteps.map((s) => (
              <div key={s.step} className="flex items-start gap-2 text-[11px]">
                {stepIcon(s.status)}
                <span className="mono font-medium w-28 flex-shrink-0 text-[var(--acm-fg-2)]">{s.step}</span>
                <span className="mono text-[var(--acm-fg-4)] truncate">{s.detail}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

export function ToolConfirmationBubble({
  confirmId,
  tool,
  command,
}: {
  confirmId: string;
  tool: string;
  command: string;
}) {
  const [resolved, setResolved] = useState<'approved' | 'denied' | 'session' | null>(null);
  const [loading, setLoading] = useState(false);
  const token = useAuthStore((s) => s.token);

  const resolve = async (approved: boolean, alwaysSession = false) => {
    setLoading(true);
    try {
      await fetch('/api/tool/confirm', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({ confirm_id: confirmId, approved, always_session: alwaysSession, command }),
      });
      setResolved(alwaysSession ? 'session' : approved ? 'approved' : 'denied');
    } catch {
      // best-effort
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex gap-3">
      <div className="w-7 h-7 border border-[var(--acm-border)] bg-[var(--acm-card)] rounded-[6px] flex items-center justify-center flex-shrink-0 text-[var(--acm-accent)]">
        <ShieldCheck size={14} />
      </div>
      <div className="flex flex-col max-w-[85%] items-start">
        <span className="mono text-[10px] text-[var(--acm-fg-4)] mb-1">Confirm</span>
        <div className="border border-[oklch(0.84_0.16_82/0.4)] bg-[oklch(0.84_0.16_82/0.04)] rounded-[6px] p-[12px] w-full">
          <div className="flex items-center gap-2 mb-3">
            <ShieldCheck size={13} className="text-[var(--acm-accent)]" />
            <span className="mono text-[12px] font-semibold text-[var(--acm-accent)]">PERMISSION REQUIRED — {tool}</span>
          </div>
          <div className="mono text-[11px] bg-[var(--acm-base)] border border-[var(--acm-border)] rounded-[4px] p-[10px_12px] mb-3 text-[var(--acm-fg-2)] break-all">
            {command}
          </div>
          {resolved === null ? (
            <div className="flex flex-wrap gap-2">
              <button
                disabled={loading}
                onClick={() => resolve(true)}
                className="btn-primary !py-[5px] !px-[10px] !text-[11px]"
              >
                {loading ? <Loader2 size={11} className="animate-spin" /> : <CheckCircle2 size={11} />}
                Allow
              </button>
              <button
                disabled={loading}
                onClick={() => resolve(true, true)}
                className="btn-secondary !py-[5px] !px-[10px] !text-[11px]"
              >
                <Infinity size={11} />
                Always (session)
              </button>
              <button
                disabled={loading}
                onClick={() => resolve(false)}
                className="mono text-[11px] text-[var(--acm-fg-4)] hover:text-[var(--acm-err)] transition-colors px-[10px] py-[5px]"
              >
                <XCircle size={11} className="inline mr-1" />
                Deny
              </button>
            </div>
          ) : (
            <div className={cn(
              'flex items-center gap-1.5 mono text-[11px] font-medium',
              resolved === 'approved' ? 'text-[var(--acm-ok)]'
              : resolved === 'session' ? 'text-[var(--acm-accent)]'
              : 'text-[var(--acm-err)]',
            )}>
              {resolved === 'approved' && <><CheckCircle2 size={11} /> Allowed</>}
              {resolved === 'session' && <><Infinity size={11} /> Allowed this session</>}
              {resolved === 'denied' && <><XCircle size={11} /> Denied</>}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export function ToolConfirmationModal({
  confirmId,
  tool,
  command,
  onClose,
}: {
  confirmId: string;
  tool: string;
  command: string;
  onClose: () => void;
}) {
  const TIMEOUT = 5;
  const [timeLeft, setTimeLeft] = useState(TIMEOUT);
  const [loading, setLoading] = useState(false);
  const token = useAuthStore((s) => s.token);
  const doneRef = useRef(false);

  const doResolve = async (approved: boolean, alwaysSession = false) => {
    if (doneRef.current) return;
    doneRef.current = true;
    setLoading(true);
    try {
      await fetch('/api/tool/confirm', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({ confirm_id: confirmId, approved, always_session: alwaysSession, command }),
      });
    } catch { /* best-effort */ }
    onClose();
  };

  // Always-fresh ref so the interval closure calls the latest doResolve
  const resolveRef = useRef(doResolve);
  resolveRef.current = doResolve;

  useEffect(() => {
    const id = setInterval(() => {
      setTimeLeft((prev) => {
        const next = prev - 1;
        if (next <= 0) {
          clearInterval(id);
          resolveRef.current(false);
        }
        return next;
      });
    }, 1000);
    return () => clearInterval(id);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div
        className="w-[460px] max-w-[92vw] rounded-[10px] overflow-hidden border bg-[var(--acm-card)]"
        style={{ borderColor: 'oklch(0.84 0.16 82 / 0.45)' }}
      >
        {/* Header */}
        <div className="flex items-center gap-[10px] px-[18px] py-[12px] border-b border-[var(--acm-border)] bg-[oklch(0.84_0.16_82/0.05)]">
          <ShieldCheck size={14} className="text-[var(--acm-accent)] flex-shrink-0" />
          <span className="mono text-[12px] font-semibold text-[var(--acm-accent)] flex-1">PERMISSION REQUIRED</span>
          <span className="mono text-[11px] text-[var(--acm-fg-4)] truncate max-w-[140px]">{tool}</span>
          {/* Countdown ring */}
          <div
            className="w-[28px] h-[28px] rounded-full border-2 flex items-center justify-center flex-shrink-0 transition-colors duration-300"
            style={{ borderColor: timeLeft <= 2 ? 'var(--acm-err)' : 'var(--acm-accent)' }}
          >
            <span
              className="mono text-[11px] font-bold transition-colors duration-300"
              style={{ color: timeLeft <= 2 ? 'var(--acm-err)' : 'var(--acm-accent)' }}
            >
              {timeLeft}
            </span>
          </div>
        </div>

        {/* Command preview */}
        <div className="px-[18px] py-[14px]">
          <div className="mono text-[11px] bg-[var(--acm-base)] border border-[var(--acm-border)] rounded-[6px] px-[12px] py-[10px] text-[var(--acm-fg-2)] break-all leading-relaxed">
            {command}
          </div>
        </div>

        {/* Actions */}
        <div className="px-[18px] pb-[16px] flex items-center gap-2">
          <button
            disabled={loading}
            onClick={() => doResolve(true)}
            className="btn-primary !py-[6px] !px-[14px] !text-[12px]"
          >
            {loading ? <Loader2 size={12} className="animate-spin" /> : <CheckCircle2 size={12} />}
            Allow
          </button>
          <button
            disabled={loading}
            onClick={() => doResolve(true, true)}
            className="btn-secondary !py-[6px] !px-[14px] !text-[12px]"
          >
            <Infinity size={12} />
            Always (session)
          </button>
          <button
            disabled={loading}
            onClick={() => doResolve(false)}
            className="mono text-[12px] text-[var(--acm-fg-4)] hover:text-[var(--acm-err)] transition-colors px-[12px] py-[6px] ml-auto flex items-center gap-1"
          >
            <XCircle size={12} />
            Deny
          </button>
        </div>

        {/* Countdown progress bar */}
        <div className="h-[3px] bg-[var(--acm-elev)]">
          <div
            className="h-full transition-all duration-1000 ease-linear"
            style={{
              width: `${(timeLeft / TIMEOUT) * 100}%`,
              background: timeLeft <= 2 ? 'var(--acm-err)' : 'var(--acm-accent)',
            }}
          />
        </div>
      </div>
    </div>
  );
}

// Regex that matches bare /api/media/<filename> links written by the LLM in plain text.

/**
 * Renders message text, converting any /api/media/<file> links into
 * inline image previews (for images) or download buttons (for other files).
 * The link text is removed from the paragraph so it's not shown twice.
 */
