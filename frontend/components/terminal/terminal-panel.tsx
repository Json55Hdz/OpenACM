'use client';

import { useEffect, useRef, useState, useCallback, KeyboardEvent } from 'react';
import { useTerminalStore } from '@/stores/terminal-store';
import { useAuthStore } from '@/stores/auth-store';
import { Terminal, X, Trash2, Circle } from 'lucide-react';

export function TerminalPanel() {
  const {
    lines,
    isConnected,
    isOpen,
    setOpen,
    addLine,
    addOutput,
    clearLines,
    setConnected,
    pushCommand,
    historyUp,
    historyDown,
    resetHistoryIndex,
  } = useTerminalStore();

  const [input, setInput] = useState('');
  const wsRef = useRef<WebSocket | null>(null);
  const outputRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const reconnectRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const connect = useCallback(() => {
    const token = useAuthStore.getState().token;
    if (!token) return;

    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) return;

    if (wsRef.current) {
      wsRef.current.onclose = null;
      wsRef.current.close();
      wsRef.current = null;
    }

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const ws = new WebSocket(
      `${protocol}//${window.location.host}/ws/terminal?token=${token}`
    );
    wsRef.current = ws;

    ws.onopen = () => {
      setConnected(true);
      addLine({ type: 'system', text: 'Terminal connected.' });
    };

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (data.type === 'output') {
          addOutput(data.data || '');
        } else if (data.type === 'exit') {
          addLine({
            type: 'system',
            text: `Process exited with code ${data.code ?? 0}`,
          });
          setConnected(false);
        } else if (data.type === 'error') {
          addLine({ type: 'error', text: data.data || 'Unknown error' });
        } else if (data.type === 'ai_command') {
          // AI is running a command — show it with [AI] prefix
          const tool = data.tool || 'run_command';
          addLine({ type: 'ai_input', text: `[AI:${tool}] $ ${data.data || ''}` });
        } else if (data.type === 'ai_output') {
          // AI command output — stream chunks line by line
          addOutput(data.data || '');
        }
      } catch {
        // Raw text fallback
        addOutput(event.data);
      }
    };

    ws.onclose = () => {
      wsRef.current = null;
      setConnected(false);
      if (reconnectRef.current) clearTimeout(reconnectRef.current);
      if (useAuthStore.getState().token) {
        reconnectRef.current = setTimeout(connect, 3000);
      }
    };

    ws.onerror = () => {
      setConnected(false);
    };
  }, [setConnected, addLine, addOutput]);

  // Connect when panel opens, disconnect when it closes
  useEffect(() => {
    if (isOpen) {
      connect();
      // Focus input when panel opens
      setTimeout(() => inputRef.current?.focus(), 100);
    }
    return () => {
      if (reconnectRef.current) clearTimeout(reconnectRef.current);
    };
  }, [isOpen, connect]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (reconnectRef.current) clearTimeout(reconnectRef.current);
      if (wsRef.current) {
        wsRef.current.onclose = null;
        wsRef.current.close();
      }
    };
  }, []);

  // Auto-scroll to bottom
  useEffect(() => {
    if (outputRef.current) {
      outputRef.current.scrollTop = outputRef.current.scrollHeight;
    }
  }, [lines]);

  const sendCommand = (cmd: string) => {
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return;
    wsRef.current.send(JSON.stringify({ type: 'input', data: cmd + '\n' }));
    addLine({ type: 'input', text: `$ ${cmd}` });
    pushCommand(cmd);
    setInput('');
    resetHistoryIndex();
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      if (input.trim()) {
        sendCommand(input);
      }
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      const cmd = historyUp();
      setInput(cmd);
    } else if (e.key === 'ArrowDown') {
      e.preventDefault();
      const cmd = historyDown();
      setInput(cmd);
    } else if (e.key === 'c' && e.ctrlKey) {
      // Send Ctrl+C to kill running process
      if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
        wsRef.current.send(JSON.stringify({ type: 'signal', data: 'SIGINT' }));
        addLine({ type: 'system', text: '^C' });
      }
    } else if (e.key === 'l' && e.ctrlKey) {
      e.preventDefault();
      clearLines();
    }
  };

  if (!isOpen) return null;

  return (
    <div className="border-t border-slate-700 bg-slate-950 flex flex-col" style={{ height: '280px' }}>
      {/* Terminal Header */}
      <div className="flex items-center justify-between px-3 py-1.5 bg-slate-900 border-b border-slate-800 shrink-0">
        <div className="flex items-center gap-2">
          <Terminal size={14} className="text-slate-400" />
          <span className="text-xs font-medium text-slate-300">Terminal</span>
          <Circle
            size={8}
            className={isConnected ? 'fill-green-500 text-green-500' : 'fill-red-500 text-red-500'}
          />
        </div>
        <div className="flex items-center gap-1">
          <button
            onClick={clearLines}
            className="p-1 text-slate-500 hover:text-slate-300 transition-colors"
            title="Clear (Ctrl+L)"
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

      {/* Terminal Output */}
      <div
        ref={outputRef}
        className="flex-1 overflow-y-auto overflow-x-auto p-2 font-mono text-xs leading-5 select-text cursor-text"
      >
        {lines.map((line, i) => (
          <div
            key={i}
            className={
              line.type === 'input'
                ? 'text-green-400'
                : line.type === 'error'
                ? 'text-red-400'
                : line.type === 'system'
                ? 'text-yellow-500 italic'
                : line.type === 'ai_input'
                ? 'text-purple-400 font-semibold'
                : line.type === 'ai_output'
                ? 'text-purple-200/70'
                : 'text-slate-300'
            }
          >
            {line.text === '' ? '\u00A0' : line.text}
          </div>
        ))}
      </div>

      {/* Terminal Input */}
      <div className="flex items-center px-2 py-1.5 border-t border-slate-800 bg-slate-900/50 shrink-0">
        <span className="text-green-400 font-mono text-xs mr-1.5 select-none">$</span>
        <input
          ref={inputRef}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={isConnected ? 'Type a command...' : 'Connecting...'}
          disabled={!isConnected}
          className="flex-1 bg-transparent text-slate-200 font-mono text-xs placeholder-slate-600 outline-none disabled:opacity-50"
          autoComplete="off"
          spellCheck={false}
        />
      </div>
    </div>
  );
}
