'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { Sidebar } from './sidebar';
import { useWebSocket } from '@/hooks/use-websocket';
import { useChatStore } from '@/stores/chat-store';

// WebSocket is initialized here (app root) so it stays alive across all page
// navigations. Tool calls, thinking status, and skill events are captured even
// when the user is not on the /chat page.
function GlobalWebSocket() {
  useWebSocket();
  return null;
}

// Watches for a pending onboarding greeting and navigates to /chat via Next.js
// router (client-side, no reload) so the Zustand store state is preserved.
function OnboardingNavigator() {
  const router = useRouter();
  const pendingOnboardingGreeting = useChatStore((s) => s.pendingOnboardingGreeting);

  useEffect(() => {
    if (pendingOnboardingGreeting !== null) {
      // Navigate to /chat without a page reload so the store message survives
      if (typeof window !== 'undefined' && !window.location.pathname.startsWith('/chat')) {
        router.push('/chat');
      }
    }
  }, [pendingOnboardingGreeting, router]);

  return null;
}

export function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen bg-slate-950">
      <GlobalWebSocket />
      <OnboardingNavigator />
      <Sidebar />

      {/* Main content */}
      <main className="lg:ml-64 min-h-screen">
        {children}
      </main>
    </div>
  );
}
