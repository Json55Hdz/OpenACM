'use client';

import { useEffect, useRef, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { Loader2, Send } from 'lucide-react';
import { useAgentMutations } from '@/hooks/use-agents';
import { useConversationHistory } from '@/hooks/use-api';
import type { AgentFlow } from '@/hooks/use-agent-flows';

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
  const { data: history } = useConversationHistory(channelId, 'dashboard_test');
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [hydrated, setHydrated] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (hydrated || !history) return;
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
  }, [history, hydrated]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ block: 'end' });
  }, [messages]);

  const send = async () => {
    const msg = input.trim();
    if (!msg) return;
    setInput('');
    setMessages(m => [...m, { role: 'user', text: msg }]);
    const extraSystemContext =
      `Estás editando el flujo "${flow.name}" (id=${flow.id}) del agente ${agentId}. Si el usuario te pide ` +
      `crear o modificar este flujo, llama a create_or_update_agent_flow con flow_id=${flow.id} y ` +
      `agent_id=${agentId} para EDITARLO directamente — no crees un flujo nuevo salvo que el usuario lo pida explícitamente.`;
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
      className="flex flex-col gap-2 p-3 rounded shrink-0"
      style={{ background: 'var(--acm-elev)', border: '1px solid var(--acm-border)', width: 320 }}
    >
      <div className="text-[11px] font-medium uppercase tracking-[0.08em]" style={{ color: 'var(--acm-fg-4)' }}>
        Chat con IA — construir este flujo
      </div>
      {messages.length > 0 && (
        <div className="space-y-2 max-h-64 overflow-y-auto acm-scroll">
          {messages.map((m, i) => (
            <div
              key={i}
              className="text-[12px] px-3 py-2 rounded-lg max-w-[90%]"
              style={
                m.role === 'user'
                  ? { background: 'var(--acm-accent-tint)', borderLeft: '2px solid var(--acm-accent)', color: 'var(--acm-fg-2)', marginLeft: 'auto' }
                  : { background: 'var(--acm-base)', color: 'var(--acm-fg-3)' }
              }
            >
              {m.text}
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
