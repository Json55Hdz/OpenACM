'use client';

import { useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import { toast } from 'sonner';
import {
  usePlugins,
  useTogglePlugin,
  usePluginDocs,
  useRestartSystem,
  usePluginNav,
} from '@/hooks/use-plugins';
import { PluginConfigForm } from '@/components/plugins/plugin-config-form';
import { useAuthStore } from '@/stores/auth-store';
import { AppLayout } from '@/components/layout/app-layout';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Loader2, Puzzle, ExternalLink, Store, ArrowUpRight } from 'lucide-react';

function ToggleSwitch({ checked, onChange }: { checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      onClick={(e) => {
        e.stopPropagation();
        onChange(!checked);
      }}
      style={{
        width: 36,
        height: 20,
        borderRadius: 999,
        border: 'none',
        padding: 2,
        cursor: 'pointer',
        background: checked ? 'var(--acm-accent)' : 'var(--acm-border)',
        transition: 'background 160ms ease',
        flexShrink: 0,
      }}
    >
      <span
        style={{
          display: 'block',
          width: 16,
          height: 16,
          borderRadius: '50%',
          background: 'var(--acm-base)',
          transform: checked ? 'translateX(16px)' : 'translateX(0)',
          transition: 'transform 160ms ease',
        }}
      />
    </button>
  );
}

