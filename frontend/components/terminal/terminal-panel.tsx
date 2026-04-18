'use client';

import { useEffect, useRef, useCallback, useState } from 'react';
import { Terminal as TerminalIcon, X, Trash2, Circle, MessageSquare, Shell, Bot } from 'lucide-react';
import { useTerminalStore } from '@/stores/terminal-store';
import { useAuthStore } from '@/stores/auth-store';
import { useChatStore } from '@/stores/chat-store';

type TermMode = 'shell' | 'chat';

export function TerminalPanel() {
  const { isOpen, isConnected, setOpen, setConnected } = useTerminalStore();
  const termContainerRef = useRef<HTMLDivElement>(null);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const xtermRef = useRef<any>(null);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const fitAddonRef = useRef<any>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const channelRef = useRef<string>('web');
  const initializedRef = useRef(false);

  // Pending confirmation state — when set, the next y/n + Enter resolves it instead of
  // sending a shell command.
  const pendingConfirmRef = useRef<{ confirmId: string; resolve: (approved: boolean) => void } | null>(null);

  // Chat-mode line buffer — accumulated chars until user presses Enter
  const chatLineRef = useRef<string>('');
  const [mode, setMode] = useState<TermMode>('shell');
  const modeRef = useRef<TermMode>('shell');

  const switchMode = useCallback((next: TermMode) => {
    modeRef.current = next;
    setMode(next);
    const term = xtermRef.current;
    if (!term) return;
    if (next === 'chat') {
      term.write('\r\n\x1b[33m─── Chat mode (Ctrl+` to switch back) ───\x1b[0m\r\n\x1b[33myou>\x1b[0m ');
      chatLineRef.current = '';
    } else {
      term.write('\r\n\x1b[32m─── Shell mode (Ctrl+` to chat) ─────────\x1b[0m\r\n');
    }
  }, []);

  // Track channel changes — reconnect terminal when user switches channel
  useEffect(() => {
    channelRef.current = useChatStore.getState().currentTarget.channel;
    const unsub = useChatStore.subscribe((state) => {
      const ch = state.currentTarget.channel;
      if (ch !== channelRef.current) {
        channelRef.current = ch;
        if (wsRef.current) {
          wsRef.current.onclose = null;
          wsRef.current.close();
          wsRef.current = null;
        }
        connectWs();
      }
    });
    return unsub;
  // connectWs is stable (useCallback [] deps)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const connectWs = useCallback(() => {
    const token = useAuthStore.getState().token;
    if (!token) return;
    if (wsRef.current?.readyState === WebSocket.OPEN) return;

    if (wsRef.current) {
      wsRef.current.onclose = null;
      wsRef.current.close();
      wsRef.current = null;
    }

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const channel = channelRef.current;
    const ws = new WebSocket(
      `${protocol}//${window.location.host}/ws/terminal?token=${token}&channel=${encodeURIComponent(channel)}`,
    );
    wsRef.current = ws;

    ws.onopen = () => {
      setConnected(true);
      if (fitAddonRef.current && xtermRef.current) {
        fitAddonRef.current.fit();
        ws.send(JSON.stringify({ type: 'resize', cols: xtermRef.current.cols, rows: xtermRef.current.rows }));
      }
    };

    ws.onmessage = (event) => {
      if (!xtermRef.current) return;
      try {
        const data = JSON.parse(event.data);
        if (data.type === 'output') {
          xtermRef.current.write(data.data ?? '');
        } else if (data.type === 'ai_command') {
          const tool = data.tool || 'run_command';
          xtermRef.current.write(`\r\n\x1b[35m[AI:${tool}] $ ${data.data ?? ''}\x1b[0m\r\n`);
        } else if (data.type === 'ai_output') {
          xtermRef.current.write(data.data ?? '');
        } else if (data.type === 'ai_text') {
          const text = (data.data ?? '').replace(/\n/g, '\r\n');
          xtermRef.current.write(`\r\n\x1b[36m[ACM]\x1b[0m ${text}\r\n`);
          // Re-render chat prompt if we're in chat mode
          if (modeRef.current === 'chat') {
            xtermRef.current.write(`\x1b[33myou>\x1b[0m `);
            chatLineRef.current = '';
          }
        } else if (data.type === 'tool_confirm') {
          // Show confirmation prompt and enter confirm mode
          const confirmId = data.confirm_id ?? '';
          const command = data.data ?? '';
          const tool = data.tool ?? 'run_command';
          xtermRef.current.write(
            `\r\n\x1b[33m[CONFIRM]\x1b[0m Allow \x1b[35m${tool}\x1b[0m: \x1b[36m${command}\x1b[0m\r\n` +
            `\x1b[33m  Type y to allow, n to deny, then press Enter:\x1b[0m `,
          );
          // Register pending confirmation
          pendingConfirmRef.current = {
            confirmId,
            resolve: async (approved: boolean) => {
              const token = useAuthStore.getState().token;
              try {
                await fetch('/api/tool/confirm', {
                  method: 'POST',
                  headers: {
                    'Content-Type': 'application/json',
                    ...(token ? { Authorization: `Bearer ${token}` } : {}),
                  },
                  body: JSON.stringify({ confirm_id: confirmId, approved }),
                });
              } catch { /* best-effort */ }
              if (xtermRef.current) {
                xtermRef.current.write(
                  approved
                    ? `\r\n\x1b[32m[Allowed]\x1b[0m\r\n`
                    : `\r\n\x1b[31m[Denied]\x1b[0m\r\n`,
                );
              }
            },
          };
        } else if (data.type === 'exit') {
          xtermRef.current.write('\r\n\x1b[33m[shell process exited]\x1b[0m\r\n');
          setConnected(false);
        } else if (data.type === 'error') {
          xtermRef.current.write(`\r\n\x1b[31m[error] ${data.data ?? ''}\x1b[0m\r\n`);
        }
      } catch {
        xtermRef.current.write(event.data);
      }
    };

    ws.onclose = () => {
      wsRef.current = null;
      setConnected(false);
      if (reconnectRef.current) clearTimeout(reconnectRef.current);
      if (useAuthStore.getState().token) {
        reconnectRef.current = setTimeout(connectWs, 3000);
      }
    };

    ws.onerror = () => setConnected(false);
  }, [setConnected]);

  // Initialize xterm.js the first time the panel opens
  useEffect(() => {
    if (!isOpen || !termContainerRef.current || initializedRef.current) return;
    initializedRef.current = true;

    Promise.all([
      import('@xterm/xterm'),
      import('@xterm/addon-fit'),
    ]).then(([{ Terminal }, { FitAddon }]) => {
      if (!termContainerRef.current) return;

      const term = new Terminal({
        cursorBlink: true,
        fontSize: 12,
        fontFamily: 'Menlo, Monaco, "Cascadia Code", Consolas, "Courier New", monospace',
        convertEol: true,
        scrollback: 5000,
        theme: {
          background: '#020617',
          foreground: '#cbd5e1',
          cursor: '#94a3b8',
          selectionBackground: '#334155',
          black: '#1e293b',
          red: '#f87171',
          green: '#4ade80',
          yellow: '#facc15',
          blue: '#60a5fa',
          magenta: '#c084fc',
          cyan: '#22d3ee',
          white: '#f1f5f9',
          brightBlack: '#475569',
          brightRed: '#fca5a5',
          brightGreen: '#86efac',
          brightYellow: '#fde047',
          brightBlue: '#93c5fd',
          brightMagenta: '#d8b4fe',
          brightCyan: '#67e8f9',
          brightWhite: '#ffffff',
        },
      });

      const fitAddon = new FitAddon();
      term.loadAddon(fitAddon);
      term.open(termContainerRef.current);
      fitAddon.fit();

      xtermRef.current = term;
      fitAddonRef.current = fitAddon;

      term.onData((data: string) => {
        const ws = wsRef.current;
        if (!ws || ws.readyState !== WebSocket.OPEN) return;

        // Ctrl+` (code 96) — toggle mode
        if (data === '\x60') {
          switchMode(modeRef.current === 'shell' ? 'chat' : 'shell');
          return;
        }

        if (modeRef.current === 'shell') {
          // If there's a pending confirmation, intercept y/n + Enter
          if (pendingConfirmRef.current) {
            const pending = pendingConfirmRef.current;
            if (data === '\r' || data === '\n') {
              // We don't have a line buffer here — just echo CR and treat as deny
              term.write('\r\n');
              pendingConfirmRef.current = null;
              pending.resolve(false);
            } else if (data === 'y' || data === 'Y') {
              term.write('y\r\n');
              pendingConfirmRef.current = null;
              pending.resolve(true);
            } else if (data === 'n' || data === 'N') {
              term.write('n\r\n');
              pendingConfirmRef.current = null;
              pending.resolve(false);
            }
            // Ignore other keys while waiting for confirmation
            return;
          }
          ws.send(JSON.stringify({ type: 'input', data }));
          return;
        }

        // ── Chat mode: collect line, echo locally ──
        if (data === '\r' || data === '\n') {
          // Submit line
          const line = chatLineRef.current.trim();
          chatLineRef.current = '';
          term.write('\r\n');
          if (line) {
            ws.send(JSON.stringify({ type: 'chat_input', data: line }));
            // Show a thinking indicator; ACM response will replace the prompt
            term.write('\x1b[90m[thinking…]\x1b[0m\r\n');
          } else {
            term.write('\x1b[33myou>\x1b[0m ');
          }
        } else if (data === '\x7f' || data === '\x08') {
          // Backspace
          if (chatLineRef.current.length > 0) {
            chatLineRef.current = chatLineRef.current.slice(0, -1);
            term.write('\b \b');
          }
        } else if (data === '\x03') {
          // Ctrl+C — clear line
          chatLineRef.current = '';
          term.write('^C\r\n\x1b[33myou>\x1b[0m ');
        } else if (data >= ' ' || data === '\t') {
          // Printable character
          chatLineRef.current += data;
          term.write(data);
        }
      });

      connectWs();
    });

    return () => {
      if (reconnectRef.current) clearTimeout(reconnectRef.current);
    };
  }, [isOpen, connectWs, switchMode]);

  // Resize observer → fit xterm + notify backend of new dimensions
  useEffect(() => {
    if (!isOpen) return;
    const observer = new ResizeObserver(() => {
      if (fitAddonRef.current && xtermRef.current) {
        try {
          fitAddonRef.current.fit();
          if (wsRef.current?.readyState === WebSocket.OPEN) {
            wsRef.current.send(
              JSON.stringify({ type: 'resize', cols: xtermRef.current.cols, rows: xtermRef.current.rows }),
            );
          }
        } catch { /* ignore */ }
      }
    });
    if (termContainerRef.current) observer.observe(termContainerRef.current);
    return () => observer.disconnect();
  }, [isOpen]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (reconnectRef.current) clearTimeout(reconnectRef.current);
      if (wsRef.current) {
        wsRef.current.onclose = null;
        wsRef.current.close();
      }
      xtermRef.current?.dispose();
      xtermRef.current = null;
      fitAddonRef.current = null;
      initializedRef.current = false;
    };
  }, []);

  if (!isOpen) return null;

  return (
    <div className="border-t border-slate-700 bg-[#020617] flex flex-col" style={{ height: '280px' }}>
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-1.5 bg-slate-900 border-b border-slate-800 shrink-0">
        <div className="flex items-center gap-2">
          <TerminalIcon size={14} className="text-slate-400" />
          <span className="text-xs font-medium text-slate-300">Terminal</span>
          <span className="text-xs text-slate-600">({channelRef.current})</span>
          <Circle
            size={8}
            className={isConnected ? 'fill-green-500 text-green-500' : 'fill-red-500 text-red-500'}
          />
        </div>
        <div className="flex items-center gap-1">
          {/* Launch ACM CLI in the real PTY */}
          <button
            onClick={() => {
              if (wsRef.current?.readyState === WebSocket.OPEN) {
                wsRef.current.send(JSON.stringify({ type: 'input', data: 'openacm-cli\r' }));
                // Switch back to shell mode so keystrokes go to the PTY
                if (modeRef.current !== 'shell') switchMode('shell');
              }
            }}
            className="flex items-center gap-1 px-2 py-0.5 rounded text-xs text-slate-500 hover:text-cyan-400 transition-colors"
            title="Launch OpenACM interactive CLI in terminal"
          >
            <Bot size={11} />
            acm
          </button>
          {/* Mode toggle */}
          <button
            onClick={() => switchMode(mode === 'shell' ? 'chat' : 'shell')}
            className={`flex items-center gap-1 px-2 py-0.5 rounded text-xs transition-colors ${
              mode === 'chat'
                ? 'bg-cyan-900/50 text-cyan-400 border border-cyan-700'
                : 'text-slate-500 hover:text-slate-300'
            }`}
            title="Toggle shell / chat mode (Ctrl+`)"
          >
            {mode === 'chat' ? <MessageSquare size={11} /> : <Shell size={11} />}
            {mode === 'chat' ? 'chat' : 'shell'}
          </button>
          <button
            onClick={() => xtermRef.current?.clear()}
            className="p-1 text-slate-500 hover:text-slate-300 transition-colors"
            title="Clear"
          >
            <Trash2 size={13} />
          </button>
          <button
            onClick={() => setOpen(false)}
            className="p-1 text-slate-500 hover:text-slate-300 transition-colors"
            title="Close terminal"
          >
            <X size={13} />
          </button>
        </div>
      </div>

      {/* xterm.js mounts here */}
      <div ref={termContainerRef} className="flex-1 overflow-hidden" style={{ padding: '4px 6px' }} />
    </div>
  );
}
