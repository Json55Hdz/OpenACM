'use client';

import { useEffect, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Paperclip, Bot, User, Loader2, Wrench, Download, Sparkles, ChevronDown, ChevronUp, DollarSign, ArrowUp, ArrowDown, Info, ScrollText } from 'lucide-react';
import { useAuthStore } from '@/stores/auth-store';
import type { MessageUsage } from '@/stores/chat-store';
import { cn } from './shared';

// Captures the filename (everything after /api/media/ up to whitespace or end).
const MEDIA_LINK_RE = /\/api\/media\/([\w.\-]+)/g;


export function MessageContent({ content, token }: { content: string; token: string | null }) {
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

export function fmt(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return String(n);
}

export function TokenBadge({ usage }: { usage: MessageUsage }) {
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

export function ReasoningBubble({ content, workerName, streaming }: { content: string; workerName?: string; streaming?: boolean }) {
  const [open, setOpen] = useState(false);
  const preRef = useRef<HTMLPreElement>(null);
  const lines = content.split('\n').length;

  // Auto-open while streaming and keep scrolled to bottom
  useEffect(() => {
    if (streaming) setOpen(true);
  }, [streaming]);

  useEffect(() => {
    if (streaming && preRef.current) {
      preRef.current.scrollTop = preRef.current.scrollHeight;
    }
  }, [content, streaming]);

  return (
    <div className="flex items-start px-2">
      <div className="w-full border border-[var(--acm-border)] rounded-[6px] overflow-hidden bg-[var(--acm-card)]">
        <button
          onClick={() => setOpen(v => !v)}
          className="w-full flex items-center gap-[8px] px-[12px] py-[7px] text-[11px] hover:bg-[var(--acm-elev)] transition-colors"
        >
          {streaming
            ? <Loader2 size={11} className="text-[oklch(0.75_0.12_280)] flex-shrink-0 animate-spin" />
            : <Sparkles size={11} className="text-[oklch(0.75_0.12_280)] flex-shrink-0" />
          }
          <span className="mono font-medium text-[oklch(0.75_0.12_280)]">
            {streaming
              ? (workerName ? `${workerName} — thinking...` : 'Thinking...')
              : (workerName ? `${workerName} — thinking` : 'Thinking')
            }
          </span>
          {!streaming && (
            <>
              <span className="text-[var(--acm-border-strong)]">·</span>
              <span className="mono text-[var(--acm-fg-4)]">{lines} lines</span>
            </>
          )}
          <span className="ml-auto text-[var(--acm-fg-4)]">{open ? '↑ collapse' : '↓ expand'}</span>
        </button>
        {open && (
          <pre ref={preRef} className="px-[12px] pb-[10px] text-[11px] text-[var(--acm-fg-3)] mono whitespace-pre-wrap leading-relaxed max-h-96 overflow-y-auto border-t border-[var(--acm-border)]">
            {content}
            {streaming && <span className="inline-block w-[5px] h-[10px] bg-[oklch(0.75_0.12_280)] animate-pulse ml-[2px] align-middle" />}
          </pre>
        )}
      </div>
    </div>
  );
}

export function CompactionNoteBubble({
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

export function MessageBubble({
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
