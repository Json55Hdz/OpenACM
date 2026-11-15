'use client';

import React, { useState, useRef, useEffect } from 'react';
import { Play, Pause, CheckCircle2, AlertCircle, Loader2, FileText, MessageSquare, ChevronDown, ChevronUp, Send, User, Radio, ArrowRight, Sparkles, XCircle, Activity, HelpCircle } from 'lucide-react';
import { useAuthStore } from '@/stores/auth-store';
import { useQuery } from '@tanstack/react-query';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Bug } from 'lucide-react';
import { MessageBubble } from '@/components/chat/message-bubble';
import { Swarm, Worker, Task, SwarmMessage, LiveEvent } from './shared';

export function SwarmMarkdown({ content, textColor }: { content: string; textColor: string }) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      components={{
        p: ({ children }) => <p className={`mb-1.5 last:mb-0 leading-relaxed text-[13px] ${textColor}`}>{children}</p>,
        h1: ({ children }) => <h1 className="text-[14px] font-bold text-[var(--acm-fg)] mt-3 mb-1 first:mt-0">{children}</h1>,
        h2: ({ children }) => <h2 className="text-[13px] font-semibold text-[var(--acm-fg)] mt-2 mb-1 first:mt-0">{children}</h2>,
        h3: ({ children }) => <h3 className="text-[13px] font-semibold text-[var(--acm-fg-2)] mt-1.5 mb-0.5 first:mt-0">{children}</h3>,
        strong: ({ children }) => <strong className="font-semibold text-[var(--acm-fg)]">{children}</strong>,
        em: ({ children }) => <em className="italic text-[var(--acm-fg-2)]">{children}</em>,
        ul: ({ children }) => <ul className="list-disc list-inside space-y-0.5 my-1.5 pl-2 text-[13px]">{children}</ul>,
        ol: ({ children }) => <ol className="list-decimal list-inside space-y-0.5 my-1.5 pl-2 text-[13px]">{children}</ol>,
        li: ({ children }) => <li className={`text-[13px] ${textColor}`}>{children}</li>,
        code: ({ children, className }) => {
          const isBlock = className?.includes('language-');
          return isBlock
            ? <code className="block bg-[var(--acm-elev)] text-[var(--acm-ok)] border border-[var(--acm-border)] rounded-lg px-3 py-2 my-1.5 text-[11px] mono overflow-x-auto whitespace-pre">{children}</code>
            : <code className="bg-[var(--acm-elev)] text-[var(--acm-accent)] border border-[var(--acm-border)] rounded px-1 py-0.5 text-[11px] mono">{children}</code>;
        },
        pre: ({ children }) => <>{children}</>,
        blockquote: ({ children }) => <blockquote className="border-l-2 border-l-[var(--acm-border-strong)] pl-2 my-1.5 text-[var(--acm-fg-3)] italic text-[13px]">{children}</blockquote>,
        hr: () => <hr className="border-[var(--acm-border)] my-2" />,
      }}
    >
      {content}
    </ReactMarkdown>
  );
}

// ─── Live Event Row ───────────────────────────────────────────────────────────

