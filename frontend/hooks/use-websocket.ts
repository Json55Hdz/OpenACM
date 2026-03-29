'use client';

import { useEffect, useCallback, useRef } from 'react';
import { useChatStore } from '@/stores/chat-store';
import { useAuthStore, authStore } from '@/stores/auth-store';
import { useTerminalStore } from '@/stores/terminal-store';
import { toast } from 'sonner';

const TERMINAL_TOOLS = new Set(['run_command', 'run_python', 'python_kernel', 'execute_command']);

function _mirrorToolToTerminal(phase: 'called' | 'result', tool: string, data: string) {
  if (!TERMINAL_TOOLS.has(tool)) return;
  const store = useTerminalStore.getState();
  if (phase === 'called') {
    // Extract command/code from JSON arguments
    let cmd = data;
    try {
      const args = JSON.parse(data);
      cmd = args.command || args.code || data;
    } catch { /* use raw */ }
    store.addLine({ type: 'ai_input', text: `[AI:${tool}] $ ${cmd}` });
  } else {
    const lines = data.split('\n');
    for (const line of lines) {
      store.addLine({ type: 'ai_output', text: line });
    }
  }
}

interface WebSocketMessage {
  type: string;
  content?: string;
  channel_id?: string;
  user_id?: string;
  channel_type?: string;
  tokens?: number;
  elapsed?: number;
  tool?: string;
  arguments?: string;
  result?: string;
  message?: string;
  status?: string;
  partial?: boolean;
  attachments?: string[];
}

