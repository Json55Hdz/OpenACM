'use client';

import { useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Bot, Paperclip, Download, Wrench, ChevronDown, ChevronUp, Loader2 } from 'lucide-react';
import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';

function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

const MEDIA_LINK_RE = /\/api\/media\/([\w.\-]+)/g;

export function MessageContent({ content, token }: { content: string; token?: string | null }) {
  const mediaMatches: { filename: string; index: number; fullMatch: string }[] = [];
  let m: RegExpExecArray | null;
  MEDIA_LINK_RE.lastIndex = 0;
  while ((m = MEDIA_LINK_RE.exec(content)) !== null) {
    mediaMatches.push({ filename: m[1], index: m.index, fullMatch: m[0] });
  }

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
        <div className={cn('space-y-2', cleanText && 'mt-3')}>
          {mediaMatches.map(({ filename }, idx) => {
            const isImage = /\.(png|jpg|jpeg|gif|webp)$/i.test(filename);
            const previewUrl = `/api/media/${filename}${token ? `?token=${token}` : ''}`;
            const downloadUrl = `/api/media/${filename}?download=true${token ? `&token=${token}` : ''}`;
            return (
              <div key={idx} className="rounded-[6px] overflow-hidden border border-[var(--acm-border)]">
                {isImage && (
                  <img src={previewUrl} alt={filename} className="max-w-xs max-h-64 object-contain bg-[var(--acm-base)] block" />
                )}
                <div className="flex items-center gap-2 px-3 py-2 bg-[var(--acm-card)] text-[11px]">
                  <Paperclip size={11} className="text-[var(--acm-fg-4)] flex-shrink-0" />
                  <span className="mono truncate text-[var(--acm-fg-3)] flex-1">{filename}</span>
                  <a href={downloadUrl} download={filename} className="btn-primary !py-[4px] !px-[8px] !text-[11px] flex-shrink-0">
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

export interface MessageBubbleProps {
  content: string;
  role: 'user' | 'assistant' | 'error' | 'system';
  badge?: string;
  token?: string | null;
  toolCall?: {
    tool: string;
    arguments: string;
    result?: string;
    status: 'running' | 'completed' | 'error';
  };
}

export function MessageBubble({ content, role, badge, token, toolCall }: MessageBubbleProps) {
  const [expanded, setExpanded] = useState(false);
  const isUser = role === 'user';
  const isError = role === 'error';
  const isSystem = role === 'system';

  if (isSystem && toolCall) {
    const isRunning = toolCall.status === 'running';
    const isDone    = toolCall.status === 'completed';
    const accentColor = isRunning ? 'var(--acm-accent)' : isDone ? 'var(--acm-ok)' : 'var(--acm-err)';
    const stateLabel  = isRunning ? 'CALL' : isDone ? 'DONE' : 'ERR';
    return (
      <div className="acm-card overflow-hidden max-w-[85%]" style={{ borderLeft: `2px solid ${accentColor}` }}>
        <button
          onClick={() => setExpanded(!expanded)}
          className="w-full flex items-center gap-[10px] px-[12px] py-[8px] hover:bg-[var(--acm-elev)] transition-colors"
          style={{ borderBottom: expanded ? '1px solid var(--acm-border)' : undefined }}
        >
          {isRunning && <span className="dot dot-accent acm-pulse" />}
          {isDone    && <span className="dot dot-ok" />}
          {!isRunning && !isDone && <span className="dot dot-err" />}
          <Wrench size={12} style={{ color: accentColor }} />
          <span className="mono text-[10px] font-semibold uppercase tracking-wider flex-shrink-0" style={{ color: accentColor }}>{stateLabel}</span>
          <span className="mono text-[12px] text-[var(--acm-fg-2)] font-medium flex-1 text-left truncate">{toolCall.tool}</span>
          {toolCall.arguments && !expanded && (
            <span className="mono text-[11px] text-[var(--acm-fg-4)] truncate max-w-[180px]">{toolCall.arguments}</span>
          )}
          {expanded ? <ChevronUp size={12} className="text-[var(--acm-fg-4)] flex-shrink-0" /> : <ChevronDown size={12} className="text-[var(--acm-fg-4)] flex-shrink-0" />}
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

  if (isError) {
    return (
      <div className="flex items-start gap-2 border-l-2 border-l-[var(--acm-err)] pl-3 py-1">
        <span className="dot dot-err mt-1 flex-shrink-0" />
        <p className="text-[12px] text-[var(--acm-fg-3)]">{content}</p>
      </div>
    );
  }

  if (isSystem) {
    return (
      <div className="border-l-2 border-l-[var(--acm-border-strong)] pl-3 py-1 text-[12px] text-[var(--acm-fg-3)]">
        {badge && <span className="mono text-[10px] text-[var(--acm-fg-4)] block mb-0.5">{badge}</span>}
        <MessageContent content={content} token={token} />
      </div>
    );
  }

  return (
    <div className={cn('flex gap-3', isUser ? 'flex-row-reverse' : '')}>
      {!isUser && (
        <div className="w-7 h-7 border border-[var(--acm-border)] bg-[var(--acm-card)] rounded-[6px] flex items-center justify-center flex-shrink-0 text-[var(--acm-accent)] self-start mt-1">
          <Bot size={14} />
        </div>
      )}
      <div className={cn('flex flex-col max-w-[75%]', isUser ? 'items-end' : 'items-start')}>
        {badge && <span className="mono text-[10px] text-[var(--acm-fg-4)] mb-1">{badge}</span>}
        {isUser ? (
          <div className="bg-[var(--acm-card)] border border-[var(--acm-border)] rounded-[8px] px-[14px] py-[12px] text-[var(--acm-fg)]">
            <MessageContent content={content} token={token} />
          </div>
        ) : (
          <div className="bg-[oklch(0.84_0.16_82/0.04)] border-l-2 border-l-[var(--acm-accent)] rounded-[0_8px_8px_0] px-[14px] py-[12px] text-[var(--acm-fg-2)]">
            <MessageContent content={content} token={token} />
          </div>
        )}
      </div>
    </div>
  );
}
