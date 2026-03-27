'use client';

import { useEffect, useRef, useState } from 'react';
import { authStore } from '@/stores/auth-store';
import {
  MessageSquare,
  Bot,
  Wrench,
  Cpu,
  Search,
  Zap,
} from 'lucide-react';

interface EventItem {
  id: string;
  time: string;
  text: string;
  type: string;
}

const MAX_EVENTS = 100;

function formatTime(date: Date): string {
  return date.toLocaleTimeString('en-US', { hour12: false });
}

function eventIcon(type: string) {
  switch (type) {
    case 'message.received':
      return <MessageSquare size={14} className="text-blue-400" />;
    case 'message.sent':
      return <Bot size={14} className="text-green-400" />;
    case 'tool.called':
      return <Wrench size={14} className="text-amber-400" />;
    case 'tool.result':
      return <Wrench size={14} className="text-emerald-400" />;
    case 'llm.request':
      return <Cpu size={14} className="text-purple-400" />;
    case 'llm.response':
      return <Cpu size={14} className="text-purple-300" />;
    case 'message.thinking':
      return <Search size={14} className="text-cyan-400" />;
    default:
      return <Zap size={14} className="text-slate-400" />;
  }
}

function describeEvent(type: string, data: Record<string, unknown>): string {
  switch (type) {
    case 'message.received':
      return `Message from ${data.channel_type || 'unknown'}: "${String(data.content || '').slice(0, 80)}${String(data.content || '').length > 80 ? '...' : ''}"`;
    case 'message.sent':
      return `Reply to ${data.channel_type || 'unknown'} (${data.tokens || 0} tokens)`;
    case 'message.thinking': {
      const status = data.status as string;
      if (status === 'tool_execution') return `Executing tool: ${data.tool}`;
      if (status === 'processing') return `Processing (step ${data.iteration || '?'})`;
      return `Thinking...`;
    }
    case 'tool.called':
      return `Tool called: ${data.tool} ${data.arguments ? `(${String(data.arguments).slice(0, 60)})` : ''}`;
    case 'tool.result':
      return `Tool result: ${data.tool} → ${String(data.result || '').slice(0, 80)}${String(data.result || '').length > 80 ? '...' : ''}`;
    case 'llm.request':
      return `LLM request → ${data.model || 'unknown'}`;
    case 'llm.response':
      return `LLM response (${data.tokens || '?'} tokens, ${data.elapsed ? `${Number(data.elapsed).toFixed(1)}s` : '?'})`;
    default:
      return `${type}`;
  }
}

export function EventLog() {
  const [events, setEvents] = useState<EventItem[]>([]);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function connect() {
      const token = authStore.getState().token;
      if (!token) return;

      if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) return;

      if (wsRef.current) {
        wsRef.current.onclose = null;
        wsRef.current.close();
        wsRef.current = null;
      }

      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      const ws = new WebSocket(`${protocol}//${window.location.host}/ws/events?token=${token}`);
      wsRef.current = ws;

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          const type = data.type as string;
          if (!type) return;

          const item: EventItem = {
            id: `${Date.now()}-${Math.random().toString(36).substr(2, 6)}`,
            time: formatTime(new Date()),
            text: describeEvent(type, data),
            type,
          };

          setEvents((prev) => {
            const next = [...prev, item];
            return next.length > MAX_EVENTS ? next.slice(-MAX_EVENTS) : next;
          });
        } catch {
          // ignore malformed messages
        }
      };

      ws.onclose = () => {
        wsRef.current = null;
        if (reconnectRef.current) clearTimeout(reconnectRef.current);
        if (authStore.getState().token) {
          reconnectRef.current = setTimeout(connect, 3000);
        }
      };

      // Keep alive
      const keepAlive = setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) ws.send('ping');
      }, 30000);

      ws.addEventListener('close', () => clearInterval(keepAlive));
    }

    connect();

    const unsubscribe = authStore.subscribe((state) => {
      if (state.token) connect();
    });

    return () => {
      unsubscribe();
      if (reconnectRef.current) clearTimeout(reconnectRef.current);
      if (wsRef.current) {
        wsRef.current.onclose = null;
        wsRef.current.close();
      }
    };
  }, []);

  // Auto-scroll to bottom
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [events]);

  return (
    <div className="h-64 overflow-y-auto space-y-1 pr-2 scrollbar-thin">
      {events.length === 0 ? (
        <div className="flex items-center justify-center h-full text-slate-500 text-sm">
          Waiting for events...
        </div>
      ) : (
        events.map((event) => (
          <div
            key={event.id}
            className="flex items-start gap-2 px-3 py-2 hover:bg-slate-800/50 rounded-lg transition-colors"
          >
            <span className="mt-0.5 shrink-0">{eventIcon(event.type)}</span>
            <span className="text-slate-500 font-mono text-xs shrink-0">{event.time}</span>
            <span className="text-slate-300 text-sm leading-snug">{event.text}</span>
          </div>
        ))
      )}
      <div ref={bottomRef} />
    </div>
  );
}
