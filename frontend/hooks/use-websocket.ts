'use client';

import { useEffect, useCallback, useRef } from 'react';
import { useChatStore } from '@/stores/chat-store';
import { useAuthStore, authStore } from '@/stores/auth-store';
import { useTamagotchiStore } from '@/stores/tamagotchi-store';
import { toast } from 'sonner';

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
  skills?: string[];
  usage?: {
    prompt_tokens: number;
    completion_tokens: number;
    total_tokens: number;
    cost: number;
    requests: number;
    model: string;
  };
  // tool.validation fields
  step?: string;
  detail?: string;
  // tool.confirmation_needed fields
  confirm_id?: string;
  command?: string;
}

export function useWebSocket() {
  const chatWsRef = useRef<WebSocket | null>(null);
  const eventsWsRef = useRef<WebSocket | null>(null);
  const chatReconnectRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const eventsReconnectRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const keepAliveRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const thinkingTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const clearThinkingTimeout = () => {
    if (thinkingTimeoutRef.current) {
      clearTimeout(thinkingTimeoutRef.current);
      thinkingTimeoutRef.current = null;
    }
  };

  const resetSpinner = (reason?: string, forKey?: string) => {
    clearThinkingTimeout();
    storeRef.current.resetWaiting(forKey);
    if (reason) {
      storeRef.current.addMessage({ content: reason, role: 'error' }, forKey);
    }
  };

  // Keep a live ref to the store so callbacks never need to re-create
  const storeRef = useRef(useChatStore.getState());
  useEffect(() => {
    return useChatStore.subscribe((state) => {
      storeRef.current = state;
    });
  }, []);

  // Live ref to tamagotchi store — same pattern, no stale closures
  const tamaRef = useRef(useTamagotchiStore.getState());
  useEffect(() => {
    return useTamagotchiStore.subscribe((state) => {
      tamaRef.current = state;
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

    ws.onopen = () => {
      storeRef.current.setWsConnected(true);
    };

    ws.onmessage = (event) => {
      const data: WebSocketMessage = JSON.parse(event.data);

      if (data.type === 'onboarding.greeting') {
        // Store the greeting — app-layout navigates to /chat via Next.js router (no reload)
        // and the chat page adds the greeting to messages on mount.
        storeRef.current.setPendingOnboardingGreeting(data.content || '');
      } else if (data.type === 'response') {
        // Route to the correct conversation even if user has switched chats
        const forKey = data.channel_id && data.user_id
          ? `${data.channel_id}:${data.user_id}`
          : undefined;
        resetSpinner(undefined, forKey);
        tamaRef.current.setAgentState('success');
        storeRef.current.addMessage({
          content: data.content || '',
          role: 'assistant',
          attachments: (data.attachments || []).map((name: string) => ({ id: name, name, type: 'file' })),
          usage: data.usage,
        }, forKey);
      } else if (data.type === 'command') {
        storeRef.current.addMessage({
          content: data.content || '',
          role: 'system',
        });
      } else if (data.type === 'error') {
        const forKey = data.channel_id && data.user_id
          ? `${data.channel_id}:${data.user_id}`
          : undefined;
        resetSpinner(undefined, forKey);
        tamaRef.current.setAgentState('error');
        storeRef.current.addMessage({
          content: data.content || 'Unknown error',
          role: 'error',
        }, forKey);
      }
    };

    ws.onclose = () => {
      chatWsRef.current = null;
      // Don't reset the spinner immediately — the brain may still be processing and
      // will buffer the response for delivery on reconnect. Only reset if the connection
      // stays down for more than 12 seconds (3 reconnect attempts × ~3s each).
      if (chatReconnectRef.current) clearTimeout(chatReconnectRef.current);
      if (authStore.getState().token) {
        chatReconnectRef.current = setTimeout(connectChatWs, 3000);
        // Safety-net spinner reset: fires only if reconnection keeps failing
        setTimeout(() => {
          if (!chatWsRef.current || chatWsRef.current.readyState !== WebSocket.OPEN) {
            resetSpinner('Connection lost. The response may have been buffered — try sending your message again.');
          }
        }, 12000);
      } else {
        resetSpinner();
      }
    };

    ws.onerror = () => {
      // Don't reset spinner on error — onclose fires right after and handles reconnect.
      // Resetting here would clear the thinking indicator even though the brain is still processing.
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
          const { channel_id, partial, is_error, content, attachments: atts } = data as WebSocketMessage & { is_error?: boolean };
          // Always show: partial AI text emitted before tool calls, OR error responses
          // (errors come from brain when LLM times out / fails — show them regardless)
          if ((partial || is_error) && channel_id === currentTarget.channel) {
            addMessage({
              content: content || '',
              role: is_error ? 'error' : 'assistant',
              attachments: (atts || []).map((name: string) => ({ id: name, name, type: 'file' })),
            });
            if (is_error) {
              storeRef.current.setWaitingResponse(false);
              storeRef.current.setThinkingLabel(null);
            }
          }
          // Non-partial, non-error web responses come through /ws/chat directly — skip
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
      } else if (data.type === 'memory.recall') {
        const status = data.status as 'searching' | 'found' | 'empty' | 'saving' | 'saved';
        const count = (data as { count?: number }).count ?? 0;
        storeRef.current.setMemoryRecall({ status, count });
        if (status === 'found' || status === 'empty' || status === 'saved') {
          setTimeout(() => storeRef.current.setMemoryRecall(null), 2500);
        }
      } else if (data.type === 'router.learned') {
        storeRef.current.setRouterLearning(true);
        setTimeout(() => storeRef.current.setRouterLearning(false), 3000);
      } else if (data.type === 'skill.active') {
        const names: string[] = data.skills || [];
        storeRef.current.setActiveSkillNames(names);
        setTimeout(() => storeRef.current.setActiveSkillNames([]), 5000);
      } else if (data.type === 'message.thinking') {
        const status = data.status;
        if (status === 'start') {
          storeRef.current.setWaitingResponse(true);
          storeRef.current.setThinkingLabel(null);
          tamaRef.current.setAgentState('thinking');
        } else if (status === 'tool_running' && data.message) {
          storeRef.current.setThinkingLabel(data.message);
          tamaRef.current.setAgentState('working');
        } else if (status === 'queued' && data.message) {
          storeRef.current.setThinkingLabel(data.message);
          tamaRef.current.setAgentState('thinking');
        } else if (status === 'done' || status === 'error') {
          resetSpinner();
          tamaRef.current.setAgentState(status === 'done' ? 'success' : 'error');
        }
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
        // terminal WS path handles this — no mirror needed
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
        // terminal WS path handles this — no mirror needed
      } else if (data.type === 'tool.validation') {
        if (data.channel_id !== currentTarget.channel) return;
        const tool = data.tool || '';
        const stepName = data.step || '';
        const status = (data.status || 'running') as 'running' | 'passed' | 'failed' | 'warning';
        const detail = data.detail || '';

        if (stepName === '__done__') {
          // Mark the validation panel as finished
          storeRef.current.upsertValidationStep(
            tool,
            { step: '__done__', status, detail: '' },
            true,
            status === 'passed',
          );
        } else {
          storeRef.current.upsertValidationStep(tool, { step: stepName, status, detail });
        }
      } else if (data.type === 'tool.confirmation_needed') {
        if (data.channel_id !== currentTarget.channel) return;
        storeRef.current.addMessage({
          content: data.command || '',
          role: 'system',
          badge: 'Confirm',
          toolConfirmation: {
            confirmId: data.confirm_id || '',
            tool: data.tool || '',
            command: data.command || '',
          },
        });
      } else if (data.type === 'memory.compacted') {
        const forKey = data.channel_id && data.user_id
          ? `${data.channel_id}:${data.user_id}`
          : undefined;
        storeRef.current.addMessage({
          content: '',
          role: 'system',
          compactionNote: {
            summary: (data as { summary?: string }).summary || '',
            summarizedMessages: (data as { summarized_messages?: number }).summarized_messages ?? 0,
          },
        }, forKey);
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
      // Safety net: if no response in 3 min, reset spinner automatically
      clearThinkingTimeout();
      thinkingTimeoutRef.current = setTimeout(() => {
        resetSpinner('The response took too long or the connection was interrupted. Please try again.');
      }, 3 * 60 * 1000);
      return true;
    }
    return false;
  }, []); // Stable — reads currentTarget from storeRef

  const cancelMessage = useCallback(() => {
    if (chatWsRef.current && chatWsRef.current.readyState === WebSocket.OPEN) {
      const { currentTarget } = storeRef.current;
      chatWsRef.current.send(JSON.stringify({
        type: 'cancel',
        target_user_id: currentTarget.user,
        target_channel_id: currentTarget.channel,
      }));
      storeRef.current.setWaitingResponse(false);
    }
  }, []);

  // Single effect — runs once. Does NOT close WS on unmount so the connection
  // survives navigation between pages (app-layout keeps this hook alive).
  useEffect(() => {
    const unsubscribe = authStore.subscribe((state) => {
      if (state.token) {
        connectChatWs();
        connectEventsWs();
      }
    });

    if (authStore.getState().token) {
      connectChatWs();
      connectEventsWs();
    }

    // Expose sendMessage/cancelMessage globally via the store so any page can use it
    useChatStore.getState().setSendMessageFn(sendMessage);
    useChatStore.getState().setCancelMessageFn(cancelMessage);

    // Guard against any spurious idle transition while waiting for a response.
    // Lottie-web registers its own visibilitychange listener that can fire onComplete
    // with a stale closure (isLooping=false) when switching tabs, resetting the state.
    // Whenever tamagotchi goes idle while isWaitingResponse is still true, restore it.
    const unsubscribeTamaGuard = useTamagotchiStore.subscribe((tama) => {
      if (tama.agentState === 'idle') {
        const { isWaitingResponse, thinkingLabel } = useChatStore.getState();
        if (isWaitingResponse) {
          useTamagotchiStore.getState().setAgentState(thinkingLabel ? 'working' : 'thinking');
        }
      }
    });

    return () => {
      unsubscribe();
      unsubscribeTamaGuard();
      // Only clear timers on unmount — WS connections stay alive
      if (chatReconnectRef.current) clearTimeout(chatReconnectRef.current);
      if (eventsReconnectRef.current) clearTimeout(eventsReconnectRef.current);
      if (keepAliveRef.current) clearInterval(keepAliveRef.current);
    };
  }, [connectChatWs, connectEventsWs, sendMessage, cancelMessage]);

  return { sendMessage, cancelMessage };
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
