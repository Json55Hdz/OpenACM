'use client';

import { Sidebar } from './sidebar';

export function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen bg-slate-950">
      <Sidebar />
      
      {/* Main content */}
      <main className="lg:ml-64 min-h-screen">
        {children}
      </main>
    </div>
  );
}