export function useWebSocket() {
  const chatWsRef = useRef<WebSocket | null>(null);
  const eventsWsRef = useRef<WebSocket | null>(null);
  const chatReconnectRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const eventsReconnectRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const keepAliveRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Keep a live ref to the store so callbacks never need to re-create
  const storeRef = useRef(useChatStore.getState());
  useEffect(() => {
    return useChatStore.subscribe((state) => {
      storeRef.current = state;
    });
  }, []);

  const connectChatWs = useCallback(() => {
    const token = authStore.getState().token;
    if (!token) return;

    // Don't reconnect if already connected
    if (chatWsRef.current && chatWsRef.current.readyState === WebSocket.OPEN) {
      return;
    }

    // Close any lingering connection (disable its onclose to prevent cascading reconnects)
    if (chatWsRef.current) {
      chatWsRef.current.onclose = null;
      chatWsRef.current.close();
      chatWsRef.current = null;
    }

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const ws = new WebSocket(`${protocol}//${window.location.host}/ws/chat?token=${token}`);

    chatWsRef.current = ws;
    storeRef.current.setWs(ws);

    ws.onmessage = (event) => {
      const data: WebSocketMessage = JSON.parse(event.data);
      storeRef.current.setWaitingResponse(false);

      if (data.type === 'response') {
        storeRef.current.addMessage({
          content: data.content || '',
          role: 'assistant',
          attachments: (data.attachments || []).map((name: string) => ({ id: name, name, type: 'file' })),
        });
      } else if (data.type === 'command') {
        storeRef.current.addMessage({
          content: data.content || '',
          role: 'system',
        });
      } else if (data.type === 'error') {
        storeRef.current.addMessage({
          content: data.content || 'Unknown error',
          role: 'error',
        });
      }
    };

    ws.onclose = () => {
      chatWsRef.current = null;
      // Clear any pending reconnect before scheduling a new one
      if (chatReconnectRef.current) clearTimeout(chatReconnectRef.current);
      if (authStore.getState().token) {
        chatReconnectRef.current = setTimeout(connectChatWs, 3000);
      }
    };

    ws.onerror = () => {
      storeRef.current.setWaitingResponse(false);
    };
  }, []); // Stable — reads everything from refs/stores

  const connectEventsWs = useCallback(() => {
    const token = authStore.getState().token;
    if (!token) return;

    // Don't reconnect if already connected
    if (eventsWsRef.current && eventsWsRef.current.readyState === WebSocket.OPEN) {
      return;
    }

    // Close any lingering connection
    if (eventsWsRef.current) {
      eventsWsRef.current.onclose = null;
      eventsWsRef.current.close();
      eventsWsRef.current = null;
    }

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const ws = new WebSocket(`${protocol}//${window.location.host}/ws/events?token=${token}`);

    eventsWsRef.current = ws;

    ws.onopen = () => {
      storeRef.current.setWsConnected(true);
    };

    ws.onmessage = (event) => {
      const data: WebSocketMessage = JSON.parse(event.data);
      // Read currentTarget from the live store ref (not a stale closure)
      const { currentTarget, addMessage } = storeRef.current;

      if (data.type === 'message.received') {
        // Web channel messages are already added locally by handleSend() — skip the echo
        if (data.channel_type === 'web') return;
        if (data.channel_id === currentTarget.channel) {
          addMessage({
            content: data.content || '',
            role: 'user',
            badge: `${data.channel_type} - ${data.user_id}`,
          });
        }
      } else if (data.type === 'message.sent') {
        if (data.channel_type === 'web') {
          // Partial messages (AI text emitted before tool calls) — show immediately
          if (data.partial && data.channel_id === currentTarget.channel) {
            addMessage({
              content: data.content || '',
              role: 'assistant',
              attachments: (data.attachments || []).map((name: string) => ({ id: name, name, type: 'file' })),
            });
          }
          // Non-partial web responses come through /ws/chat directly — skip the echo
          return;
        }
        if (data.channel_id === currentTarget.channel) {
          addMessage({
            content: data.content || '',
            role: 'assistant',
            badge: `Reply to ${data.channel_type}`,
            attachments: (data.attachments || []).map((name: string) => ({ id: name, name, type: 'file' })),
          });
        }
      } else if (data.type === 'router.learned') {
        storeRef.current.setRouterLearning(true);
        setTimeout(() => storeRef.current.setRouterLearning(false), 3000);
      } else if (data.type === 'tool.called') {
        if (data.channel_id !== currentTarget.channel) return;
        addMessage({
          content: `Executing: ${data.tool || 'tool'}`,
          role: 'system',
          badge: 'Tool',
          toolCall: {
            tool: data.tool || '',
            arguments: data.arguments || '',
            status: 'running',
          },
        });
        _mirrorToolToTerminal('called', data.tool || '', data.arguments || '');
      } else if (data.type === 'tool.result') {
        if (data.channel_id !== currentTarget.channel) return;
        addMessage({
          content: `${data.tool || 'Tool'} completed`,
          role: 'system',
          badge: 'Tool',
          toolCall: {
            tool: data.tool || '',
            arguments: '',
            result: data.result || '',
            status: 'completed',
          },
        });
        _mirrorToolToTerminal('result', data.tool || '', data.result || '');
      }
    };

    ws.onclose = () => {
      storeRef.current.setWsConnected(false);
      eventsWsRef.current = null;
      if (eventsReconnectRef.current) clearTimeout(eventsReconnectRef.current);
      if (authStore.getState().token) {
        eventsReconnectRef.current = setTimeout(connectEventsWs, 3000);
      }
    };

    ws.onerror = () => {
      storeRef.current.setWsConnected(false);
    };

    // Keep alive (clear old interval first)
    if (keepAliveRef.current) clearInterval(keepAliveRef.current);
    keepAliveRef.current = setInterval(() => {
      if (ws.readyState === WebSocket.OPEN) {
        ws.send('ping');
      }
    }, 30000);
  }, []); // Stable — reads everything from refs/stores

  const sendMessage = useCallback((message: string, attachments: string[] = []) => {
    if (chatWsRef.current && chatWsRef.current.readyState === WebSocket.OPEN) {
      const { currentTarget } = storeRef.current;
      const payload = {
        message,
        target_user_id: currentTarget.user,
        target_channel_id: currentTarget.channel,
        attachments: attachments.length > 0 ? attachments : undefined,
      };
      chatWsRef.current.send(JSON.stringify(payload));
      storeRef.current.setWaitingResponse(true);
      return true;
    }
    return false;
  }, []); // Stable — reads currentTarget from storeRef

  // Single effect that runs once on mount — connect functions are stable
  useEffect(() => {
    const unsubscribe = authStore.subscribe((state) => {
      if (state.token) {
        connectChatWs();
        connectEventsWs();
      }
    });

    // Initial connection if already authenticated
    if (authStore.getState().token) {
      connectChatWs();
      connectEventsWs();
    }

    return () => {
      unsubscribe();
      // Clear all timers
      if (chatReconnectRef.current) clearTimeout(chatReconnectRef.current);
      if (eventsReconnectRef.current) clearTimeout(eventsReconnectRef.current);
      if (keepAliveRef.current) clearInterval(keepAliveRef.current);
      // Disable onclose to prevent reconnect during teardown, then close
      if (chatWsRef.current) {
        chatWsRef.current.onclose = null;
        chatWsRef.current.close();
      }
      if (eventsWsRef.current) {
        eventsWsRef.current.onclose = null;
        eventsWsRef.current.close();
      }
    };
  }, [connectChatWs, connectEventsWs]);

  return { sendMessage };
}

export function useAuth() {
  const { token, isAuthenticated, setToken, clearAuth, checkAuth } = authStore();

  const login = async (tokenInput: string): Promise<boolean> => {
    try {
      const response = await fetch('/api/auth/check', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token: tokenInput }),
      });

      if (response.ok) {
        setToken(tokenInput);
        toast.success('Authentication successful');
        return true;
      }
      return false;
    } catch {
      return false;
    }
  };

  return {
    token,
    isAuthenticated,
    login,
    logout: clearAuth,
    checkAuth,
  };
}
