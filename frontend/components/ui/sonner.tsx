'use client';

import { Toaster as SonnerToaster } from 'sonner';

export function Toaster() {
  return (
    <SonnerToaster 
      position="top-right" 
      richColors
      toastOptions={{
        style: {
          background: 'var(--bg-secondary)',
          border: '1px solid var(--glass-border)',
          color: 'var(--text-primary)',
        },
      }}
    />
  );
}
