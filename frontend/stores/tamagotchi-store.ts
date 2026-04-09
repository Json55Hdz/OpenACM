import { create } from 'zustand';
import { persist } from 'zustand/middleware';

export type AgentState = 'idle' | 'thinking' | 'working' | 'success' | 'error';

interface TamagotchiState {
  agentState: AgentState;
  activeSkin: string;
  setAgentState: (state: AgentState) => void;
  setActiveSkin: (skin: string) => void;
}

export const useTamagotchiStore = create<TamagotchiState>()(
  persist(
    (set, get) => ({
      agentState: 'idle',
      activeSkin: 'space_cat',

      setAgentState: (state) => {
        set({ agentState: state });
        // One-shot animations auto-reset to idle (safety net if onComplete doesn't fire)
        if (state === 'success' || state === 'error') {
          setTimeout(() => {
            if (get().agentState === state) {
              set({ agentState: 'idle' });
            }
          }, 4000);
        }
      },

      setActiveSkin: (skin) => set({ activeSkin: skin }),
    }),
    {
      name: 'tamagotchi-store',
      partialize: (state) => ({ activeSkin: state.activeSkin }),
    }
  )
);
