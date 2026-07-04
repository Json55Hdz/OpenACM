'use client';

import { useState } from 'react';
import { usePlugins, useTogglePlugin, usePluginDocs, useRestartSystem } from '@/hooks/use-plugins';
import { PluginConfigForm } from '@/components/plugins/plugin-config-form';
import { useAuthStore } from '@/stores/auth-store';
import { AppLayout } from '@/components/layout/app-layout';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Loader2, Puzzle, ExternalLink } from 'lucide-react';

export default function PluginsPage() {
  const { data: plugins, isLoading } = usePlugins();
  const togglePlugin = useTogglePlugin();
  const restartSystem = useRestartSystem();
  const token = useAuthStore((s) => s.token);
  const [configOpen, setConfigOpen] = useState<string | null>(null);
  const [showDocs, setShowDocs] = useState(false);
  const [needsRestart, setNeedsRestart] = useState(false);

  const handleToggle = (name: string, enabled: boolean) => {
    togglePlugin.mutate({ name, enabled });
    setNeedsRestart(true);
  };

  return (
    <AppLayout>
      <div style={{ padding: 32, maxWidth: 900 }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 24 }}>
          <h1 className="font-bold" style={{ fontSize: 24, color: 'var(--acm-fg)' }}>Plugins</h1>
          <button className="btn-secondary" onClick={() => setShowDocs((s) => !s)}>
            {showDocs ? 'Ver plugins' : '¿Cómo creo un plugin?'}
          </button>
        </div>
  
        {needsRestart && (
          <div
            style={{
              display: 'flex', alignItems: 'center', justifyContent: 'space-between',
              background: 'var(--acm-accent-soft)', border: '1px solid oklch(0.84 0.16 82 / 0.18)',
              borderRadius: 8, padding: '10px 16px', marginBottom: 16, fontSize: 13,
            }}
          >
            <span>Reinicia el contenedor para aplicar los cambios de plugins.</span>
            <button
              className="btn-primary"
              disabled={restartSystem.isPending}
              onClick={() => restartSystem.mutate()}
            >
              {restartSystem.isPending ? <Loader2 size={14} className="animate-spin" /> : 'Reiniciar ahora'}
            </button>
          </div>
        )}
  
        {showDocs ? (
          <PluginDocsViewer />
        ) : isLoading ? (
          <Loader2 size={24} className="animate-spin" />
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            {(plugins ?? []).map((p) => (
              <div
                key={p.name}
                style={{
                  background: 'var(--acm-card)',
                  border: '1px solid var(--acm-border)',
                  borderRadius: 10,
                  padding: 20,
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                  <Puzzle size={18} style={{ color: 'var(--acm-accent)' }} />
                  <div>
                    <div style={{ fontWeight: 600, color: 'var(--acm-fg)' }}>
                      {p.name} <span style={{ fontSize: 12, color: 'var(--acm-fg-4)' }}>v{p.version}</span>
                    </div>
                    <div style={{ fontSize: 13, color: 'var(--acm-fg-3)' }}>{p.description}</div>
                  </div>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                  {p.has_custom_ui && (
                    <a
                      href={`/api/plugins/${p.name}/ui?token=${encodeURIComponent(token ?? '')}`}
                      target="_blank"
                      rel="noopener noreferrer"
                      referrerPolicy="no-referrer"
                    >
                      <ExternalLink size={16} style={{ color: 'var(--acm-fg-4)' }} />
                    </a>
                  )}
                  {p.has_config_schema && (
                    <button className="btn-secondary" onClick={() => setConfigOpen(p.name)}>
                      Configurar
                    </button>
                  )}
                  <label style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                    <input
                      type="checkbox"
                      checked={p.enabled}
                      onChange={(e) => handleToggle(p.name, e.target.checked)}
                    />
                    {p.enabled ? 'Activo' : 'Desactivado'}
                  </label>
                </div>
              </div>
            ))}
          </div>
        )}
  
        {configOpen && (
          <div
            style={{
              position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)',
              display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000,
            }}
            onClick={() => setConfigOpen(null)}
          >
            <div
              style={{ background: 'var(--acm-card)', borderRadius: 12, padding: 28, width: 480 }}
              onClick={(e) => e.stopPropagation()}
            >
              <h3 style={{ marginBottom: 16, color: 'var(--acm-fg)' }}>Configurar {configOpen}</h3>
              <PluginConfigForm pluginName={configOpen} onSaved={() => setConfigOpen(null)} />
            </div>
          </div>
        )}
      </div>
    </AppLayout>
  );
}

function PluginDocsViewer() {
  const { data: markdown, isLoading } = usePluginDocs();
  if (isLoading) return <Loader2 size={24} className="animate-spin" />;
  return (
    <div className="mono" style={{ color: 'var(--acm-fg-2)', lineHeight: 1.7 }}>
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{markdown ?? ''}</ReactMarkdown>
    </div>
  );
}
