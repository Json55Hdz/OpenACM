import { create } from 'zustand';

interface TerminalState {
  isOpen: boolean;
  isConnected: boolean;
  toggleOpen: () => void;
  setOpen: (open: boolean) => void;
  setConnected: (connected: boolean) => void;
}

export const useTerminalStore = create<TerminalState>((set) => ({
  isOpen: false,
  isConnected: false,
  toggleOpen: () => set((s) => ({ isOpen: !s.isOpen })),
  setOpen: (open) => set({ isOpen: open }),
  setConnected: (connected) => set({ isConnected: connected }),
}));