export default function PluginsPage() {
  const router = useRouter();
  const { data: plugins, isLoading } = usePlugins();
  const { data: navItems } = usePluginNav();
  const togglePlugin = useTogglePlugin();
  const restartSystem = useRestartSystem();
  const token = useAuthStore((s) => s.token);
  const [configOpen, setConfigOpen] = useState<string | null>(null);
  const [showDocs, setShowDocs] = useState(false);
  const [needsRestart, setNeedsRestart] = useState(false);

  // First nav route each plugin contributes, if any — lets a card link
  // straight to the plugin's own page instead of just showing metadata.
  const pluginRoutes = useMemo(() => {
    const map: Record<string, string> = {};
    for (const item of navItems ?? []) {
      if (!(item.plugin in map)) map[item.plugin] = item.path;
    }
    return map;
  }, [navItems]);

  const handleToggle = (name: string, enabled: boolean) => {
    togglePlugin.mutate({ name, enabled });
    setNeedsRestart(true);
  };

  const handleCardClick = (pluginName: string, hasCustomUi: boolean) => {
    const route = pluginRoutes[pluginName];
    if (route) {
      router.push(route);
    } else if (hasCustomUi) {
      // window.open's windowFeatures 'noreferrer' token isn't reliably honored
      // across browsers — a real <a referrerPolicy="no-referrer"> click is the
      // only cross-browser way to suppress the Referer header for a
      // token-bearing URL, matching the visible link below.
      const a = document.createElement('a');
      a.href = `/api/plugins/${pluginName}/ui?token=${encodeURIComponent(token ?? '')}`;
      a.target = '_blank';
      a.rel = 'noopener noreferrer';
      a.referrerPolicy = 'no-referrer';
      a.click();
    }
  };

  return (
    <AppLayout>
      <div style={{ padding: 32, maxWidth: 1100, margin: '0 auto' }}>
        <div style={{ display: 'flex', alignItems: 'flex-end', justifyContent: 'space-between', marginBottom: 28, gap: 16, flexWrap: 'wrap' }}>
          <div>
            <h1 className="font-bold" style={{ fontSize: 24, color: 'var(--acm-fg)' }}>Plugins</h1>
            <p style={{ fontSize: 13, color: 'var(--acm-fg-4)', marginTop: 4 }}>
              {isLoading ? 'Cargando…' : `${plugins?.length ?? 0} instalados`}
            </p>
          </div>
          <div style={{ display: 'flex', gap: 10 }}>
            <button
              className="btn-secondary"
              onClick={() => toast.info('Marketplace de plugins — próximamente')}
            >
              <Store size={14} style={{ marginRight: 6, verticalAlign: -2 }} />
              Marketplace
            </button>
            <button className="btn-secondary" onClick={() => setShowDocs((s) => !s)}>
              {showDocs ? 'Ver plugins' : '¿Cómo creo un plugin?'}
            </button>
          </div>
        </div>

        {needsRestart && (
          <div
            style={{
              display: 'flex', alignItems: 'center', justifyContent: 'space-between',
              background: 'var(--acm-accent-soft)', border: '1px solid oklch(0.84 0.16 82 / 0.18)',
              borderRadius: 8, padding: '10px 16px', marginBottom: 20, fontSize: 13,
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
          <div className="grid gap-4" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))' }}>
            {[1, 2, 3].map((i) => (
              <div key={i} className="acm-card" style={{ height: 160, opacity: 0.4, animation: 'acm-pulse 1.8s ease-in-out infinite' }} />
            ))}
          </div>
        ) : (plugins ?? []).length === 0 ? (
          <div className="acm-card flex flex-col items-center justify-center" style={{ padding: '64px 32px', textAlign: 'center' }}>
            <Puzzle size={40} style={{ color: 'var(--acm-fg-4)', marginBottom: 16 }} />
            <h3 className="text-base font-semibold mb-2" style={{ color: 'var(--acm-fg-2)' }}>Sin plugins instalados</h3>
            <p className="text-sm" style={{ color: 'var(--acm-fg-4)' }}>
              Los plugins se cargan automáticamente desde <span className="mono">src/openacm/plugins/</span>.
            </p>
          </div>
        ) : (
          <div className="grid gap-4" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))' }}>
            {(plugins ?? []).map((p) => {
              const clickable = Boolean(pluginRoutes[p.name] || p.has_custom_ui);
              return (
                <div
                  key={p.name}
                  className="acm-card"
                  onClick={clickable ? () => handleCardClick(p.name, p.has_custom_ui) : undefined}
                  style={{
                    padding: 20,
                    display: 'flex',
                    flexDirection: 'column',
                    gap: 14,
                    cursor: clickable ? 'pointer' : 'default',
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 12, minWidth: 0 }}>
                      <div
                        style={{
                          width: 36, height: 36, borderRadius: 9, flexShrink: 0,
                          background: 'var(--acm-accent-soft)',
                          display: 'flex', alignItems: 'center', justifyContent: 'center',
                        }}
                      >
                        <Puzzle size={17} style={{ color: 'var(--acm-accent)' }} />
                      </div>
                      <div style={{ minWidth: 0 }}>
                        <div style={{ fontWeight: 600, color: 'var(--acm-fg)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                          {p.name}
                        </div>
                        <div className="mono" style={{ fontSize: 11, color: 'var(--acm-fg-4)' }}>v{p.version}</div>
                      </div>
                    </div>
                    {clickable && <ArrowUpRight size={16} style={{ color: 'var(--acm-fg-4)', flexShrink: 0 }} />}
                  </div>

                  <p
                    style={{
                      fontSize: 13, color: 'var(--acm-fg-3)', margin: 0, flex: 1,
                      display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden',
                    }}
                  >
                    {p.description || 'Sin descripción.'}
                  </p>

                  <div
                    style={{
                      display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                      paddingTop: 12, borderTop: '1px solid var(--acm-border)',
                    }}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                      <ToggleSwitch checked={p.enabled} onChange={(v) => handleToggle(p.name, v)} />
                      <span style={{ fontSize: 12, color: p.enabled ? 'var(--acm-fg-2)' : 'var(--acm-fg-4)' }}>
                        {p.enabled ? 'Activo' : 'Desactivado'}
                      </span>
                    </div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                      {p.has_custom_ui && (
                        <a
                          href={`/api/plugins/${p.name}/ui?token=${encodeURIComponent(token ?? '')}`}
                          target="_blank"
                          rel="noopener noreferrer"
                          referrerPolicy="no-referrer"
                          onClick={(e) => e.stopPropagation()}
                          title="Abrir vista completa"
                        >
                          <ExternalLink size={15} style={{ color: 'var(--acm-fg-4)' }} />
                        </a>
                      )}
                      {p.has_config_schema && (
                        <button
                          className="btn-secondary"
                          style={{ padding: '4px 10px', fontSize: 12 }}
                          onClick={(e) => { e.stopPropagation(); setConfigOpen(p.name); }}
                        >
                          Configurar
                        </button>
                      )}
                    </div>
                  </div>
                </div>
              );
            })}
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
