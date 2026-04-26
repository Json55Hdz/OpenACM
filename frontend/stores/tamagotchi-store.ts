import { create } from 'zustand';
import { persist } from 'zustand/middleware';

export type AgentState = 'idle' | 'thinking' | 'working' | 'success' | 'error';

export interface DockRect { x: number; y: number; w: number; h: number; }

interface TamagotchiState {
  agentState: AgentState;
  activeSkin: string;
  // Free-floating position (center point, persisted)
  tamaFloatX: number;
  tamaFloatY: number;
  // Set by TamaPlaceholder when the daemon page is mounted; null otherwise
  tamaDockedRect: DockRect | null;

  setAgentState: (state: AgentState) => void;
  setActiveSkin: (skin: string) => void;
  setTamaFloat: (x: number, y: number) => void;
  setTamaDockedRect: (rect: DockRect | null) => void;
}

export const useTamagotchiStore = create<TamagotchiState>()(
  persist(
    (set, get) => ({
      agentState:      'idle',
      activeSkin:      'ai_robot',
      tamaFloatX:      120,
      tamaFloatY:      120,
      tamaDockedRect:  null,

      setAgentState: (state) => {
        set({ agentState: state });
        // One-shot animations auto-reset to idle (safety net if onComplete doesn't fire)
        if (state === 'success' || state === 'error') {
          setTimeout(() => {
            if (get().agentState === state) set({ agentState: 'idle' });
          }, 4000);
        }
      },

      setActiveSkin:     (skin) => set({ activeSkin: skin }),
      setTamaFloat:      (x, y) => set({ tamaFloatX: x, tamaFloatY: y }),
      setTamaDockedRect: (rect)  => set({ tamaDockedRect: rect }),
    }),
    {
      name: 'tamagotchi-store',
      // Persist skin + last float position; dockedRect is ephemeral (DOM-derived)
      partialize: (state) => ({
        activeSkin: state.activeSkin,
        tamaFloatX: state.tamaFloatX,
        tamaFloatY: state.tamaFloatY,
      }),
    }
  )
);
