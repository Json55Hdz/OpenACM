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
    <div className="flex items-center gap-1.5 px-3 py-1.5 bg-violet-950/80 border border-violet-500/40 rounded-full text-violet-300 text-xs font-medium shadow-lg backdrop-blur-sm animate-pulse">
      <Sparkles size={12} className="text-violet-400" />
      <span>Aprendiendo...</span>
    </div>
  );
}

function MemoryRecallIndicator({ status, count }: {
  status: 'searching' | 'found' | 'empty' | 'saving' | 'saved';
  count: number;
}) {
  const isBusy   = status === 'searching' || status === 'saving';
  const isGood   = status === 'found' || status === 'saved';
  const isEmpty  = status === 'empty';

  const label =
    status === 'searching' ? 'Searching memory...' :
    status === 'found'     ? `Memory: ${count} ${count === 1 ? 'fragment' : 'fragments'}` :
    status === 'saving'    ? 'Saving to memory...' :
    status === 'saved'     ? 'Saved to memory' :
                             'No memory results';

  return (
    <div className={cn(
      'flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium shadow-lg backdrop-blur-sm border transition-all duration-300',
      isBusy  && 'bg-indigo-950/80 border-indigo-500/40 text-indigo-300',
      isGood  && 'bg-indigo-950/80 border-indigo-400/50 text-indigo-200',
      isEmpty && 'bg-slate-900/80 border-slate-700/40 text-slate-400',
    )}>
      <BrainCircuit size={12} className={cn(
        isBusy  && 'animate-pulse text-indigo-400',
        isGood  && 'text-indigo-300',
        isEmpty && 'text-slate-500',
      )} />
      <span>{label}</span>
    </div>
  );
}

function SkillActiveIndicator({ names }: { names: string[] }) {
  const label = names
    .map((n) => n.replace(/-/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase()))
    .join(', ');
  return (
    <div className="flex items-center gap-1.5 px-3 py-1.5 bg-emerald-950/80 border border-emerald-500/40 rounded-full text-emerald-300 text-xs font-medium shadow-lg backdrop-blur-sm">
      <span className="relative flex h-2 w-2">
        <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
        <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500" />
      </span>
      <span>Skill: {label}</span>
    </div>
  );
}

