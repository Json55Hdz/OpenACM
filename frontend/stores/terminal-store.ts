import { create } from 'zustand';

interface TerminalLine {
  type: 'input' | 'output' | 'error' | 'system' | 'ai_input' | 'ai_output';
  text: string;
}

interface TerminalState {
  isOpen: boolean;
  lines: TerminalLine[];
  commandHistory: string[];
  historyIndex: number;
  isConnected: boolean;

  toggleOpen: () => void;
  setOpen: (open: boolean) => void;
  addLine: (line: TerminalLine) => void;
  addOutput: (text: string) => void;
  clearLines: () => void;
  setConnected: (connected: boolean) => void;
  pushCommand: (cmd: string) => void;
  historyUp: () => string;
  historyDown: () => string;
  resetHistoryIndex: () => void;
}

const MAX_LINES = 1000;
const MAX_HISTORY = 100;

export const useTerminalStore = create<TerminalState>((set, get) => ({
  isOpen: false,
  lines: [],
  commandHistory: [],
  historyIndex: -1,
  isConnected: false,

  toggleOpen: () => set((s) => ({ isOpen: !s.isOpen })),
  setOpen: (open) => set({ isOpen: open }),

  addLine: (line) =>
    set((s) => ({
      lines: [...s.lines.slice(-MAX_LINES), line],
    })),

  addOutput: (text) => {
    // Append to last line if it doesn't end with \n (streaming chunks),
    // otherwise start new lines.
    set((s) => {
      const parts = text.split('\n');
      const lines = [...s.lines];

      if (lines.length > 0 && lines[lines.length - 1].type === 'output') {
        // Append first part to the last existing output line
        lines[lines.length - 1] = {
          ...lines[lines.length - 1],
          text: lines[lines.length - 1].text + parts[0],
        };
        // Remaining parts become new lines
        for (let i = 1; i < parts.length; i++) {
          lines.push({ type: 'output', text: parts[i] });
        }
      } else {
        for (const p of parts) {
          lines.push({ type: 'output', text: p });
        }
      }

      return { lines: lines.slice(-MAX_LINES) };
    });
  },

  clearLines: () =>
    set({
      lines: [{ type: 'system', text: 'Terminal cleared.' }],
    }),

  setConnected: (connected) => set({ isConnected: connected }),

  pushCommand: (cmd) =>
    set((s) => ({
      commandHistory: [...s.commandHistory.slice(-MAX_HISTORY), cmd],
      historyIndex: -1,
    })),

  historyUp: () => {
    const { commandHistory, historyIndex } = get();
    if (commandHistory.length === 0) return '';
    const newIndex =
      historyIndex === -1
        ? commandHistory.length - 1
        : Math.max(0, historyIndex - 1);
    set({ historyIndex: newIndex });
    return commandHistory[newIndex] || '';
  },

  historyDown: () => {
    const { commandHistory, historyIndex } = get();
    if (historyIndex === -1) return '';
    const newIndex = historyIndex + 1;
    if (newIndex >= commandHistory.length) {
      set({ historyIndex: -1 });
      return '';
    }
    set({ historyIndex: newIndex });
    return commandHistory[newIndex] || '';
  },

  resetHistoryIndex: () => set({ historyIndex: -1 }),
}));
