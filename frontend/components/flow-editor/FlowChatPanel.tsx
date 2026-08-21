'use client';

import { useEffect, useRef, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Loader2, Send } from 'lucide-react';
import { useAgentMutations } from '@/hooks/use-agents';
import { useConversationHistory } from '@/hooks/use-api';
import type { AgentFlow } from '@/hooks/use-agent-flows';

// Lightweight markdown rendering for this panel's short bot replies — reuses
// the same react-markdown/remark-gfm libraries the main /chat page uses, but
// with a smaller set of element overrides (no media-link parsing, no
// attachments) since replies here are brief build confirmations, not rich
// chat messages.
const MARKDOWN_COMPONENTS = {
  p: ({ children }: { children?: React.ReactNode }) => <p className="mb-1.5 last:mb-0 leading-relaxed break-words" style={{ overflowWrap: 'anywhere' }}>{children}</p>,
  strong: ({ children }: { children?: React.ReactNode }) => <strong className="font-semibold" style={{ color: 'var(--acm-fg)' }}>{children}</strong>,
  em: ({ children }: { children?: React.ReactNode }) => <em className="italic">{children}</em>,
  ul: ({ children }: { children?: React.ReactNode }) => <ul className="list-disc list-inside space-y-0.5 my-1.5 pl-1">{children}</ul>,
  ol: ({ children }: { children?: React.ReactNode }) => <ol className="list-decimal list-inside space-y-0.5 my-1.5 pl-1">{children}</ol>,
  li: ({ children }: { children?: React.ReactNode }) => <li>{children}</li>,
  // break-words/overflow-wrap so an unbroken token (a long URL, a query
  // string) wraps inside the bubble instead of forcing the 320px panel
  // wider than its fixed width.
  code: ({ children }: { children?: React.ReactNode }) => (
    <code
      className="rounded-[4px] px-1 py-0.5 text-[11px] mono break-words"
      style={{ background: 'var(--acm-elev)', color: 'var(--acm-accent)', overflowWrap: 'anywhere' }}
    >{children}</code>
  ),
  // A fenced code block's own <pre> defaults to white-space: pre (no wrap)
  // — scope containment to this element alone (its inner <code> already
  // wraps via the override above) rather than fighting pre's own layout.
  pre: ({ children }: { children?: React.ReactNode }) => (
    <pre className="max-w-full overflow-x-auto my-1.5 acm-scroll">{children}</pre>
  ),
  a: ({ href, children }: { href?: string; children?: React.ReactNode }) => (
    <a
      href={href} target="_blank" rel="noopener noreferrer"
      className="underline underline-offset-2 break-words"
      style={{ color: 'var(--acm-accent)', overflowWrap: 'anywhere' }}
    >{children}</a>
  ),
  // GFM tables don't wrap by nature (columns), so contain overflow with a
  // dedicated horizontal scroller instead of letting the table's intrinsic
  // width push the whole panel wider.
  table: ({ children }: { children?: React.ReactNode }) => (
    <div className="max-w-full overflow-x-auto my-1.5 rounded acm-scroll" style={{ border: '1px solid var(--acm-border)' }}>
      <table className="text-[11px]" style={{ borderCollapse: 'collapse', width: '100%' }}>{children}</table>
    </div>
  ),
  th: ({ children }: { children?: React.ReactNode }) => (
    <th className="text-left px-2 py-1 font-medium whitespace-nowrap" style={{ borderBottom: '1px solid var(--acm-border)', color: 'var(--acm-fg-2)' }}>{children}</th>
  ),
  td: ({ children }: { children?: React.ReactNode }) => (
    <td className="px-2 py-1 align-top" style={{ borderBottom: '1px solid var(--acm-border)', color: 'var(--acm-fg-3)' }}>{children}</td>
  ),
};

interface HistoryItem {
  role: string;
  // Nullable on purpose: a persisted tool-call-only assistant turn carries no
  // user-facing text, and older rows can come back with a null content.
  content: string | null;
  timestamp: string;
}

interface ChatMessage {
  role: 'user' | 'assistant';
  text: string;
}

