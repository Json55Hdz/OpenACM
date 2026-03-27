import { create } from 'zustand';

interface DashboardStats {
  messagesToday: number;
  tokensToday: number;
  toolCalls: number;
  activeConversations: number;
  currentModel: string;
}

interface DashboardState {
  stats: DashboardStats;
  isOnline: boolean;
  setStats: (stats: Partial<DashboardStats>) => void;
  setOnline: (online: boolean) => void;
}

export const useDashboardStore = create<DashboardState>((set) => ({
  stats: {
    messagesToday: 0,
    tokensToday: 0,
    toolCalls: 0,
    activeConversations: 0,
    currentModel: 'Loading...',
  },
  isOnline: false,
  
  setStats: (stats) => set((state) => ({ stats: { ...state.stats, ...stats } })),
  setOnline: (online) => set({ isOnline: online }),
}));
