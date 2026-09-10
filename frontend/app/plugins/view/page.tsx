'use client';

import { Suspense } from 'react';
import { useSearchParams } from 'next/navigation';
import { AppLayout } from '@/components/layout/app-layout';
import { useAuthStore } from '@/stores/auth-store';

// Generic embed for any plugin's has_custom_ui() escape hatch — renders it
// inside the app shell (sidebar, header) rather than the bare new-tab HTML
// page the /api/plugins/{name}/ui link previously opened directly. Uses a
// query param (not a dynamic route segment) since the frontend is a static
// `output: export` build with no server to resolve arbitrary plugin names
// at build time — the SPA catch-all in server.py serves this same page for
// any /plugins/view URL and the plugin name is read client-side.
const SAFE_PLUGIN_NAME = /^[a-zA-Z0-9_-]+$/;

function PluginCustomUiView() {
  const searchParams = useSearchParams();
  const rawName = searchParams.get('name') ?? '';
  const name = SAFE_PLUGIN_NAME.test(rawName) ? rawName : '';
  const token = useAuthStore((s) => s.token);

  if (!name) {
    return <div style={{ padding: 32, color: 'var(--acm-fg-4)' }}>Plugin inválido.</div>;
  }

  return (
    <iframe
      src={`/api/plugins/${encodeURIComponent(name)}/ui?token=${encodeURIComponent(token ?? '')}`}
      title={`Vista de ${name}`}
      style={{ width: '100%', height: '100vh', border: 'none', display: 'block' }}
    />
  );
}

export default function PluginCustomUiPage() {
  return (
    <AppLayout>
      <Suspense fallback={null}>
        <PluginCustomUiView />
      </Suspense>
    </AppLayout>
  );
}