export function FlowChatPanel({ agentId, flow }: { agentId: number; flow: AgentFlow }) {
  const { test } = useAgentMutations();
  const qc = useQueryClient();
  const channelId = `agent_${agentId}_flow_${flow.id}`;
  const { data: history, isFetching: historyFetching } = useConversationHistory(channelId, 'dashboard_test');
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [hydrated, setHydrated] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (hydrated || historyFetching || !history) return;
    setMessages(
      (history as HistoryItem[])
        // Mirrors memory.py's _load_from_db filter: an assistant turn that
        // only planned a tool call is persisted with content="" (see
        // brain_loop.py), and rendering it would put one blank padded bubble
        // per tool-call turn into the reopened conversation.
        .filter(h => (h.role === 'user' || h.role === 'assistant') && h.content?.trim())
        .map(h => ({ role: h.role as 'user' | 'assistant', text: h.content as string }))
    );
    setHydrated(true);
  }, [history, historyFetching, hydrated]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ block: 'end' });
  }, [messages]);

  const send = async () => {
    const msg = input.trim();
    if (!msg) return;
    setInput('');
    setMessages(m => [...m, { role: 'user', text: msg }]);
    // Includes the flow's CURRENT graph_json (re-read from the `flow` prop at
    // send time, not cached from when the panel opened) so the model always
    // sees the real current structure — not just its own memory of what it
    // built in earlier turns of this conversation, which goes stale the
    // moment the flow was built or edited any other way (by hand on the
    // canvas, by a different chat session, etc.).
    const extraSystemContext =
      `Estás editando el flujo "${flow.name}" (id=${flow.id}) del agente ${agentId}. Si el usuario te pide ` +
      `crear o modificar este flujo, llama a create_or_update_agent_flow con flow_id=${flow.id} y ` +
      `agent_id=${agentId} para EDITARLO directamente — no crees un flujo nuevo salvo que el usuario lo pida explícitamente.\n\n` +
      `Grafo actual de este flujo (úsalo como base real — no asumas que es lo que tú recuerdas haber construido antes):\n` +
      `${flow.graph_json || '{"nodes":[],"edges":[]}'}`;
    try {
      const res = await test.mutateAsync({
        id: agentId, message: msg, channel_id: channelId, extra_system_context: extraSystemContext,
      });
      setMessages(m => [...m, { role: 'assistant', text: res.response }]);
      qc.invalidateQueries({ queryKey: ['agent-flow', flow.id] });
      qc.invalidateQueries({ queryKey: ['agent-flows', agentId] });
    } catch (e) {
      // fetchAPI already unwraps the backend's error detail into the Error's
      // message, so surface it instead of a generic string.
      const detail = e instanceof Error ? e.message : 'Error al obtener respuesta.';
      setMessages(m => [...m, { role: 'assistant', text: `⚠️ ${detail}` }]);
    }
  };

  return (
    <div
      className="flex flex-col gap-2 p-3 rounded shrink-0 overflow-hidden"
      style={{ background: 'var(--acm-elev)', border: '1px solid var(--acm-border)', width: 320 }}
    >
      <div className="text-[11px] font-medium uppercase tracking-[0.08em]" style={{ color: 'var(--acm-fg-4)' }}>
        Chat con IA — construir este flujo
      </div>
      {messages.length > 0 && (
        <div className="space-y-2 max-h-64 overflow-y-auto overflow-x-hidden acm-scroll">
          {messages.map((m, i) => (
            <div
              key={i}
              className="text-[12px] px-3 py-2 rounded-lg max-w-[90%] min-w-0"
              style={
                m.role === 'user'
                  ? { background: 'var(--acm-accent-tint)', borderLeft: '2px solid var(--acm-accent)', color: 'var(--acm-fg-2)', marginLeft: 'auto' }
                  : { background: 'var(--acm-base)', color: 'var(--acm-fg-3)' }
              }
            >
              <ReactMarkdown remarkPlugins={[remarkGfm]} components={MARKDOWN_COMPONENTS}>{m.text}</ReactMarkdown>
            </div>
          ))}
          {test.isPending && (
            <div className="flex items-center gap-1.5 text-[11px]" style={{ color: 'var(--acm-fg-4)' }}>
              <Loader2 size={11} className="animate-spin" /> Pensando...
            </div>
          )}
          <div ref={messagesEndRef} />
        </div>
      )}
      <div className="flex gap-2">
        <input
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && !e.shiftKey && send()}
          placeholder="Describe el flujo que quieres..."
          disabled={test.isPending}
          className="acm-input flex-1 text-[13px] disabled:opacity-50"
        />
        <button onClick={send} disabled={test.isPending || !input.trim()} className="btn-primary px-2.5 py-2 disabled:opacity-50">
          <Send size={13} />
        </button>
      </div>
    </div>
  );
}
