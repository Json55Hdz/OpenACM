'use client';

import { useEffect, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { useQueryClient } from '@tanstack/react-query';
import { AppLayout } from '@/components/layout/app-layout';
import { useChatStore } from '@/stores/chat-store';
// useWebSocket is now initialized globally in app-layout — no need to import here
import { useAPI, useConversations, useConversationHistory, useChatCommand, useClearConversation, useCurrentModel, useSystemInfo } from '@/hooks/use-api';
import {
  Send,
  Paperclip,
  X,
  MoreVertical,
  Plus,
  Bot,
  User,
  Loader2,
  MessageSquare,
  Wrench,
  HelpCircle,
  Cpu,
  BarChart3,
  Download,
  SquareTerminal,
  Sparkles,
  Mic,
  MicOff,
  FileText,
  Music,
  FlaskConical,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  BrainCircuit,
  Trash2,
  ShieldCheck,
  ChevronDown,
  ChevronUp,
  DollarSign,
  ArrowUp,
  ArrowDown,
  Info,
  Infinity,
  ScrollText,
} from 'lucide-react';
import type { ValidationStep, MessageUsage } from '@/stores/chat-store';
import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';
import { toast } from 'sonner';
import { TerminalPanel } from '@/components/terminal/terminal-panel';
import { useTerminalStore } from '@/stores/terminal-store';
import { useAuthStore } from '@/stores/auth-store';

function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

interface Conversation {
  channel_id: string;
  user_id: string;
  title: string;
  last_message: string;
  last_timestamp: string;
  message_count: number;
}

function RouterLearningIndicator() {
  return (
    <div className="flex items-center gap-[7px] px-[10px] py-[4px] bg-[oklch(0.84_0.16_82/0.1)] border border-[var(--acm-accent)] rounded-full text-[var(--acm-accent)] text-[11px]">
      <Sparkles size={11} className="acm-pulse" />
      <span className="mono">Aprendiendo...</span>
    </div>
  );
}

function MemoryRecallIndicator({ status, count }: {
  status: 'searching' | 'found' | 'empty' | 'saving' | 'saved';
  count: number;
}) {
  const isBusy  = status === 'searching' || status === 'saving';
  const isGood  = status === 'found' || status === 'saved';
  const isEmpty = status === 'empty';

  const label =
    status === 'searching' ? 'Searching memory...' :
    status === 'found'     ? `Memory: ${count} ${count === 1 ? 'fragment' : 'fragments'}` :
    status === 'saving'    ? 'Saving to memory...' :
    status === 'saved'     ? 'Saved to memory' :
                             'No memory results';

  return (
    <div className={cn(
      'inline-flex items-center gap-[7px] px-[10px] py-[4px] border rounded-full text-[11px] transition-all duration-300',
      isBusy  && 'border-[var(--acm-border-strong)] text-[var(--acm-fg-3)]',
      isGood  && 'border-[var(--acm-accent)] text-[var(--acm-accent)] bg-[oklch(0.84_0.16_82/0.07)]',
      isEmpty && 'border-[var(--acm-border)] text-[var(--acm-fg-4)]',
    )}>
      <BrainCircuit size={11} className={cn(
        isBusy  && 'acm-pulse text-[var(--acm-fg-3)]',
        isGood  && 'text-[var(--acm-accent)]',
        isEmpty && 'text-[var(--acm-fg-4)]',
      )} />
      <span className="mono">{label}</span>
    </div>
  );
}

function SkillActiveIndicator({ names }: { names: string[] }) {
  const label = names
    .map((n) => n.replace(/-/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase()))
    .join(', ');
  return (
    <div className="inline-flex items-center gap-[7px] px-[10px] py-[4px] border border-[var(--acm-accent)] bg-[oklch(0.84_0.16_82/0.07)] rounded-full text-[var(--acm-accent)] text-[11px]">
      <span className="dot dot-accent acm-pulse" />
      <span className="mono">Skill: {label}</span>
    </div>
  );
}

function TypingIndicator({ label }: { label?: string | null }) {
  return (
    <div className="flex items-center gap-3 pl-1 py-1">
      <div className="flex items-center gap-[5px]">
        <div className="w-[7px] h-[7px] rounded-full bg-[var(--acm-accent)] acm-pulse" style={{ animationDelay: '0ms' }} />
        <div className="w-[7px] h-[7px] rounded-full bg-[var(--acm-accent)] acm-pulse" style={{ animationDelay: '220ms' }} />
        <div className="w-[7px] h-[7px] rounded-full bg-[var(--acm-accent)] acm-pulse" style={{ animationDelay: '440ms' }} />
      </div>
      {label && <span className="mono text-[11px] text-[var(--acm-fg-3)] truncate">{label}</span>}
    </div>
  );
}

function ValidationBubble({
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

function ToolConfirmationBubble({
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

function ToolConfirmationModal({
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
// Captures the filename (everything after /api/media/ up to whitespace or end).
const MEDIA_LINK_RE = /\/api\/media\/([\w.\-]+)/g;

/**
 * Renders message text, converting any /api/media/<file> links into
 * inline image previews (for images) or download buttons (for other files).
 * The link text is removed from the paragraph so it's not shown twice.
 */
function MessageContent({ content, token }: { content: string; token: string | null }) {
  // Find all /api/media/ links in the text
  const mediaMatches: { filename: string; index: number; fullMatch: string }[] = [];
  let m: RegExpExecArray | null;
  MEDIA_LINK_RE.lastIndex = 0;
  while ((m = MEDIA_LINK_RE.exec(content)) !== null) {
    mediaMatches.push({ filename: m[1], index: m.index, fullMatch: m[0] });
  }

  // Remove the matched links from the visible text
  const cleanText = content.replace(MEDIA_LINK_RE, '').replace(/\n{3,}/g, '\n\n').trim();

  return (
    <div>
      {cleanText && (
        <ReactMarkdown
          remarkPlugins={[remarkGfm]}
          components={{
            p: ({ children }) => <p className="mb-2 last:mb-0 leading-relaxed text-[var(--acm-fg-2)]">{children}</p>,
            h1: ({ children }) => <h1 className="text-xl font-bold text-[var(--acm-fg)] mt-4 mb-2 first:mt-0">{children}</h1>,
            h2: ({ children }) => <h2 className="text-lg font-semibold text-[var(--acm-fg)] mt-3 mb-1.5 first:mt-0">{children}</h2>,
            h3: ({ children }) => <h3 className="text-base font-semibold text-[var(--acm-fg-2)] mt-2 mb-1 first:mt-0">{children}</h3>,
            strong: ({ children }) => <strong className="font-semibold text-[var(--acm-fg)]">{children}</strong>,
            em: ({ children }) => <em className="italic text-[var(--acm-fg-3)]">{children}</em>,
            ul: ({ children }) => <ul className="list-disc list-inside space-y-1 my-2 pl-2">{children}</ul>,
            ol: ({ children }) => <ol className="list-decimal list-inside space-y-1 my-2 pl-2">{children}</ol>,
            li: ({ children }) => <li className="text-[var(--acm-fg-2)]">{children}</li>,
            code: ({ children, className }) => {
              const isBlock = className?.includes('language-');
              return isBlock
                ? <code className="block bg-[oklch(0.13_0.005_255)] text-[var(--acm-ok)] rounded-[6px] px-4 py-3 my-2 text-[12px] mono overflow-x-auto whitespace-pre">{children}</code>
                : <code className="bg-[var(--acm-elev)] text-[var(--acm-accent)] rounded-[4px] px-1.5 py-0.5 text-[12px] mono">{children}</code>;
            },
            pre: ({ children }) => <>{children}</>,
            blockquote: ({ children }) => <blockquote className="border-l-2 border-l-[var(--acm-accent)] pl-3 my-2 text-[var(--acm-fg-3)] italic">{children}</blockquote>,
            a: ({ href, children }) => <a href={href} target="_blank" rel="noopener noreferrer" className="text-[var(--acm-accent)] hover:text-[var(--acm-accent-hi)] underline underline-offset-2">{children}</a>,
            hr: () => <hr className="border-[var(--acm-border)] my-3" />,
            table: ({ children }) => <div className="overflow-x-auto my-2"><table className="text-[12px] border-collapse w-full">{children}</table></div>,
            th: ({ children }) => <th className="border border-[var(--acm-border-strong)] px-3 py-1.5 bg-[var(--acm-elev)] text-left font-semibold text-[var(--acm-fg-2)]">{children}</th>,
            td: ({ children }) => <td className="border border-[var(--acm-border)] px-3 py-1.5 text-[var(--acm-fg-3)]">{children}</td>,
          }}
        >
          {cleanText}
        </ReactMarkdown>
      )}
      {mediaMatches.length > 0 && (
        <div className={cn("space-y-2", cleanText && "mt-3")}>
          {mediaMatches.map(({ filename }, idx) => {
            const isImage = /\.(png|jpg|jpeg|gif|webp)$/i.test(filename);
            const previewUrl = `/api/media/${filename}${token ? `?token=${token}` : ''}`;
            const downloadUrl = `/api/media/${filename}?download=true${token ? `&token=${token}` : ''}`;
            return (
              <div key={idx} className="rounded-[6px] overflow-hidden border border-[var(--acm-border)]">
                {isImage && (
                  <img
                    src={previewUrl}
                    alt={filename}
                    className="max-w-xs max-h-64 object-contain bg-[var(--acm-base)] block"
                  />
                )}
                <div className="flex items-center gap-2 px-3 py-2 bg-[var(--acm-card)] text-[11px]">
                  <Paperclip size={11} className="text-[var(--acm-fg-4)] flex-shrink-0" />
                  <span className="mono truncate text-[var(--acm-fg-3)] flex-1">{filename}</span>
                  <a
                    href={downloadUrl}
                    download={filename}
                    className="btn-primary !py-[4px] !px-[8px] !text-[11px] flex-shrink-0"
                  >
                    <Download size={10} />
                    Download
                  </a>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ── Token Badge (debug mode only) ────────────────────────────────────────────

function fmt(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return String(n);
}

function TokenBadge({ usage }: { usage: MessageUsage }) {
  const [open, setOpen] = useState(false);

  return (
    <div className="mt-1.5">
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center gap-2 mono text-[10px] text-[var(--acm-fg-4)] hover:text-[var(--acm-fg-3)] transition-colors group"
      >
        <span className="flex items-center gap-0.5">
          <ArrowUp size={9} className="text-[var(--acm-accent)]" />
          {fmt(usage.prompt_tokens)}
        </span>
        <span className="flex items-center gap-0.5">
          <ArrowDown size={9} className="text-[var(--acm-fg-3)]" />
          {fmt(usage.completion_tokens)}
        </span>
        {usage.cost > 0 && (
          <span className="flex items-center gap-0.5 text-[var(--acm-accent)]">
            <DollarSign size={9} />
            {usage.cost < 0.001 ? '<$0.001' : `$${usage.cost.toFixed(4)}`}
          </span>
        )}
        <Info size={9} className="opacity-0 group-hover:opacity-100 transition-opacity" />
        {open ? <ChevronUp size={9} /> : <ChevronDown size={9} />}
      </button>

      {open && (
        <div className="mt-1 bg-[var(--acm-card)] border border-[var(--acm-border)] rounded-[6px] p-3 text-[11px] space-y-1.5 text-[var(--acm-fg-4)] mono max-w-xs">
          <div className="flex justify-between">
            <span className="text-[var(--acm-fg-4)]">Model</span>
            <span className="text-[var(--acm-fg-2)]">{usage.model || '—'}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-[var(--acm-fg-4)]">Input tokens</span>
            <span className="text-[var(--acm-accent)]">{usage.prompt_tokens.toLocaleString()}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-[var(--acm-fg-4)]">Output tokens</span>
            <span className="text-[var(--acm-fg-3)]">{usage.completion_tokens.toLocaleString()}</span>
          </div>
          <div className="flex justify-between border-t border-[var(--acm-border)] pt-1.5">
            <span className="text-[var(--acm-fg-4)]">Total tokens</span>
            <span className="text-[var(--acm-fg)]">{usage.total_tokens.toLocaleString()}</span>
          </div>
          {usage.cost > 0 && (
            <div className="flex justify-between">
              <span className="text-[var(--acm-fg-4)]">Est. cost</span>
              <span className="text-[var(--acm-accent)]">
                ${usage.cost < 0.000001 ? '< $0.000001' : usage.cost.toFixed(6)}
              </span>
            </div>
          )}
          {usage.requests > 1 && (
            <div className="flex justify-between">
              <span className="text-[var(--acm-fg-4)]">LLM calls</span>
              <span className="text-[var(--acm-fg-3)]">{usage.requests}</span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function CompactionNoteBubble({
  summarizedMessages,
}: {
  summarizedMessages: number;
}) {
  return (
    <div className="flex items-center px-2">
      <div className="flex items-center gap-[8px] px-[12px] py-[7px] border border-[var(--acm-border)] bg-[var(--acm-card)] rounded-[6px] text-[11px]">
        <ScrollText size={11} className="text-[var(--acm-accent)] flex-shrink-0" />
        <span className="mono font-medium text-[var(--acm-fg-3)]">Conversation compacted</span>
        <span className="text-[var(--acm-border-strong)]">·</span>
        <span className="mono text-[var(--acm-fg-4)]">{summarizedMessages} messages summarized</span>
      </div>
    </div>
  );
}

function MessageBubble({
  content,
  role,
  badge,
  attachments,
  toolCall,
  usage,
  debugMode,
}: {
  content: string;
  role: 'user' | 'assistant' | 'error' | 'system';
  badge?: string;
  attachments?: Array<{ id?: string; name: string; type: string }>;
  usage?: MessageUsage;
  debugMode?: boolean;
  toolCall?: {
    tool: string;
    arguments: string;
    result?: string;
    status: 'running' | 'completed' | 'error';
  };
}) {
  const [expanded, setExpanded] = useState(false);
  const isUser = role === 'user';
  const isError = role === 'error';
  const isSystem = role === 'system';
  const token = useAuthStore((s) => s.token);

  // System/tool messages — tool call card style
  if (isSystem && toolCall) {
    const isRunning = toolCall.status === 'running';
    const isDone    = toolCall.status === 'completed';
    const isFailed  = toolCall.status === 'error';

    const accentColor = isRunning ? 'var(--acm-accent)' : isDone ? 'var(--acm-ok)' : 'var(--acm-err)';
    const stateLabel  = isRunning ? 'CALL' : isDone ? 'DONE' : 'ERR';

    return (
      <div
        className="acm-card overflow-hidden max-w-[85%]"
        style={{ borderLeft: `2px solid ${accentColor}` }}
      >
        {/* Card header — always clickable to expand */}
        <button
          onClick={() => setExpanded(!expanded)}
          className="w-full flex items-center gap-[10px] px-[12px] py-[8px] hover:bg-[var(--acm-elev)] transition-colors"
          style={{ borderBottom: expanded ? '1px solid var(--acm-border)' : undefined }}
        >
          {isRunning && <span className="dot dot-accent acm-pulse" />}
          {isDone    && <span className="dot dot-ok" />}
          {isFailed  && <span className="dot dot-err" />}

          <Wrench size={12} style={{ color: accentColor }} />

          <span
            className="mono text-[10px] font-semibold uppercase tracking-wider flex-shrink-0"
            style={{ color: accentColor }}
          >
            {stateLabel}
          </span>

          <span className="mono text-[12px] text-[var(--acm-fg-2)] font-medium flex-1 text-left truncate">
            {toolCall.tool}
          </span>

          {toolCall.arguments && !expanded && (
            <span className="mono text-[11px] text-[var(--acm-fg-4)] truncate max-w-[180px]">
              {toolCall.arguments}
            </span>
          )}

          {expanded
            ? <ChevronUp size={12} className="text-[var(--acm-fg-4)] flex-shrink-0" />
            : <ChevronDown size={12} className="text-[var(--acm-fg-4)] flex-shrink-0" />
          }
        </button>

        {expanded && (
          <div className="bg-[oklch(0.13_0.005_255)] mono text-[11px]">
            {toolCall.arguments && (
              <div className="px-[12px] py-[8px] border-b border-[var(--acm-border)]">
                <div className="text-[var(--acm-accent)] text-[9px] uppercase tracking-widest mb-1">Arguments</div>
                <pre className="text-[var(--acm-fg-3)] overflow-x-auto whitespace-pre-wrap">{toolCall.arguments}</pre>
              </div>
            )}

            {toolCall.result ? (
              <div className="px-[12px] py-[8px]">
                <div className="text-[var(--acm-ok)] text-[9px] uppercase tracking-widest mb-1">Result</div>
                <pre className="text-[var(--acm-fg-3)] overflow-x-auto whitespace-pre-wrap">{toolCall.result}</pre>
              </div>
            ) : isRunning ? (
              <div className="px-[12px] py-[8px] flex items-center gap-2 text-[var(--acm-fg-4)]">
                <Loader2 size={11} className="animate-spin text-[var(--acm-accent)]" />
                <span>Running…</span>
              </div>
            ) : null}
          </div>
        )}
      </div>
    );
  }

  // Error role — inline style
  if (isError) {
    return (
      <div className="flex items-start gap-2 border-l-2 border-l-[var(--acm-err)] pl-3 py-1">
        <span className="dot dot-err mt-1 flex-shrink-0" />
        <p className="text-[12px] text-[var(--acm-fg-3)]">{content}</p>
      </div>
    );
  }

  // System message (no toolCall) — divider style
  if (isSystem) {
    return (
      <div className="border-l-2 border-l-[var(--acm-border-strong)] pl-3 py-1 text-[12px] text-[var(--acm-fg-3)]">
        {badge && <span className="mono text-[10px] text-[var(--acm-fg-4)] block mb-0.5">{badge}</span>}
        <MessageContent content={content} token={token} />
      </div>
    );
  }

  return (
    <div className={cn(
      "flex gap-3",
      isUser ? "flex-row-reverse" : ""
    )}>
      {/* Avatar */}
      {!isUser && (
        <div className="w-7 h-7 border border-[var(--acm-border)] bg-[var(--acm-card)] rounded-[6px] flex items-center justify-center flex-shrink-0 text-[var(--acm-accent)] self-start mt-1">
          <Bot size={14} />
        </div>
      )}

      <div className={cn(
        "flex flex-col max-w-[75%]",
        isUser ? "items-end" : "items-start"
      )}>
        {badge && (
          <span className="mono text-[10px] text-[var(--acm-fg-4)] mb-1">{badge}</span>
        )}

        {isUser ? (
          /* User bubble */
          <div className="bg-[var(--acm-card)] border border-[var(--acm-border)] rounded-[8px] px-[14px] py-[12px] text-[var(--acm-fg)]">
            <MessageContent content={content} token={token} />

            {attachments && attachments.length > 0 && (
              <div className="mt-3 space-y-2">
                {attachments.map((att, idx) => {
                  const fileId = att.id || att.name;
                  const isMedia = /\.(png|jpg|jpeg|gif|webp)$/i.test(att.name);
                  const downloadUrl = `/api/media/${fileId}?download=true&token=${token}`;
                  const previewUrl = `/api/media/${fileId}?token=${token}`;
                  return (
                    <div key={idx} className="rounded-[6px] overflow-hidden border border-[var(--acm-border)]">
                      {isMedia && (
                        <img
                          src={previewUrl}
                          alt={att.name}
                          className="max-w-xs max-h-48 object-contain bg-[var(--acm-base)]"
                        />
                      )}
                      <div className="flex items-center gap-2 px-3 py-2 bg-[var(--acm-elev)] text-[11px]">
                        <Paperclip size={11} className="text-[var(--acm-fg-4)] flex-shrink-0" />
                        <span className="mono truncate text-[var(--acm-fg-3)] flex-1">{att.name}</span>
                        <a
                          href={downloadUrl}
                          download={att.name}
                          className="btn-primary !py-[4px] !px-[8px] !text-[11px] flex-shrink-0"
                        >
                          <Download size={10} />
                          Download
                        </a>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        ) : (
          /* Assistant bubble */
          <div className="bg-[oklch(0.84_0.16_82/0.04)] border-l-2 border-l-[var(--acm-accent)] rounded-[0_8px_8px_0] px-[14px] py-[12px] text-[var(--acm-fg-2)]">
            <MessageContent content={content} token={token} />

            {attachments && attachments.length > 0 && (
              <div className="mt-3 space-y-2">
                {attachments.map((att, idx) => {
                  const fileId = att.id || att.name;
                  const isMedia = /\.(png|jpg|jpeg|gif|webp)$/i.test(att.name);
                  const downloadUrl = `/api/media/${fileId}?download=true&token=${token}`;
                  const previewUrl = `/api/media/${fileId}?token=${token}`;
                  return (
                    <div key={idx} className="rounded-[6px] overflow-hidden border border-[var(--acm-border)]">
                      {isMedia && (
                        <img
                          src={previewUrl}
                          alt={att.name}
                          className="max-w-xs max-h-48 object-contain bg-[var(--acm-base)]"
                        />
                      )}
                      <div className="flex items-center gap-2 px-3 py-2 bg-[var(--acm-elev)] text-[11px]">
                        <Paperclip size={11} className="text-[var(--acm-fg-4)] flex-shrink-0" />
                        <span className="mono truncate text-[var(--acm-fg-3)] flex-1">{att.name}</span>
                        <a
                          href={downloadUrl}
                          download={att.name}
                          className="btn-primary !py-[4px] !px-[8px] !text-[11px] flex-shrink-0"
                        >
                          <Download size={10} />
                          Download
                        </a>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        )}

        {!isUser && !isError && usage && usage.total_tokens > 0 && (
          <TokenBadge usage={usage} />
        )}
      </div>
    </div>
  );
}

export default function ChatPage() {
  const {
    messages,
    addMessage,
    setMessages,
    currentTarget,
    setTarget,
    isWaitingResponse,
    thinkingLabel,
    currentAttachments,
    addAttachment,
    removeAttachment,
    clearAttachments,
    showToolLogs,
    setShowToolLogs,
    isRouterLearning,
    activeSkillNames,
    memoryRecall,
  } = useChatStore();

  const wsConnected = useChatStore((s) => s.wsConnected);
  const sendMessage = useChatStore((s) => s.sendMessageFn);
  const cancelMessage = useChatStore((s) => s.cancelMessageFn);
  const pendingOnboardingGreeting = useChatStore((s) => s.pendingOnboardingGreeting);
  const setPendingOnboardingGreeting = useChatStore((s) => s.setPendingOnboardingGreeting);
  const { data: conversations } = useConversations();
  const { data: history, isFetching: isLoadingHistory } = useConversationHistory(currentTarget.channel, currentTarget.user);
  const chatCommand = useChatCommand();
  const clearConversation = useClearConversation();
  const { data: modelData } = useCurrentModel();
  const { data: systemInfo } = useSystemInfo();
  const { fetchAPI } = useAPI();
  const queryClient = useQueryClient();

  const { isOpen: isTerminalOpen, toggleOpen: toggleTerminal } = useTerminalStore();

  const [inputValue, setInputValue] = useState('');
  const [isSidebarOpen, setIsSidebarOpen] = useState(true);
  const [deletingKey, setDeletingKey] = useState<string | null>(null);
  const [debugMode] = useState(() =>
    typeof window !== 'undefined' && localStorage.getItem('openacm_debug_mode') === 'true'
  );

  const [isRecording, setIsRecording] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [isCompacting, setIsCompacting] = useState(false);
  const [activeConfirmation, setActiveConfirmation] = useState<{
    confirmId: string;
    tool: string;
    command: string;
  } | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);
  // Track which confirmation IDs have already been shown as a modal
  const shownConfirmIdsRef = useRef<Set<string>>(new Set());
  // Track which conversation we last loaded history for
  const loadedKeyRef = useRef('');
  // Only show reconnecting overlay after first successful connection
  const hasConnectedRef = useRef(false);
  useEffect(() => { if (wsConnected) hasConnectedRef.current = true; }, [wsConnected]);
  const showReconnecting = hasConnectedRef.current && !wsConnected;

  // Pop a modal for any new toolConfirmation message that hasn't been shown yet
  useEffect(() => {
    for (let i = messages.length - 1; i >= 0; i--) {
      const msg = messages[i];
      if (msg.toolConfirmation) {
        const { confirmId, tool, command } = msg.toolConfirmation;
        if (!shownConfirmIdsRef.current.has(confirmId)) {
          shownConfirmIdsRef.current.add(confirmId);
          setActiveConfirmation({ confirmId, tool, command });
        }
        break;
      }
    }
  }, [messages]);

  // Load conversation history when a new conversation is selected
  useEffect(() => {
    const key = `${currentTarget.channel}:${currentTarget.user}`;
    // Only load once per conversation switch (avoid re-running on live messages)
    if (loadedKeyRef.current === key) return;

    if (history && Array.isArray(history)) {
      loadedKeyRef.current = key;
      // If we already have in-memory messages for this conversation (restored from
      // the per-conversation cache), keep them — they have usage/token data.
      if (useChatStore.getState().messages.length > 0) return;
      if (history.length > 0) {
        const visible = history
          .filter((msg: { role: string; content: string }) => {
            // Skip system prompts, tool results, and assistant-only-tool-call messages
            if (msg.role === 'system') return false;
            if (msg.role === 'tool') return false;
            // Skip assistant messages that have no visible text (were just tool-call planners)
            if (msg.role === 'assistant' && (!msg.content || !msg.content.trim())) return false;
            return true;
          })
          .map((msg: { role: string; content: string }) => {
            // Parse [IMAGE:filename] markers back into attachment objects
            const attachments: Array<{ id: string; name: string; type: string }> = [];
            const content = msg.content.replace(/\[IMAGE:([^\]]+)\]/g, (_, fileId) => {
              const ext = fileId.split('.').pop()?.toLowerCase() ?? '';
              const imgExts = new Set(['png', 'jpg', 'jpeg', 'gif', 'webp']);
              attachments.push({
                id: fileId,
                name: fileId,
                type: imgExts.has(ext) ? `image/${ext === 'jpg' ? 'jpeg' : ext}` : 'application/octet-stream',
              });
              return '';
            }).trim();
            return {
              content,
              role: (msg.role === 'assistant' ? 'assistant' : 'user') as 'user' | 'assistant',
              ...(attachments.length > 0 ? { attachments } : {}),
            };
          });
        setMessages(visible);
      }
    }
  }, [history, currentTarget.channel, currentTarget.user, setMessages]);

  // Consume pending onboarding greeting — add it once history has been loaded
  // (or immediately if there's no history to load). Clear after showing.
  useEffect(() => {
    if (pendingOnboardingGreeting === null) return;
    if (isLoadingHistory) return; // wait for history to settle first
    addMessage({ content: pendingOnboardingGreeting, role: 'assistant' });
    setPendingOnboardingGreeting(null);
  }, [pendingOnboardingGreeting, isLoadingHistory, addMessage, setPendingOnboardingGreeting]);

  // Auto-scroll to bottom
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isWaitingResponse]);

  const executeCommand = async (command: string) => {
    if (command.startsWith('/compact')) setIsCompacting(true);
    try {
      const result = await chatCommand.mutateAsync({
        command,
        userId: currentTarget.user,
        channelId: currentTarget.channel,
      });
      if (result.text) {
        addMessage({ content: result.text, role: 'system' });
      }
      // Handle special data payloads
      if (result.data?.export) {
        const blob = new Blob([result.data.export], { type: 'text/plain' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'conversation.txt';
        a.click();
        URL.revokeObjectURL(url);
      }
      // If it was a clear/new/reset command, also clear local messages
      if (command.startsWith('/new') || command.startsWith('/clear') || command.startsWith('/reset')) {
        setMessages([]);
      }
      if (command.startsWith('/compact') && result.data?.compact) {
        setIsCompacting(false);
      }
    } catch {
      toast.error('Command failed');
    } finally {
      setIsCompacting(false);
    }
  };

  const handleSend = () => {
    if (!inputValue.trim() && currentAttachments.length === 0) return;

    // Intercept slash commands — send via REST, not WebSocket
    if (inputValue.trim().startsWith('/')) {
      const cmd = inputValue.trim();
      setInputValue('');
      addMessage({ content: cmd, role: 'user' });
      executeCommand(cmd);
      return;
    }

    const attachmentIds = currentAttachments.map(a => a.id);

    // Add user message to local state
    addMessage({
      content: inputValue,
      role: 'user',
      attachments: currentAttachments,
    });

    // Send via WebSocket (sendMessage is injected by the global WS hook in app-layout)
    const sent = sendMessage ? sendMessage(inputValue, attachmentIds) : false;

    if (sent) {
      setInputValue('');
      clearAttachments();
    } else {
      toast.error('Could not send message. Check your connection.');
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const uploadFile = async (file: File): Promise<{ id: string; name: string; type: string; previewUrl?: string } | null> => {
    const token = useAuthStore.getState().token;
    const formData = new FormData();
    formData.append('file', file);
    try {
      const res = await fetch('/api/chat/upload', {
        method: 'POST',
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        body: formData,
      });
      if (!res.ok) throw new Error(`Upload failed: ${res.status}`);
      const data = await res.json();
      return {
        id: data.file_id,
        name: file.name,
        type: file.type,
        previewUrl: file.type.startsWith('image/') ? URL.createObjectURL(file) : undefined,
      };
    } catch (err) {
      toast.error(`Failed to upload ${file.name}`);
      return null;
    }
  };

  const handleFileSelect = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (!files) return;
    setIsUploading(true);
    for (const file of Array.from(files)) {
      const att = await uploadFile(file);
      if (att) addAttachment(att);
    }
    setIsUploading(false);
    e.target.value = '';
  };

  const handlePaste = async (e: React.ClipboardEvent) => {
    const items = Array.from(e.clipboardData.items);
    const imageItem = items.find(i => i.type.startsWith('image/'));
    if (!imageItem) return;
    e.preventDefault();
    const file = imageItem.getAsFile();
    if (!file) return;
    const named = new File([file], `paste-${Date.now()}.png`, { type: file.type });
    setIsUploading(true);
    const att = await uploadFile(named);
    if (att) addAttachment(att);
    setIsUploading(false);
  };

  const handleMicClick = async () => {
    if (isRecording) {
      mediaRecorderRef.current?.stop();
      setIsRecording(false);
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const recorder = new MediaRecorder(stream);
      mediaRecorderRef.current = recorder;
      audioChunksRef.current = [];

      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) audioChunksRef.current.push(e.data);
      };

      recorder.onstop = async () => {
        stream.getTracks().forEach(t => t.stop());
        const blob = new Blob(audioChunksRef.current, { type: 'audio/webm' });
        const file = new File([blob], `voice-${Date.now()}.webm`, { type: 'audio/webm' });
        setIsUploading(true);
        const att = await uploadFile(file);
        if (att) {
          addAttachment(att);
          toast.success('Voice message ready — press Send');
        }
        setIsUploading(false);
      };

      recorder.start();
      setIsRecording(true);
      toast('Recording... press mic again to stop', { icon: '🎤' });
    } catch {
      toast.error('Could not access microphone');
    }
  };

  const selectConversation = (conv: Conversation) => {
    const newKey = `${conv.channel_id}:${conv.user_id}`;
    if (loadedKeyRef.current !== newKey) {
      loadedKeyRef.current = '';
    }
    setTarget({
      channel: conv.channel_id,
      user: conv.user_id,
      title: conv.title || `${conv.channel_id} - ${conv.user_id}`,
    });
  };

  const startNewConversation = () => {
    const newUserId = `web_${Date.now()}`;
    loadedKeyRef.current = '';
    setTarget({
      channel: 'web',
      user: newUserId,
      title: 'New Conversation',
    });
    // Optimistically add the new conversation to the sidebar immediately
    queryClient.setQueryData(['conversations'], (old: Conversation[] | undefined) => {
      const entry: Conversation = {
        channel_id: 'web',
        user_id: newUserId,
        title: 'New Conversation',
        last_message: '',
        last_timestamp: new Date().toISOString(),
        message_count: 0,
      };
      return [entry, ...(old ?? [])];
    });
  };

  const handleDeleteConversation = async (conv: Conversation, e: React.MouseEvent) => {
    e.stopPropagation();
    const key = `${conv.channel_id}-${conv.user_id}`;
    setDeletingKey(key);
    try {
      await clearConversation.mutateAsync({ channelId: conv.channel_id, userId: conv.user_id });
      // If we deleted the currently active conversation, start a new one
      if (currentTarget.channel === conv.channel_id && currentTarget.user === conv.user_id) {
        startNewConversation();
      }
    } catch {
      toast.error('Failed to delete conversation');
    } finally {
      setDeletingKey(null);
    }
  };

  const conversationList: Conversation[] = conversations || [];

  return (
    <AppLayout>
      <div className="h-screen flex bg-[var(--acm-base)]">
        {/* Sidebar - Conversation List */}
        <div className={cn(
          "fixed lg:static inset-y-0 left-0 w-72 bg-[var(--acm-base)] border-r border-[var(--acm-border)] z-30 transition-transform duration-300",
          isSidebarOpen ? "translate-x-0" : "-translate-x-full lg:translate-x-0 lg:w-0 lg:overflow-hidden lg:border-r-0"
        )}>
          <div className="flex flex-col h-full">
            {/* Sidebar header */}
            <div className="px-[16px] py-[14px] border-b border-[var(--acm-border)]">
              <div className="flex items-center justify-between mb-3">
                <span className="label text-[var(--acm-fg-3)]">Conversations</span>
                <button
                  onClick={() => setIsSidebarOpen(false)}
                  className="lg:hidden p-1 text-[var(--acm-fg-4)] hover:text-[var(--acm-fg)] transition-colors"
                >
                  <X size={16} />
                </button>
              </div>
              {systemInfo?.messages_encrypted && (
                <div className="flex items-center gap-1.5 px-2.5 py-1.5 mb-3 rounded-[6px] border border-[var(--acm-border)] text-[var(--acm-ok)] text-[11px] mono">
                  <ShieldCheck size={11} className="shrink-0" />
                  <span>Encrypted at rest</span>
                </div>
              )}
              <button
                onClick={startNewConversation}
                className="btn-primary w-full justify-center !text-[12px] !py-[7px]"
              >
                <Plus size={14} />
                New Conversation
              </button>
            </div>

            {/* Conversation list */}
            <div className="flex-1 overflow-y-auto acm-scroll p-[8px] space-y-[2px]">
              {conversationList.map((conv) => {
                const convKey = `${conv.channel_id}-${conv.user_id}`;
                const isActive = currentTarget.channel === conv.channel_id && currentTarget.user === conv.user_id;
                const isDeleting = deletingKey === convKey;
                const isDeletable = conv.channel_id !== 'console';
                return (
                  <div
                    key={convKey}
                    className={cn(
                      "group relative w-full text-left px-[10px] py-[9px] rounded-[6px] transition-colors cursor-pointer",
                      isActive
                        ? "border-l-2 border-l-[var(--acm-accent)] bg-[var(--acm-elev)] pl-[8px]"
                        : "border-l-2 border-l-transparent hover:bg-[var(--acm-card)]"
                    )}
                    onClick={() => selectConversation(conv)}
                  >
                    <div className="flex items-center gap-2">
                      <MessageSquare size={13} className={cn(
                        "flex-shrink-0",
                        isActive ? "text-[var(--acm-accent)]" : "text-[var(--acm-fg-4)]"
                      )} />
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-1.5">
                          <p className={cn(
                            "text-[13px] font-medium truncate",
                            isActive ? "text-[var(--acm-fg)]" : "text-[var(--acm-fg-2)]"
                          )}>
                            {conv.title || `${conv.channel_id} - ${conv.user_id}`}
                          </p>
                          {conv.message_count === 0 && (
                            <span className="shrink-0 mono text-[10px] px-1.5 py-0.5 bg-[oklch(0.84_0.16_82/0.1)] text-[var(--acm-accent)] rounded-full border border-[oklch(0.84_0.16_82/0.3)]">
                              New
                            </span>
                          )}
                        </div>
                        <p className="mono text-[10px] text-[var(--acm-fg-4)] truncate mt-[1px]">
                          {conv.last_message || 'No messages yet'}
                        </p>
                      </div>
                      {conv.message_count > 0 && (
                        <span className="mono text-[10px] text-[var(--acm-fg-4)] group-hover:hidden">
                          {conv.message_count}
                        </span>
                      )}
                      {isDeletable && (
                        <button
                          onClick={(e) => handleDeleteConversation(conv, e)}
                          disabled={isDeleting}
                          className={cn(
                            "hidden group-hover:flex items-center justify-center w-6 h-6 rounded-[4px] transition-colors shrink-0",
                            "text-[var(--acm-fg-4)] hover:text-[var(--acm-err)] hover:bg-[oklch(0.68_0.13_22/0.1)]",
                            isDeleting && "!flex"
                          )}
                          title="Delete conversation"
                        >
                          {isDeleting
                            ? <Loader2 size={12} className="animate-spin" />
                            : <Trash2 size={12} />
                          }
                        </button>
                      )}
                    </div>
                  </div>
                );
              })}

              {conversationList.length === 0 && (
                <div className="text-center py-10">
                  <MessageSquare size={32} className="mx-auto text-[var(--acm-border-strong)] mb-2" />
                  <p className="mono text-[11px] text-[var(--acm-fg-4)]">No conversations yet</p>
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Main Chat Area */}
        <div className="flex-1 flex flex-col min-w-0 bg-[var(--acm-base)] relative">
          {/* Reconnecting overlay */}
          {showReconnecting && (
            <div className="absolute inset-0 z-50 flex flex-col items-center justify-center bg-[var(--acm-base)]/90 backdrop-blur-sm">
              <Loader2 size={32} className="text-[var(--acm-accent)] animate-spin mb-4" />
              <p className="text-[var(--acm-fg-2)] text-[13.5px] font-semibold">Reconnecting to backend…</p>
              <p className="mono text-[10px] text-[var(--acm-fg-4)] mt-1">Your conversation will resume automatically</p>
            </div>
          )}

          {/* Chat header bar */}
          <div className="h-[52px] flex items-center justify-between px-[16px] border-b border-[var(--acm-border)] bg-[var(--acm-base)] flex-shrink-0">
            <div className="flex items-center gap-3">
              <button
                onClick={() => setIsSidebarOpen(true)}
                className="lg:hidden p-1.5 text-[var(--acm-fg-4)] hover:text-[var(--acm-fg)] transition-colors"
              >
                <MessageSquare size={16} />
              </button>
              <div>
                <h3 className="text-[13.5px] font-semibold text-[var(--acm-fg)] leading-tight">{currentTarget.title}</h3>
                <p className="mono text-[10px] text-[var(--acm-fg-4)]">{currentTarget.channel} · {currentTarget.user}</p>
              </div>
            </div>

            <div className="flex items-center gap-[8px]">
              {/* WS status pill */}
              <div className="inline-flex items-center gap-[7px] px-[10px] py-[4px] border border-[var(--acm-border)] rounded-full text-[11px]">
                <span className={cn("dot", wsConnected ? "dot-ok acm-pulse" : "dot-err")} />
                <span className="mono text-[var(--acm-fg-4)]">{wsConnected ? 'connected' : 'offline'}</span>
              </div>

              <button
                onClick={() => setShowToolLogs(!showToolLogs)}
                className={cn(
                  "inline-flex items-center gap-[7px] px-[10px] py-[4px] border rounded-full text-[11px] mono transition-colors",
                  showToolLogs
                    ? "border-[var(--acm-accent)] text-[var(--acm-accent)] bg-[oklch(0.84_0.16_82/0.07)]"
                    : "border-[var(--acm-border)] text-[var(--acm-fg-4)] hover:text-[var(--acm-fg)] hover:border-[var(--acm-border-strong)]"
                )}
              >
                Tool Logs
              </button>
              <button
                onClick={toggleTerminal}
                className={cn(
                  "inline-flex items-center gap-[7px] px-[10px] py-[4px] border rounded-full text-[11px] mono transition-colors",
                  isTerminalOpen
                    ? "border-[var(--acm-accent)] text-[var(--acm-accent)] bg-[oklch(0.84_0.16_82/0.07)]"
                    : "border-[var(--acm-border)] text-[var(--acm-fg-4)] hover:text-[var(--acm-fg)] hover:border-[var(--acm-border-strong)]"
                )}
              >
                <SquareTerminal size={12} />
                Terminal
              </button>
              <button className="p-1.5 text-[var(--acm-fg-4)] hover:text-[var(--acm-fg)] transition-colors">
                <MoreVertical size={16} />
              </button>
            </div>
          </div>

          {/* Messages feed */}
          <div className="flex-1 overflow-y-auto acm-scroll px-[20px] py-[16px] space-y-[16px] relative">
            {/* Floating status badges */}
            {(isRouterLearning || activeSkillNames.length > 0 || memoryRecall) && (
              <div className="sticky top-2 z-10 flex justify-end gap-2 pointer-events-none">
                {memoryRecall && <MemoryRecallIndicator status={memoryRecall.status} count={memoryRecall.count} />}
                {isRouterLearning && <RouterLearningIndicator />}
                {activeSkillNames.length > 0 && <SkillActiveIndicator names={activeSkillNames} />}
              </div>
            )}

            {messages.length === 0 ? (
              <div className="flex flex-col items-center justify-center h-full text-center">
                {isLoadingHistory ? (
                  <>
                    <Loader2 size={28} className="text-[var(--acm-accent)] animate-spin mb-4" />
                    <p className="mono text-[11px] text-[var(--acm-fg-4)]">Loading conversation...</p>
                  </>
                ) : (
                  <>
                    <div className="w-14 h-14 border border-[var(--acm-border)] bg-[var(--acm-card)] rounded-[10px] flex items-center justify-center mb-5 text-[var(--acm-accent)]">
                      <Plus size={24} />
                    </div>
                    <div className="mb-2 flex items-center gap-2">
                      <span className="mono text-[10px] px-[10px] py-[4px] border border-[oklch(0.84_0.16_82/0.3)] bg-[oklch(0.84_0.16_82/0.07)] text-[var(--acm-accent)] rounded-full">
                        New conversation
                      </span>
                    </div>
                    <h3 className="text-[14px] font-semibold text-[var(--acm-fg-2)] mb-2">
                      Ready to start
                    </h3>
                    <p className="mono text-[11px] text-[var(--acm-fg-4)] max-w-xs">
                      This is a fresh conversation. Type your first message below.
                    </p>
                  </>
                )}
              </div>
            ) : (
              messages
                .filter((msg) => showToolLogs || msg.compactionNote || (!msg.toolCall && !msg.validation && !msg.toolConfirmation))
                .map((msg) => {
                  if (msg.validation) {
                    return (
                      <ValidationBubble
                        key={msg.id}
                        tool={msg.validation.tool}
                        steps={msg.validation.steps}
                        done={msg.validation.done}
                        passed={msg.validation.passed}
                      />
                    );
                  }
                  if (msg.toolConfirmation) {
                    return (
                      <ToolConfirmationBubble
                        key={msg.id}
                        confirmId={msg.toolConfirmation.confirmId}
                        tool={msg.toolConfirmation.tool}
                        command={msg.toolConfirmation.command}
                      />
                    );
                  }
                  if (msg.compactionNote) {
                    return (
                      <CompactionNoteBubble
                        key={msg.id}
                        summarizedMessages={msg.compactionNote.summarizedMessages}
                      />
                    );
                  }
                  return (
                    <MessageBubble
                      key={msg.id}
                      content={msg.content}
                      role={msg.role}
                      badge={msg.badge}
                      attachments={msg.attachments}
                      toolCall={msg.toolCall}
                      usage={msg.usage}
                      debugMode={debugMode}
                    />
                  );
                })
            )}

            {isWaitingResponse && <TypingIndicator label={thinkingLabel} />}
            <div ref={messagesEndRef} />
          </div>

          {/* Quick command strip */}
          <div className="px-[16px] py-[8px] border-t border-[var(--acm-border)] bg-[var(--acm-base)] flex items-center gap-[6px] flex-wrap">
            <button
              onClick={startNewConversation}
              className="inline-flex items-center gap-[5px] px-[10px] py-[4px] rounded-full border border-[var(--acm-border)] mono text-[11px] text-[var(--acm-fg-4)] hover:text-[var(--acm-fg)] hover:border-[var(--acm-border-strong)] transition-colors"
            >
              <Plus size={11} />
              New
            </button>
            <button
              onClick={() => executeCommand('/help')}
              className="inline-flex items-center gap-[5px] px-[10px] py-[4px] rounded-full border border-[var(--acm-border)] mono text-[11px] text-[var(--acm-fg-4)] hover:text-[var(--acm-fg)] hover:border-[var(--acm-border-strong)] transition-colors"
            >
              <HelpCircle size={11} />
              Help
            </button>
            <button
              onClick={() => executeCommand('/model')}
              className="inline-flex items-center gap-[5px] px-[10px] py-[4px] rounded-full border border-[var(--acm-border)] mono text-[11px] text-[var(--acm-fg-4)] hover:text-[var(--acm-fg)] hover:border-[var(--acm-border-strong)] transition-colors"
            >
              <Cpu size={11} />
              {modelData?.model ? `Model: ${modelData.model}` : 'Model'}
            </button>
            <button
              onClick={() => executeCommand('/stats')}
              className="inline-flex items-center gap-[5px] px-[10px] py-[4px] rounded-full border border-[var(--acm-border)] mono text-[11px] text-[var(--acm-fg-4)] hover:text-[var(--acm-fg)] hover:border-[var(--acm-border-strong)] transition-colors"
            >
              <BarChart3 size={11} />
              Stats
            </button>
            <button
              onClick={() => executeCommand('/export')}
              className="inline-flex items-center gap-[5px] px-[10px] py-[4px] rounded-full border border-[var(--acm-border)] mono text-[11px] text-[var(--acm-fg-4)] hover:text-[var(--acm-fg)] hover:border-[var(--acm-border-strong)] transition-colors"
            >
              <Download size={11} />
              Export
            </button>
            <button
              onClick={() => { addMessage({ content: '/compact', role: 'user' }); executeCommand('/compact'); }}
              disabled={isCompacting}
              className="inline-flex items-center gap-[5px] px-[10px] py-[4px] rounded-full border border-[var(--acm-border)] mono text-[11px] text-[var(--acm-fg-4)] hover:text-[var(--acm-accent)] hover:border-[oklch(0.84_0.16_82/0.4)] transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              title="Summarize old messages to free up context window"
            >
              {isCompacting ? <Loader2 size={11} className="animate-spin" /> : <ScrollText size={11} />}
              {isCompacting ? 'Compacting…' : 'Compact'}
            </button>
          </div>

          {/* Terminal Panel */}
          <TerminalPanel />

          {/* Composer */}
          <div className="border-t border-[var(--acm-border)] px-[24px] pt-[14px] pb-[18px] bg-[var(--acm-base)]">
            {/* Attachment previews */}
            {currentAttachments.length > 0 && (
              <div className="flex flex-wrap gap-2 mb-3">
                {currentAttachments.map((att) => (
                  <div
                    key={att.id}
                    className="relative flex items-center gap-2 bg-[var(--acm-card)] border border-[var(--acm-border)] rounded-[6px] overflow-hidden text-[12px] text-[var(--acm-fg-3)]"
                  >
                    {att.previewUrl ? (
                      <div className="relative">
                        {/* eslint-disable-next-line @next/next/no-img-element */}
                        <img src={att.previewUrl} alt={att.name} className="h-14 w-14 object-cover" />
                      </div>
                    ) : (
                      <div className="flex items-center gap-2 px-3 py-1.5">
                        {att.type.startsWith('audio/') ? <Music size={13} className="text-[var(--acm-accent)]" /> : <FileText size={13} className="text-[var(--acm-fg-3)]" />}
                        <span className="mono truncate max-w-[120px] text-[11px]">{att.name}</span>
                      </div>
                    )}
                    <button
                      onClick={() => removeAttachment(att.id)}
                      className="absolute top-0.5 right-0.5 bg-[var(--acm-base)]/80 rounded-full p-0.5 text-[var(--acm-fg-4)] hover:text-[var(--acm-err)] transition-colors"
                    >
                      <X size={11} />
                    </button>
                  </div>
                ))}
              </div>
            )}

            {/* Input card */}
            <div className="border border-[var(--acm-border)] rounded-[8px] bg-[var(--acm-card)] px-[12px] pt-[8px] pb-[10px]">
              {/* Prompt prefix row + textarea */}
              <div className="flex items-start gap-[8px]">
                <span className="mono text-[12px] text-[var(--acm-accent)] pt-[10px] select-none flex-shrink-0">›</span>
                <textarea
                  value={inputValue}
                  onChange={(e) => setInputValue(e.target.value)}
                  onKeyDown={handleKeyDown}
                  onPaste={handlePaste}
                  placeholder="Type a message, or paste an image..."
                  rows={1}
                  className="flex-1 bg-transparent text-[var(--acm-fg)] placeholder-[var(--acm-fg-4)] resize-none focus:outline-none text-[13.5px] leading-relaxed pt-[8px]"
                  style={{ minHeight: '38px', maxHeight: '120px' }}
                />
              </div>

              {/* Toolbar */}
              <div className="flex items-center gap-[4px] mt-[6px] pt-[6px] border-t border-[var(--acm-border)]">
                {/* Attach */}
                <button
                  onClick={() => fileInputRef.current?.click()}
                  disabled={isUploading}
                  className="flex items-center gap-[4px] px-[8px] py-[4px] rounded-[4px] text-[var(--acm-fg-3)] hover:text-[var(--acm-fg)] text-[11.5px] transition-colors disabled:opacity-50"
                  title="Attach file (image, PDF, audio, text...)"
                >
                  {isUploading ? <Loader2 size={13} className="animate-spin" /> : <Paperclip size={13} />}
                  <span className="mono">Attach</span>
                </button>
                <input
                  ref={fileInputRef}
                  type="file"
                  multiple
                  accept="image/*,audio/*,.pdf,.txt,.md,.csv,.json,.yaml,.yml,.xml,.html,.log"
                  className="hidden"
                  onChange={handleFileSelect}
                />

                {/* Voice */}
                <button
                  onClick={handleMicClick}
                  disabled={isUploading}
                  className={cn(
                    "flex items-center gap-[4px] px-[8px] py-[4px] rounded-[4px] text-[11.5px] transition-colors disabled:opacity-50 mono",
                    isRecording
                      ? "text-[var(--acm-err)] acm-pulse"
                      : "text-[var(--acm-fg-3)] hover:text-[var(--acm-fg)]"
                  )}
                  title={isRecording ? "Stop recording" : "Record voice message"}
                >
                  {isRecording ? <MicOff size={13} /> : <Mic size={13} />}
                  <span>{isRecording ? 'Stop' : 'Voice'}</span>
                </button>

                <div className="flex-1" />

                {/* Send / Cancel */}
                {isWaitingResponse ? (
                  <button
                    onClick={() => cancelMessage?.()}
                    className="btn-secondary !py-[5px] !px-[12px] !text-[12px] border-[var(--acm-err)] text-[var(--acm-err)] hover:border-[var(--acm-err)] hover:text-[var(--acm-err)]"
                    title="Cancel"
                  >
                    <X size={12} />
                    Cancel
                  </button>
                ) : (
                  <button
                    onClick={handleSend}
                    disabled={(!inputValue.trim() && currentAttachments.length === 0) || isUploading}
                    className="btn-primary !py-[5px] !px-[12px] !text-[12px]"
                  >
                    <Send size={12} />
                    Send
                  </button>
                )}
              </div>
            </div>

            <p className="mono text-[10px] text-[var(--acm-fg-4)] mt-[8px] text-center">
              Enter to send · Shift+Enter new line · Paste images directly
              <span className="mx-2 text-[var(--acm-border-strong)]">·</span>
              <span>All data stays local</span>
            </p>
          </div>
        </div>
      </div>
      {/* Tool confirmation modal (yolo mode safety gate) */}
      {activeConfirmation && (
        <ToolConfirmationModal
          key={activeConfirmation.confirmId}
          confirmId={activeConfirmation.confirmId}
          tool={activeConfirmation.tool}
          command={activeConfirmation.command}
          onClose={() => setActiveConfirmation(null)}
        />
      )}
    </AppLayout>
  );
}