function TypingIndicator({ label }: { label?: string | null }) {
  return (
    <div className="flex items-center gap-2 px-4 py-3 bg-slate-800 rounded-2xl rounded-tl-sm w-fit max-w-xs">
      <div className="flex items-center gap-1 flex-shrink-0">
        <div className="w-2 h-2 bg-slate-400 rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
        <div className="w-2 h-2 bg-slate-400 rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
        <div className="w-2 h-2 bg-slate-400 rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
      </div>
      {label && <span className="text-xs text-slate-300 truncate">{label}</span>}
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
    if (status === 'running') return <Loader2 size={13} className="animate-spin text-blue-400 flex-shrink-0" />;
    if (status === 'passed')  return <CheckCircle2 size={13} className="text-emerald-400 flex-shrink-0" />;
    if (status === 'warning') return <AlertTriangle size={13} className="text-amber-400 flex-shrink-0" />;
    return <XCircle size={13} className="text-red-400 flex-shrink-0" />;
  };

  const headerColor = !done
    ? 'text-blue-300 border-blue-600/30 bg-blue-950/40'
    : passed
      ? 'text-emerald-300 border-emerald-600/30 bg-emerald-950/40'
      : 'text-red-300 border-red-600/30 bg-red-950/40';

  const headerLabel = !done
    ? 'Validando...'
    : passed
      ? 'Tests pasados — listo para aplicar'
      : 'Tests fallaron — corrige los errores';

  return (
    <div className="flex gap-3">
      <div className="w-8 h-8 rounded-full flex items-center justify-center flex-shrink-0 bg-violet-700">
        <FlaskConical size={15} className="text-white" />
      </div>
      <div className="flex flex-col max-w-[85%] items-start">
        <span className="text-xs text-slate-500 mb-1">Validación automática</span>
        <div className={cn('px-4 py-3 rounded-2xl rounded-tl-sm border w-full', headerColor)}>
          <div className="flex items-center gap-2 mb-3">
            {!done && <Loader2 size={14} className="animate-spin" />}
            {done && passed && <CheckCircle2 size={14} className="text-emerald-400" />}
            {done && !passed && <XCircle size={14} className="text-red-400" />}
            <span className="font-medium text-sm">{`Tool: ${tool}`}</span>
            <span className="text-xs opacity-70 ml-auto">{headerLabel}</span>
          </div>
          <div className="space-y-1.5">
            {visibleSteps.map((s) => (
              <div key={s.step} className="flex items-start gap-2 text-xs">
                {stepIcon(s.status)}
                <span className="font-medium w-28 flex-shrink-0 opacity-90">{s.step}</span>
                <span className="opacity-60 truncate">{s.detail}</span>
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
      <div className="w-8 h-8 rounded-full flex items-center justify-center flex-shrink-0 bg-orange-600">
        <ShieldCheck size={16} className="text-white" />
      </div>
      <div className="flex flex-col max-w-[85%] items-start">
        <span className="text-xs text-slate-500 mb-1">Confirm</span>
        <div className="px-4 py-3 rounded-2xl rounded-tl-sm border border-orange-600/40 bg-orange-950/30 text-orange-200 w-full">
          <div className="flex items-center gap-2 mb-2">
            <ShieldCheck size={14} className="text-orange-400" />
            <span className="font-medium text-sm">Permission required — {tool}</span>
          </div>
          <div className="text-xs font-mono bg-slate-900/60 rounded-lg px-3 py-2 mb-3 text-slate-300 break-all">
            {command}
          </div>
          {resolved === null ? (
            <div className="flex flex-wrap gap-2">
              <button
                disabled={loading}
                onClick={() => resolve(true)}
                className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white transition-colors disabled:opacity-50"
              >
                {loading ? <Loader2 size={12} className="animate-spin" /> : <CheckCircle2 size={12} />}
                Allow
              </button>
              <button
                disabled={loading}
                onClick={() => resolve(true, true)}
                className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg bg-amber-600 hover:bg-amber-500 text-white transition-colors disabled:opacity-50"
              >
                <Infinity size={12} />
                Always (session)
              </button>
              <button
                disabled={loading}
                onClick={() => resolve(false)}
                className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg bg-red-700 hover:bg-red-600 text-white transition-colors disabled:opacity-50"
              >
                <XCircle size={12} />
                Deny
              </button>
            </div>
          ) : (
            <div className={cn(
              'flex items-center gap-1.5 text-xs font-medium',
              resolved === 'approved' ? 'text-emerald-400'
              : resolved === 'session' ? 'text-amber-400'
              : 'text-red-400',
            )}>
              {resolved === 'approved' && <><CheckCircle2 size={12} /> Allowed</>}
              {resolved === 'session' && <><Infinity size={12} /> Allowed this session</>}
              {resolved === 'denied' && <><XCircle size={12} /> Denied</>}
            </div>
          )}
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
            p: ({ children }) => <p className="mb-2 last:mb-0 leading-relaxed">{children}</p>,
            h1: ({ children }) => <h1 className="text-xl font-bold text-white mt-4 mb-2 first:mt-0">{children}</h1>,
            h2: ({ children }) => <h2 className="text-lg font-semibold text-white mt-3 mb-1.5 first:mt-0">{children}</h2>,
            h3: ({ children }) => <h3 className="text-base font-semibold text-slate-200 mt-2 mb-1 first:mt-0">{children}</h3>,
            strong: ({ children }) => <strong className="font-semibold text-white">{children}</strong>,
            em: ({ children }) => <em className="italic text-slate-300">{children}</em>,
            ul: ({ children }) => <ul className="list-disc list-inside space-y-1 my-2 pl-2">{children}</ul>,
            ol: ({ children }) => <ol className="list-decimal list-inside space-y-1 my-2 pl-2">{children}</ol>,
            li: ({ children }) => <li className="text-slate-200">{children}</li>,
            code: ({ children, className }) => {
              const isBlock = className?.includes('language-');
              return isBlock
                ? <code className="block bg-slate-950 text-green-300 rounded-lg px-4 py-3 my-2 text-sm font-mono overflow-x-auto whitespace-pre">{children}</code>
                : <code className="bg-slate-800 text-blue-300 rounded px-1.5 py-0.5 text-sm font-mono">{children}</code>;
            },
            pre: ({ children }) => <>{children}</>,
            blockquote: ({ children }) => <blockquote className="border-l-2 border-blue-500 pl-3 my-2 text-slate-400 italic">{children}</blockquote>,
            a: ({ href, children }) => <a href={href} target="_blank" rel="noopener noreferrer" className="text-blue-400 hover:text-blue-300 underline underline-offset-2">{children}</a>,
            hr: () => <hr className="border-slate-700 my-3" />,
            table: ({ children }) => <div className="overflow-x-auto my-2"><table className="text-sm border-collapse w-full">{children}</table></div>,
            th: ({ children }) => <th className="border border-slate-600 px-3 py-1.5 bg-slate-800 text-left font-semibold text-slate-200">{children}</th>,
            td: ({ children }) => <td className="border border-slate-700 px-3 py-1.5 text-slate-300">{children}</td>,
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
              <div key={idx} className="rounded-lg overflow-hidden border border-slate-600">
                {isImage && (
                  <img
                    src={previewUrl}
                    alt={filename}
                    className="max-w-xs max-h-64 object-contain bg-slate-900 block"
                  />
                )}
                <div className="flex items-center gap-2 px-3 py-2 bg-slate-700/60 text-xs">
                  <Paperclip size={12} className="text-slate-400 flex-shrink-0" />
                  <span className="truncate text-slate-300 flex-1">{filename}</span>
                  <a
                    href={downloadUrl}
                    download={filename}
                    className="flex items-center gap-1 px-2 py-1 bg-blue-600 hover:bg-blue-500 text-white rounded transition-colors flex-shrink-0"
                  >
                    <Download size={11} />
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
        className="flex items-center gap-2 text-[10px] text-slate-500 hover:text-slate-300 transition-colors group"
      >
        <span className="flex items-center gap-0.5">
          <ArrowUp size={9} className="text-blue-400" />
          {fmt(usage.prompt_tokens)}
        </span>
        <span className="flex items-center gap-0.5">
          <ArrowDown size={9} className="text-purple-400" />
          {fmt(usage.completion_tokens)}
        </span>
        {usage.cost > 0 && (
          <span className="flex items-center gap-0.5 text-amber-500">
            <DollarSign size={9} />
            {usage.cost < 0.001 ? '<$0.001' : `$${usage.cost.toFixed(4)}`}
          </span>
        )}
        <Info size={9} className="opacity-0 group-hover:opacity-100 transition-opacity" />
        {open ? <ChevronUp size={9} /> : <ChevronDown size={9} />}
      </button>

      {open && (
        <div className="mt-1 bg-slate-900 border border-slate-700 rounded-lg p-3 text-[11px] space-y-1.5 text-slate-400 font-mono max-w-xs">
          <div className="flex justify-between">
            <span className="text-slate-500">Model</span>
            <span className="text-slate-200">{usage.model || '—'}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-slate-500">Input tokens</span>
            <span className="text-blue-400">{usage.prompt_tokens.toLocaleString()}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-slate-500">Output tokens</span>
            <span className="text-purple-400">{usage.completion_tokens.toLocaleString()}</span>
          </div>
          <div className="flex justify-between border-t border-slate-700 pt-1.5">
            <span className="text-slate-500">Total tokens</span>
            <span className="text-white">{usage.total_tokens.toLocaleString()}</span>
          </div>
          {usage.cost > 0 && (
            <div className="flex justify-between">
              <span className="text-slate-500">Est. cost</span>
              <span className="text-amber-400">
                ${usage.cost < 0.000001 ? '< $0.000001' : usage.cost.toFixed(6)}
              </span>
            </div>
          )}
          {usage.requests > 1 && (
            <div className="flex justify-between">
              <span className="text-slate-500">LLM calls</span>
              <span>{usage.requests}</span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function CompactionNoteBubble({
  summary,
  summarizedMessages,
}: {
  summary: string;
  summarizedMessages: number;
}) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="flex items-start gap-3 px-2">
      <div className="flex-1 border border-dashed border-slate-600/60 rounded-xl bg-slate-900/50 px-4 py-3">
        <div className="flex items-center gap-2 text-slate-400 text-xs mb-1">
          <ScrollText size={13} className="text-indigo-400 flex-shrink-0" />
          <span className="font-medium text-indigo-300">Conversación compactada</span>
          <span className="text-slate-600">·</span>
          <span>{summarizedMessages} mensajes resumidos</span>
          <button
            onClick={() => setExpanded(!expanded)}
            className="ml-auto flex items-center gap-1 text-slate-500 hover:text-slate-300 transition-colors"
          >
            {expanded ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
            {expanded ? 'Ocultar' : 'Ver resumen'}
          </button>
        </div>
        {expanded && (
          <div className="mt-2 text-xs text-slate-400 leading-relaxed border-t border-slate-700/50 pt-2">
            {summary}
          </div>
        )}
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
  const isUser = role === 'user';
  const isError = role === 'error';
  const isSystem = role === 'system';
  const token = useAuthStore((s) => s.token);
  
  // System/tool messages have different styling
  if (isSystem && toolCall) {
    return (
      <div className="flex gap-3">
        <div className="w-8 h-8 rounded-full flex items-center justify-center flex-shrink-0 bg-amber-600">
          <Wrench size={16} className="text-white" />
        </div>
        
        <div className="flex flex-col max-w-[85%] items-start">
          {badge && (
            <span className="text-xs text-slate-500 mb-1">{badge}</span>
          )}
          
          <div className="px-4 py-3 rounded-2xl bg-amber-900/30 text-amber-200 border border-amber-600/30 rounded-tl-sm">
            <div className="flex items-center gap-2 mb-2">
              {toolCall.status === 'running' && <Loader2 size={14} className="animate-spin" />}
              {toolCall.status === 'completed' && <span className="text-green-400">✓</span>}
              {toolCall.status === 'error' && <span className="text-red-400">✗</span>}
              <span className="font-medium">{toolCall.tool}</span>
            </div>
            
            {toolCall.arguments && (
              <div className="text-xs text-amber-300/70 mb-2">
                <span className="font-mono">{toolCall.arguments}</span>
              </div>
            )}
            
            {toolCall.result && (
              <div className="text-sm text-slate-300 border-t border-amber-600/20 pt-2 mt-2">
                {toolCall.result}
              </div>
            )}
          </div>
        </div>
      </div>
    );
  }
  
  return (
    <div className={cn(
      "flex gap-3",
      isUser ? "flex-row-reverse" : ""
    )}>
      <div className={cn(
        "w-8 h-8 rounded-full flex items-center justify-center flex-shrink-0",
        isUser ? "bg-blue-600" : isError ? "bg-red-600" : "bg-purple-600"
      )}>
        {isUser ? <User size={16} className="text-white" /> : <Bot size={16} className="text-white" />}
      </div>
      
      <div className={cn(
        "flex flex-col max-w-[75%]",
        isUser ? "items-end" : "items-start"
      )}>
        {badge && (
          <span className="text-xs text-slate-500 mb-1">{badge}</span>
        )}
        
        <div className={cn(
          "px-4 py-3 rounded-2xl",
          isUser
            ? "bg-blue-600 text-white rounded-tr-sm"
            : isError
              ? "bg-red-500/20 text-red-200 border border-red-500/30 rounded-tl-sm"
              : isSystem
                ? "bg-slate-900/80 text-slate-300 border border-slate-600/50 rounded-tl-sm text-sm"
                : "bg-slate-800 text-slate-200 border border-slate-700 rounded-tl-sm"
        )}>
          <MessageContent content={content} token={token} />

          {attachments && attachments.length > 0 && (
            <div className="mt-3 space-y-2">
              {attachments.map((att, idx) => {
                const fileId = att.id || att.name;
                const isMedia = /\.(png|jpg|jpeg|gif|webp)$/i.test(att.name);
                const downloadUrl = `/api/media/${fileId}?download=true&token=${token}`;
                const previewUrl = `/api/media/${fileId}?token=${token}`;
                return (
                  <div key={idx} className="rounded-lg overflow-hidden border border-slate-600">
                    {isMedia && (
                      <img
                        src={previewUrl}
                        alt={att.name}
                        className="max-w-xs max-h-48 object-contain bg-slate-900"
                      />
                    )}
                    <div className="flex items-center gap-2 px-3 py-2 bg-slate-700/60 text-xs">
                      <Paperclip size={12} className="text-slate-400 flex-shrink-0" />
                      <span className="truncate text-slate-300 flex-1">{att.name}</span>
                      <a
                        href={downloadUrl}
                        download={att.name}
                        className="flex items-center gap-1 px-2 py-1 bg-blue-600 hover:bg-blue-500 text-white rounded transition-colors flex-shrink-0"
                      >
                        <Download size={11} />
                        Download
                      </a>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>

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
  const fileInputRef = useRef<HTMLInputElement>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);
  // Track which conversation we last loaded history for
  const loadedKeyRef = useRef('');
  // Only show reconnecting overlay after first successful connection
  const hasConnectedRef = useRef(false);
  useEffect(() => { if (wsConnected) hasConnectedRef.current = true; }, [wsConnected]);
  const showReconnecting = hasConnectedRef.current && !wsConnected;

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
      // Compact responses are shown via the memory.compacted WS event bubble — skip the text
      if (result.text && !result.data?.compact) {
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
      <div className="h-screen flex">
        {/* Sidebar - Conversation List */}
        <div className={cn(
          "fixed lg:static inset-y-0 left-0 w-80 bg-slate-900 border-r border-slate-800 z-30 transition-transform duration-300",
          isSidebarOpen ? "translate-x-0" : "-translate-x-full lg:translate-x-0 lg:w-0 lg:overflow-hidden lg:border-r-0"
        )}>
          <div className="flex flex-col h-full">
            {/* Header */}
            <div className="p-4 border-b border-slate-800">
              <div className="flex items-center justify-between mb-3">
                <h2 className="text-lg font-semibold text-white">Conversations</h2>
                <button
                  onClick={() => setIsSidebarOpen(false)}
                  className="lg:hidden p-1 text-slate-400 hover:text-white"
                >
                  <X size={20} />
                </button>
              </div>
              {systemInfo?.messages_encrypted && (
                <div className="flex items-center gap-1.5 px-2.5 py-1.5 mb-3 rounded-lg bg-emerald-950/50 border border-emerald-700/30 text-emerald-400 text-xs">
                  <ShieldCheck size={13} className="shrink-0" />
                  <span>Messages encrypted at rest</span>
                </div>
              )}
              <button
                onClick={startNewConversation}
                className="w-full flex items-center justify-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg transition-colors"
              >
                <Plus size={18} />
                <span>New Conversation</span>
              </button>
            </div>
            
            {/* Conversation List */}
            <div className="flex-1 overflow-y-auto p-2 space-y-1">
              {conversationList.map((conv) => {
                const convKey = `${conv.channel_id}-${conv.user_id}`;
                const isActive = currentTarget.channel === conv.channel_id && currentTarget.user === conv.user_id;
                const isDeleting = deletingKey === convKey;
                const isDeletable = conv.channel_id !== 'console';
                return (
                  <div
                    key={convKey}
                    className={cn(
                      "group relative w-full text-left p-3 rounded-lg transition-colors cursor-pointer",
                      isActive
                        ? "bg-blue-600/20 border border-blue-600/30"
                        : "hover:bg-slate-800 border border-transparent"
                    )}
                    onClick={() => selectConversation(conv)}
                  >
                    <div className="flex items-center gap-3">
                      <div className="w-10 h-10 bg-slate-800 rounded-full flex items-center justify-center shrink-0">
                        <MessageSquare size={18} className="text-slate-400" />
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-1.5">
                          <p className="text-sm font-medium text-slate-200 truncate">
                            {conv.title || `${conv.channel_id} - ${conv.user_id}`}
                          </p>
                          {conv.message_count === 0 && (
                            <span className="shrink-0 text-[10px] font-semibold px-1.5 py-0.5 bg-blue-500/15 text-blue-400 rounded-full border border-blue-500/20">
                              New
                            </span>
                          )}
                        </div>
                        <p className="text-xs text-slate-500 truncate">
                          {conv.last_message || 'No messages yet'}
                        </p>
                      </div>
                      {/* Message count — hidden when delete button is visible */}
                      {conv.message_count > 0 && (
                        <span className="text-xs text-slate-500 group-hover:hidden">
                          {conv.message_count}
                        </span>
                      )}
                      {/* Delete button — only for external channels (not web/console), shown on hover */}
                      {isDeletable && (
                        <button
                          onClick={(e) => handleDeleteConversation(conv, e)}
                          disabled={isDeleting}
                          className={cn(
                            "hidden group-hover:flex items-center justify-center w-7 h-7 rounded-md transition-colors shrink-0",
                            "text-slate-500 hover:text-red-400 hover:bg-red-500/10",
                            isDeleting && "!flex"
                          )}
                          title="Delete conversation"
                        >
                          {isDeleting
                            ? <Loader2 size={14} className="animate-spin" />
                            : <Trash2 size={14} />
                          }
                        </button>
                      )}
                    </div>
                  </div>
                );
              })}
              
              {conversationList.length === 0 && (
                <div className="text-center py-8">
                  <MessageSquare size={48} className="mx-auto text-slate-600 mb-2" />
                  <p className="text-sm text-slate-500">No conversations yet</p>
                </div>
              )}
            </div>
          </div>
        </div>
        
        {/* Main Chat Area */}
        <div className="flex-1 flex flex-col min-w-0 bg-slate-950 relative">
          {/* Reconnecting overlay — shown only after first connection, when backend drops */}
          {showReconnecting && (
            <div className="absolute inset-0 z-50 flex flex-col items-center justify-center bg-slate-950/90 backdrop-blur-sm">
              <Loader2 size={36} className="text-blue-400 animate-spin mb-4" />
              <p className="text-slate-200 text-sm font-medium">Reconnecting to backend…</p>
              <p className="text-slate-500 text-xs mt-1">Your conversation will resume automatically</p>
            </div>
          )}
          {/* Chat Header */}
          <div className="flex items-center justify-between px-4 py-3 border-b border-slate-800 bg-slate-900/50">
            <div className="flex items-center gap-3">
              <button
                onClick={() => setIsSidebarOpen(true)}
                className="lg:hidden p-2 text-slate-400 hover:text-white"
              >
                <MessageSquare size={20} />
              </button>
              <div>
                <h3 className="font-semibold text-white">{currentTarget.title}</h3>
                <p className="text-xs text-slate-500">{currentTarget.channel} • {currentTarget.user}</p>
              </div>
            </div>
            
            <div className="flex items-center gap-2">
              <button
                onClick={() => setShowToolLogs(!showToolLogs)}
                className={cn(
                  "px-3 py-1.5 text-sm rounded-lg transition-colors",
                  showToolLogs
                    ? "bg-blue-600/20 text-blue-400 border border-blue-600/30"
                    : "text-slate-400 hover:bg-slate-800"
                )}
              >
                Tool Logs
              </button>
              <button
                onClick={toggleTerminal}
                className={cn(
                  "px-3 py-1.5 text-sm rounded-lg transition-colors flex items-center gap-1.5",
                  isTerminalOpen
                    ? "bg-emerald-600/20 text-emerald-400 border border-emerald-600/30"
                    : "text-slate-400 hover:bg-slate-800"
                )}
              >
                <SquareTerminal size={14} />
                Terminal
              </button>
              <button className="p-2 text-slate-400 hover:text-white">
                <MoreVertical size={20} />
              </button>
            </div>
          </div>
          
          {/* Messages Area */}
          <div className="flex-1 overflow-y-auto p-4 space-y-4 relative">
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
                    <Loader2 size={32} className="text-slate-400 animate-spin mb-4" />
                    <p className="text-sm text-slate-500">Loading conversation...</p>
                  </>
                ) : (
                  <>
                    <div className="w-16 h-16 bg-blue-500/10 border border-blue-500/20 rounded-full flex items-center justify-center mb-4">
                      <Plus size={28} className="text-blue-400" />
                    </div>
                    <div className="mb-2 flex items-center gap-2">
                      <span className="px-2 py-0.5 text-xs font-semibold bg-blue-500/10 text-blue-400 border border-blue-500/20 rounded-full">
                        New conversation
                      </span>
                    </div>
                    <h3 className="text-lg font-medium text-slate-300 mb-2">
                      Ready to start
                    </h3>
                    <p className="text-sm text-slate-500 max-w-sm">
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
                        summary={msg.compactionNote.summary}
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
          
          {/* Command Buttons */}
          <div className="px-4 py-2 border-t border-slate-800 bg-slate-900/30 flex items-center gap-2 flex-wrap">
            <button
              onClick={startNewConversation}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-full bg-slate-800 text-slate-300 hover:bg-slate-700 hover:text-white border border-slate-700 transition-colors"
            >
              <Plus size={13} />
              New
            </button>
            <button
              onClick={() => executeCommand('/help')}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-full bg-slate-800 text-slate-300 hover:bg-slate-700 hover:text-white border border-slate-700 transition-colors"
            >
              <HelpCircle size={13} />
              Help
            </button>
            <button
              onClick={() => executeCommand('/model')}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-full bg-slate-800 text-slate-300 hover:bg-slate-700 hover:text-white border border-slate-700 transition-colors"
            >
              <Cpu size={13} />
              {modelData?.model ? `Model: ${modelData.model}` : 'Model'}
            </button>
            <button
              onClick={() => executeCommand('/stats')}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-full bg-slate-800 text-slate-300 hover:bg-slate-700 hover:text-white border border-slate-700 transition-colors"
            >
              <BarChart3 size={13} />
              Stats
            </button>
            <button
              onClick={() => executeCommand('/export')}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-full bg-slate-800 text-slate-300 hover:bg-slate-700 hover:text-white border border-slate-700 transition-colors"
            >
              <Download size={13} />
              Export
            </button>
            <button
              onClick={() => { addMessage({ content: '/compact', role: 'user' }); executeCommand('/compact'); }}
              disabled={isCompacting}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-full border transition-colors disabled:opacity-50 disabled:cursor-not-allowed bg-indigo-950/60 text-indigo-300 hover:bg-indigo-900/60 hover:text-indigo-100 border-indigo-700/50"
              title="Summarize old messages to free up context window"
            >
              {isCompacting ? <Loader2 size={13} className="animate-spin" /> : <ScrollText size={13} />}
              {isCompacting ? 'Compacting…' : 'Compact'}
            </button>
          </div>

          {/* Terminal Panel */}
          <TerminalPanel />

          {/* Input Area */}
          <div className="p-4 border-t border-slate-800 bg-slate-900/50">
            {/* Attachments preview */}
            {currentAttachments.length > 0 && (
              <div className="flex flex-wrap gap-2 mb-3">
                {currentAttachments.map((att) => (
                  <div
                    key={att.id}
                    className="relative flex items-center gap-2 bg-slate-800 rounded-lg overflow-hidden text-sm text-slate-300"
                  >
                    {att.previewUrl ? (
                      // Image thumbnail
                      <div className="relative">
                        {/* eslint-disable-next-line @next/next/no-img-element */}
                        <img src={att.previewUrl} alt={att.name} className="h-16 w-16 object-cover" />
                      </div>
                    ) : (
                      <div className="flex items-center gap-2 px-3 py-1.5">
                        {att.type.startsWith('audio/') ? <Music size={14} className="text-violet-400" /> : <FileText size={14} className="text-blue-400" />}
                        <span className="truncate max-w-[120px]">{att.name}</span>
                      </div>
                    )}
                    <button
                      onClick={() => removeAttachment(att.id)}
                      className="absolute top-0.5 right-0.5 bg-slate-900/80 rounded-full p-0.5 text-slate-400 hover:text-red-400"
                    >
                      <X size={12} />
                    </button>
                  </div>
                ))}
              </div>
            )}

            <div className="flex items-end gap-2">
              {/* Attach file */}
              <button
                onClick={() => fileInputRef.current?.click()}
                disabled={isUploading}
                className="p-3 text-slate-400 hover:text-white hover:bg-slate-800 rounded-lg transition-colors disabled:opacity-50"
                title="Attach file (image, PDF, audio, text...)"
              >
                {isUploading ? <Loader2 size={20} className="animate-spin" /> : <Paperclip size={20} />}
              </button>
              <input
                ref={fileInputRef}
                type="file"
                multiple
                accept="image/*,audio/*,.pdf,.txt,.md,.csv,.json,.yaml,.yml,.xml,.html,.log"
                className="hidden"
                onChange={handleFileSelect}
              />

              {/* Mic button */}
              <button
                onClick={handleMicClick}
                disabled={isUploading}
                className={cn(
                  "p-3 rounded-lg transition-colors disabled:opacity-50",
                  isRecording
                    ? "bg-red-600 hover:bg-red-700 text-white animate-pulse"
                    : "text-slate-400 hover:text-white hover:bg-slate-800"
                )}
                title={isRecording ? "Stop recording" : "Record voice message"}
              >
                {isRecording ? <MicOff size={20} /> : <Mic size={20} />}
              </button>

              <div className="flex-1 relative">
                <textarea
                  value={inputValue}
                  onChange={(e) => setInputValue(e.target.value)}
                  onKeyDown={handleKeyDown}
                  onPaste={handlePaste}
                  placeholder="Type a message, or paste an image..."
                  rows={1}
                  className="w-full px-4 py-3 bg-slate-800 border border-slate-700 rounded-lg text-white placeholder-slate-500 resize-none focus:outline-none focus:border-blue-500"
                  style={{ minHeight: '48px', maxHeight: '120px' }}
                />
              </div>

              {isWaitingResponse ? (
                <button
                  onClick={() => cancelMessage?.()}
                  className="p-3 bg-red-600 hover:bg-red-700 text-white rounded-lg transition-colors"
                  title="Cancel"
                >
                  <X size={20} />
                </button>
              ) : (
                <button
                  onClick={handleSend}
                  disabled={(!inputValue.trim() && currentAttachments.length === 0) || isUploading}
                  className="p-3 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed text-white rounded-lg transition-colors"
                >
                  <Send size={20} />
                </button>
              )}
            </div>

            <p className="text-xs text-slate-500 mt-2 text-center">
              Enter to send · Shift+Enter new line · Paste images directly
              <span className="mx-2 text-slate-700">·</span>
              <span className="text-slate-600">All data stays local — nothing is shared with OpenACM servers</span>
            </p>
          </div>
        </div>
      </div>
    </AppLayout>
  );
}
