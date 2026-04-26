'use client';

import { useState, useEffect } from 'react';
import { useRouter, usePathname } from 'next/navigation';
import { useAuthStore } from '@/stores/auth-store';
import { useAuth, useWebSocket } from '@/hooks/use-websocket';
import { useConfigStatus } from '@/hooks/use-setup';
import { toast } from 'sonner';
import { translations } from '@/lib/translations';
import { VoiceProvider } from '@/components/providers/voice-provider';

// Single global WS instance — lives at the app root so it survives all page navigations.
function GlobalWebSocket() {
  useWebSocket();
  return null;
}

const t = translations.auth;

export function AuthGate({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const [isLoading, setIsLoading] = useState(true);
  const [isAuth, setIsAuth] = useState(false);
  const [tokenInput, setTokenInput] = useState('');
  const [showError, setShowError] = useState(false);
  const { login } = useAuth();
  const checkAuth = useAuthStore((state) => state.checkAuth);

  const isOnboardingPage = pathname === '/onboarding';
  const { data: configStatus, isLoading: configLoading } = useConfigStatus();

  useEffect(() => {
    const init = async () => {
      const authed = await checkAuth();
      setIsAuth(authed);
      setIsLoading(false);
    };
    init();
  }, [checkAuth]);

  // Redirect to onboarding if setup is needed (but not if already there)
  useEffect(() => {
    if (!isAuth || isOnboardingPage) return;
    if (configLoading) return;
    if (configStatus?.needs_setup) {
      router.push('/onboarding');
    }
  }, [isAuth, configStatus, configLoading, router, isOnboardingPage]);

  // Also redirect immediately after login if config already resolved
  useEffect(() => {
    if (!isAuth || isOnboardingPage) return;
    if (!configLoading && configStatus?.needs_setup) {
      router.push('/onboarding');
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isAuth]); // runs specifically when auth state changes

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setShowError(false);

    const success = await login(tokenInput.trim());
    if (success) {
      setIsAuth(true);
    } else {
      setShowError(true);
      toast.error(t.invalidToken);
    }
  };

  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-slate-900">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-500"></div>
      </div>
    );
  }

  if (!isAuth) {
    return (
      <div className="fixed inset-0 bg-black/80 flex items-center justify-center z-[10000]">
        <div className="bg-slate-800 rounded-xl p-8 max-w-md w-full mx-4 border border-slate-700">
          <div className="text-center mb-6">
            <span className="text-4xl">🔑</span>
            <h1 className="text-2xl font-bold text-white mt-4">{t.title}</h1>
            <p className="text-slate-400 mt-2">{t.subtitle}</p>
          </div>

          <form onSubmit={handleSubmit}>
            <div className="mb-4">
              <label className="block text-sm font-medium text-slate-300 mb-2">
                {t.tokenLabel}
              </label>
              <input
                type="password"
                value={tokenInput}
                onChange={(e) => setTokenInput(e.target.value)}
                placeholder={t.tokenPlaceholder}
                className="w-full px-4 py-3 bg-slate-900 border border-slate-600 rounded-lg text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                required
              />
              {showError && (
                <p className="text-red-500 text-sm mt-2">{t.invalidToken}</p>
              )}
            </div>

            <button
              type="submit"
              className="w-full py-3 px-4 bg-gradient-to-r from-blue-600 to-purple-600 hover:from-blue-700 hover:to-purple-700 text-white font-medium rounded-lg transition-all"
            >
              {t.submitButton}
            </button>
          </form>
        </div>
      </div>
    );
  }

  // If we're on the onboarding page, let it render freely (it handles its own flow)
  if (isOnboardingPage) {
    return <>{children}</>;
  }

  // Still loading config status - show spinner briefly
  if (configLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-slate-900">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-500"></div>
      </div>
    );
  }

  // If needs setup, the useEffect above will redirect - show nothing to avoid flash
  if (configStatus?.needs_setup) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-slate-900">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-500"></div>
      </div>
    );
  }

  return (
    <VoiceProvider>
      <GlobalWebSocket />
      {children}
    </VoiceProvider>
  );
}