export function LiveEventRow({ event }: { event: LiveEvent }) {
  const { type, task_title, worker_name, tools_called, iteration, content, pct_used: pct } = event;
  const [expanded, setExpanded] = useState(false);

  const cfg: Record<string, { icon: React.ReactNode; color: string; label: string }> = {
    'swarm:task_started':    { icon: <Play size={10} />,         color: 'text-[var(--acm-accent)]', label: 'started' },
    'swarm:task_completed':  { icon: <CheckCircle2 size={10} />, color: 'text-[var(--acm-ok)]',     label: 'done' },
    'swarm:task_failed':     { icon: <AlertCircle size={10} />,  color: 'text-[var(--acm-err)]',    label: 'failed' },
    'swarm:started':         { icon: <Play size={10} />,         color: 'text-[var(--acm-ok)]',     label: 'swarm started' },
    'swarm:paused':          { icon: <Pause size={10} />,        color: 'text-[var(--acm-warn)]',   label: 'swarm paused' },
    'swarm:completed':       { icon: <CheckCircle2 size={10} />, color: 'text-[var(--acm-ok)]',     label: 'swarm completed' },
    'swarm:failed':          { icon: <AlertCircle size={10} />,  color: 'text-[var(--acm-err)]',    label: 'swarm failed' },
    'swarm:contract_ready':  { icon: <FileText size={10} />,     color: 'text-[var(--acm-fg-3)]',   label: 'contract ready' },
    'swarm:worker_progress': { icon: <Loader2 size={10} className="animate-spin" />, color: 'text-[var(--acm-accent)]', label: 'working' },
    'swarm:worker_thought':  { icon: <MessageSquare size={10} />, color: 'text-[var(--acm-fg-2)]',  label: 'thinking' },
  };

  const c = cfg[type] ?? { icon: <Radio size={10} />, color: 'text-[var(--acm-fg-4)]', label: type };
  const pctColor = pct == null ? '' : pct >= 90 ? 'text-[var(--acm-err)]' : pct >= 75 ? 'text-[var(--acm-warn)]' : 'text-[var(--acm-fg-4)]';

  // worker_thought: show collapsible text block
  if (type === 'swarm:worker_thought' && content) {
    const preview = content.length > 120 ? content.slice(0, 120) + '…' : content;
    return (
      <div className="py-0.5">
        <div className="flex items-center gap-2 text-[11px] cursor-pointer" onClick={() => setExpanded(v => !v)}>
          <span className={c.color}>{c.icon}</span>
          {worker_name && <span className="mono text-[var(--acm-fg-2)] font-medium">{worker_name}</span>}
          <span className="text-[var(--acm-fg-4)]">{c.label}</span>
          {iteration !== undefined && <span className="mono text-[var(--acm-fg-4)]">#{iteration}</span>}
          <span className="text-[var(--acm-fg-3)] truncate flex-1">{preview}</span>
          {expanded ? <ChevronUp size={10} className="shrink-0 text-[var(--acm-fg-4)]" /> : <ChevronDown size={10} className="shrink-0 text-[var(--acm-fg-4)]" />}
        </div>
        {expanded && (
          <pre className="mt-1 ml-4 text-[11px] text-[var(--acm-fg-3)] bg-[var(--acm-elev)] border border-[var(--acm-border)] rounded-lg p-2 whitespace-pre-wrap max-h-64 overflow-y-auto mono">
            {content}
          </pre>
        )}
      </div>
    );
  }

  return (
    <div className="flex items-center gap-2 text-[11px] py-0.5">
      <span className={c.color}>{c.icon}</span>
      {worker_name && <span className="mono text-[var(--acm-fg-2)] font-medium truncate max-w-[120px]">{worker_name}</span>}
      <span className={`${c.color} shrink-0`}>{c.label}</span>
      {task_title && <span className="text-[var(--acm-fg-3)] truncate flex-1">{task_title}</span>}
      {tools_called && tools_called.length > 0 && (
        <span className="text-[var(--acm-fg-4)] mono truncate flex-1">
          {tools_called.slice(0, 3).join(', ')}{tools_called.length > 3 ? ` +${tools_called.length - 3}` : ''}
        </span>
      )}
      {iteration !== undefined && (
        <span className="text-[var(--acm-fg-4)] mono shrink-0">#{iteration}</span>
      )}
      {pct != null && (
        <span className={`mono shrink-0 ${pctColor}`}>{pct}% ctx</span>
      )}
    </div>
  );
}

// ─── Activity Feed Entry ──────────────────────────────────────────────────────

export function ActivityEntry({ msg, onReply }: { msg: SwarmMessage; onReply?: (prefix: string) => void }) {
  const [expanded, setExpanded] = useState(false);
  const type = msg.message_type;

  const cfg: Record<string, {
    containerClass: string;
    icon: React.ReactNode;
    label: () => React.ReactNode;
    textColor: string;
    collapsible?: boolean;
  }> = {
    user: {
      containerClass: 'border-l-2 border-l-[var(--acm-accent)] border-[var(--acm-border)] bg-[oklch(0.84_0.16_82/0.04)]',
      textColor: 'text-[var(--acm-fg-2)]',
      icon: <User size={12} className="text-[var(--acm-accent)]" />,
      label: () => <span className="font-semibold text-[var(--acm-accent)]">You</span>,
    },
    question: {
      containerClass: 'border-l-2 border-l-[var(--acm-warn)] border-[var(--acm-border)]',
      textColor: 'text-[var(--acm-fg-2)]',
      icon: <HelpCircle size={12} className="text-[var(--acm-warn)]" />,
      label: () => <span className="font-semibold text-[var(--acm-warn)]">{msg.from_worker_name || 'Worker'} asks</span>,
    },
    task_result: {
      containerClass: 'border-[var(--acm-border)] bg-[var(--acm-card)]',
      textColor: 'text-[var(--acm-fg-2)]',
      icon: <CheckCircle2 size={12} className="text-[var(--acm-ok)]" />,
      label: () => <span className="font-semibold text-[var(--acm-ok)]">{msg.from_worker_name || 'Worker'}</span>,
      collapsible: true,
    },
    task_failed: {
      containerClass: 'border-l-2 border-l-[var(--acm-err)] border-[var(--acm-border)]',
      textColor: 'text-[var(--acm-fg-2)]',
      icon: <XCircle size={12} className="text-[var(--acm-err)]" />,
      label: () => <span className="font-semibold text-[var(--acm-err)]">{msg.from_worker_name || 'Worker'}</span>,
    },
    task_waiting: {
      containerClass: 'border-l-2 border-l-[var(--acm-warn)] border-[var(--acm-border)]',
      textColor: 'text-[var(--acm-fg-2)]',
      icon: <HelpCircle size={12} className="text-[var(--acm-warn)]" />,
      label: () => <span className="font-semibold text-[var(--acm-warn)]">{msg.from_worker_name || 'Worker'} — waiting</span>,
    },
    bug_report: {
      containerClass: 'border-l-2 border-l-[var(--acm-err)] border-[var(--acm-border)]',
      textColor: 'text-[var(--acm-fg-2)]',
      icon: <Bug size={12} className="text-[var(--acm-err)]" />,
      label: () => <span className="font-semibold text-[var(--acm-err)]">{msg.from_worker_name || 'QA'} — bug found</span>,
    },
    synthesis: {
      containerClass: 'border-l-2 border-l-[var(--acm-accent)] border-[var(--acm-border)] bg-[oklch(0.84_0.16_82/0.03)]',
      textColor: 'text-[var(--acm-fg-2)]',
      icon: <Sparkles size={12} className="text-[var(--acm-accent)]" />,
      label: () => <span className="font-semibold text-[var(--acm-accent)]">Final Summary</span>,
      collapsible: true,
    },
    broadcast: {
      containerClass: 'border-[var(--acm-border)] bg-[var(--acm-card)]',
      textColor: 'text-[var(--acm-fg-2)]',
      icon: <Radio size={12} className="text-[var(--acm-fg-3)]" />,
      label: () => <span className="font-semibold text-[var(--acm-fg-2)]">{msg.from_worker_name || 'Worker'}</span>,
    },
    message: {
      containerClass: 'border-[var(--acm-border)] bg-[var(--acm-card)]',
      textColor: 'text-[var(--acm-fg-2)]',
      icon: <ArrowRight size={12} className="text-[var(--acm-fg-4)]" />,
      label: () => (
        <>
          <span className="font-semibold text-[var(--acm-fg-2)]">{msg.from_worker_name || '?'}</span>
          <ArrowRight size={10} className="text-[var(--acm-fg-4)] mx-0.5" />
          <span className="font-semibold text-[var(--acm-fg-2)]">{msg.to_worker_name || '?'}</span>
        </>
      ),
    },
  };

  const c = cfg[type] ?? cfg['message'];
  const isCollapsible = c.collapsible && msg.content.length > 400;
  const displayContent = isCollapsible && !expanded ? msg.content.slice(0, 400) + '…' : msg.content;

  // Bug reports are stored as JSON — render as a structured card
  if (type === 'bug_report') {
    let bug: { title?: string; description?: string; severity?: string; fixer?: string; cycle?: number; fix_task?: string; retest_task?: string } = {};
    try { bug = JSON.parse(msg.content); } catch { bug = { title: msg.content }; }
    const sevClass: Record<string, string> = {
      critical: 'bg-[var(--acm-err)] text-[var(--acm-base)]',
      high:     'bg-[var(--acm-warn)] text-[var(--acm-base)]',
      medium:   'bg-[var(--acm-accent)] text-[oklch(0.18_0.015_80)]',
      low:      'bg-[var(--acm-fg-4)] text-[var(--acm-base)]',
    };
    const sev = (bug.severity || 'medium').toLowerCase();
    return (
      <div className="border-l-2 border-l-[var(--acm-err)] border-[var(--acm-border)] rounded-lg p-3">
        <div className="flex items-center gap-1.5 mb-2 text-[11px] text-[var(--acm-fg-4)]">
          <Bug size={12} className="text-[var(--acm-err)]" />
          <span className="font-semibold text-[var(--acm-err)]">{msg.from_worker_name || 'QA'} — bug found</span>
          <span className={`ml-1 px-1.5 py-0.5 rounded mono text-[10px] font-bold ${sevClass[sev] || sevClass.medium}`}>
            {sev.toUpperCase()}
          </span>
          {bug.cycle && bug.cycle > 1 && <span className="text-[var(--acm-fg-4)]">cycle {bug.cycle}</span>}
          <span className="ml-auto mono text-[var(--acm-fg-4)]">{new Date(msg.created_at).toLocaleTimeString()}</span>
        </div>
        <p className="text-[13px] font-semibold text-[var(--acm-fg)] mb-1">{bug.title}</p>
        {bug.description && (
          <p className="text-[11px] text-[var(--acm-fg-3)] mb-2 whitespace-pre-wrap">{bug.description}</p>
        )}
        <div className="flex gap-3 text-[11px] text-[var(--acm-fg-4)]">
          {bug.fixer && <span>Fix → <span className="text-[var(--acm-fg-2)]">{bug.fixer}</span></span>}
          {bug.retest_task && <span>Re-test scheduled</span>}
        </div>
      </div>
    );
  }

  return (
    <div className={`border rounded-lg p-3 ${c.containerClass}`}>
      <div className="flex items-center gap-1.5 mb-1.5 text-[11px] text-[var(--acm-fg-4)]">
        {c.icon}
        {c.label()}
        <span className="ml-auto mono text-[var(--acm-fg-4)]">{new Date(msg.created_at).toLocaleTimeString()}</span>
      </div>
      <SwarmMarkdown content={displayContent} textColor={c.textColor} />
      <div className="flex items-center gap-2 mt-1.5">
        {isCollapsible && (
          <button
            onClick={() => setExpanded(x => !x)}
            className="text-[11px] text-[var(--acm-fg-4)] hover:text-[var(--acm-fg-3)] transition-colors"
          >
            {expanded ? '↑ collapse' : '↓ show full output'}
          </button>
        )}
        {(type === 'question' || type === 'task_waiting') && onReply && (
          <button
            onClick={() => onReply(`@${msg.from_worker_name || 'Worker'}: `)}
            className="ml-auto flex items-center gap-1 px-2 py-0.5 rounded text-[11px] border border-[var(--acm-warn)] text-[var(--acm-warn)] hover:bg-[oklch(0.84_0.16_82/0.08)] transition-colors"
          >
            <Send size={10} /> Reply
          </button>
        )}
      </div>
    </div>
  );
}

// ─── Swarm Chats Tab ──────────────────────────────────────────────────────────

interface ChannelStat { channel_id: string; user_id: string; message_count: number; last_updated: string; last_message: string; }
interface ChannelMessage { role: string; content: string; timestamp: string; }

export function sanitizeSwarmMessage(content: string): { text: string; truncated: boolean } {
  // Strip binary/non-printable chars (PDF bytes, etc.)
  const clean = content.replace(/[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]/g, '')
    // Collapse runs of replacement chars and whitespace left by binary removal
    .replace(/�{3,}/g, '[binary data]')
    .replace(/\n{4,}/g, '\n\n\n')
    .trim();

  // Task context messages are huge (workspace + context + PDF). Show a compact preview.
  const MAX = 800;
  if (clean.length > MAX) {
    return { text: clean.slice(0, MAX) + `\n\n… [${clean.length.toLocaleString()} chars total]`, truncated: true };
  }
  return { text: clean, truncated: false };
}

export function SwarmChatsTab({ swarmId, selectedChannel, onSelect, fetchAPI }: {
  swarmId: number;
  selectedChannel: { channel_id: string; user_id: string } | null;
  onSelect: (ch: { channel_id: string; user_id: string } | null) => void;
  fetchAPI: (url: string, opts?: RequestInit) => Promise<any>;
}) {
  const { data: channels = [] } = useQuery<ChannelStat[]>({
    queryKey: ['swarm-chats', swarmId],
    queryFn: () => fetchAPI(`/api/swarms/${swarmId}/conversations`),
    refetchInterval: 5000,
  });

  const { data: messages = [] } = useQuery<ChannelMessage[]>({
    queryKey: ['swarm-chat-msgs', swarmId, selectedChannel?.channel_id],
    queryFn: () => selectedChannel
      ? fetchAPI(`/api/swarms/${swarmId}/conversations/${encodeURIComponent(selectedChannel.channel_id)}/${encodeURIComponent(selectedChannel.user_id)}`)
      : Promise.resolve([]),
    enabled: !!selectedChannel,
    refetchInterval: selectedChannel ? 3000 : false,
  });

  const token = useAuthStore(s => s.token);
  const msgsEndRef = useRef<HTMLDivElement>(null);
  useEffect(() => { msgsEndRef.current?.scrollIntoView({ behavior: 'smooth' }); }, [messages]);

  if (channels.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-12 text-[var(--acm-fg-4)]">
        <MessageSquare size={28} className="mb-3" />
        <p className="text-[13px]">No worker conversations yet.</p>
      </div>
    );
  }

  const workerLabel = (ch: ChannelStat) => {
    const parts = ch.channel_id.split('__');
    return parts.length >= 2 ? parts[1].replace(/_/g, ' ') : ch.channel_id;
  };

  return (
    <div className="flex gap-3 h-[520px]">
      {/* Channel list */}
      <div className="w-48 shrink-0 flex flex-col gap-1 overflow-y-auto">
        {channels.map(ch => (
          <button
            key={ch.channel_id}
            onClick={() => onSelect(selectedChannel?.channel_id === ch.channel_id ? null : { channel_id: ch.channel_id, user_id: ch.user_id })}
            className={`text-left p-2.5 rounded-[6px] border transition-colors ${
              selectedChannel?.channel_id === ch.channel_id
                ? 'bg-[var(--acm-accent)] border-[var(--acm-accent)] text-[oklch(0.18_0.015_80)]'
                : 'bg-[var(--acm-card)] border-[var(--acm-border)] text-[var(--acm-fg-2)] hover:border-[var(--acm-accent)]'
            }`}
          >
            <div className="text-[11px] font-medium capitalize truncate">{workerLabel(ch)}</div>
            <div className="text-[10px] opacity-60 mt-0.5 truncate">{ch.message_count} msgs</div>
            {ch.last_message && (
              <div className="text-[10px] opacity-50 mt-0.5 truncate">
                {sanitizeSwarmMessage(ch.last_message).text.slice(0, 40)}
              </div>
            )}
          </button>
        ))}
      </div>

      {/* Messages panel */}
      <div className="flex-1 acm-card overflow-y-auto px-4 py-4 flex flex-col gap-4">
        {!selectedChannel ? (
          <div className="flex items-center justify-center h-full text-[var(--acm-fg-4)] text-[12px]">Select a worker to view its conversation</div>
        ) : messages.length === 0 ? (
          <div className="flex items-center justify-center h-full text-[var(--acm-fg-4)] text-[12px]">No messages yet</div>
        ) : (
          messages
            .filter(m => m.role === 'user' || m.role === 'assistant')
            .map((m, i) => {
              const { text } = sanitizeSwarmMessage(m.content);
              return (
                <MessageBubble
                  key={i}
                  content={text}
                  role={m.role as 'user' | 'assistant'}
                  token={token}
                />
              );
            })
        )}
        <div ref={msgsEndRef} />
      </div>
    </div>
  );
}

// ─── Swarm Detail ─────────────────────────────────────────────────────────────
