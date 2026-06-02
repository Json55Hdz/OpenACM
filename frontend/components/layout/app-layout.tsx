'use client';

import { useEffect, useState } from 'react';
import { useRouter, usePathname } from 'next/navigation';
import { Sidebar } from './sidebar';
import { useChatStore } from '@/stores/chat-store';
import { GlobalTamagotchi } from '@/components/tamagotchi/global-tamagotchi';

function OnboardingNavigator() {
  const router = useRouter();
  const pendingOnboardingGreeting = useChatStore((s) => s.pendingOnboardingGreeting);

  useEffect(() => {
    if (pendingOnboardingGreeting !== null) {
      if (typeof window !== 'undefined' && !window.location.pathname.startsWith('/chat')) {
        router.push('/chat');
      }
    }
  }, [pendingOnboardingGreeting, router]);

  return null;
}

// Redirects to /chat if the current page is not in the client profile's allowed_pages
function ClientProfileGuard() {
  const router = useRouter();
  const pathname = usePathname();

  useEffect(() => {
    const check = async () => {
      try {
        const res = await fetch('/api/config/client-profile');
        if (!res.ok) return;
        const profile = await res.json();
        if (!profile.active || profile.allowed_pages.length === 0) return;
        const allowed: string[] = profile.allowed_pages;
        const isAllowed = allowed.some((p: string) => pathname === p || pathname.startsWith(p + '/'));
        if (!isAllowed) router.replace('/chat');
      } catch { /* ignore */ }
    };
    check();
  }, [pathname, router]);

  return null;
}

export function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen bg-[var(--acm-base)]">
      <OnboardingNavigator />
      <ClientProfileGuard />
      <Sidebar />
      <GlobalTamagotchi />

      {/* Main content */}
      <main className="lg:ml-64 min-h-screen">
        {children}
      </main>
    </div>
  );
}
