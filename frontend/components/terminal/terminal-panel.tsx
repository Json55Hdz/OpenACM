'use client';

import { useEffect, useRef, useCallback } from 'react';
import { Terminal as TerminalIcon, X, Trash2, Circle } from 'lucide-react';
import { useTerminalStore } from '@/stores/terminal-store';
import { useAuthStore } from '@/stores/auth-store';
import { useChatStore } from '@/stores/chat-store';

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

      // Forward all keystrokes directly to the shell via WS
      term.onData((data: string) => {
        if (wsRef.current?.readyState === WebSocket.OPEN) {
          wsRef.current.send(JSON.stringify({ type: 'input', data }));
        }
      });

      connectWs();
    });

    return () => {
      if (reconnectRef.current) clearTimeout(reconnectRef.current);
    };
  }, [isOpen, connectWs]);

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
