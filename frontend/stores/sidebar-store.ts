import { create } from 'zustand';
import { persist } from 'zustand/middleware';

interface SidebarState {
  /** Desktop: collapsed to an icon-only rail when true. Persisted to localStorage. */
  collapsed: boolean;
  toggleCollapsed: () => void;
  setCollapsed: (collapsed: boolean) => void;
}

export const useSidebarStore = create<SidebarState>()(
  persist(
    (set) => ({
      collapsed: false,
      toggleCollapsed: () => set((s) => ({ collapsed: !s.collapsed })),
      setCollapsed: (collapsed: boolean) => set({ collapsed }),
    }),
    {
      name: 'openacm-sidebar-storage',
    }
  )
);
