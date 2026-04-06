'use client';

import { Sidebar } from './Sidebar';
import { useWebSocket } from '@/hooks/use-websocket';

// WebSocket is initialized here (app root) so it stays alive across all page
// navigations. Tool calls, thinking status, and skill events are captured even
// when the user is not on the /chat page.
function GlobalWebSocket() {
  useWebSocket();
  return null;
}

export function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen bg-slate-950">
      <GlobalWebSocket />
      <Sidebar />

      {/* Main content */}
      <main className="lg:ml-64 min-h-screen">
        {children}
      </main>
    </div>
  );
}
