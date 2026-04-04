import { create } from 'zustand';
import { persist } from 'zustand/middleware';

interface AuthState {
  token: string | null;
  isAuthenticated: boolean;
  setToken: (token: string) => void;
  clearAuth: () => void;
  checkAuth: () => Promise<boolean>;
}

// Create store with persist middleware
const store = create<AuthState>()(
  persist(
    (set, get) => ({
      token: null,
      isAuthenticated: false,
      
      setToken: (token: string) => {
        set({ token, isAuthenticated: true });
      },
      
      clearAuth: () => {
        set({ token: null, isAuthenticated: false });
      },
      
      checkAuth: async () => {
        const token = get().token;
        if (!token) return false;

        try {
          const response = await fetch('/api/auth/check', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ token }),
          });

          if (!response.ok) {
            get().clearAuth();
            return false;
          }

          // Ensure isAuthenticated is true in the store after a successful check
          set({ isAuthenticated: true });
          return true;
        } catch {
          return false;
        }
      },
    }),
    {
      name: 'openacm-auth-storage',
    }
  )
);

// Export the hook
export const useAuthStore = store;

// Export the store instance for direct access (subscribe, getState, etc.)
export const authStore = store;
