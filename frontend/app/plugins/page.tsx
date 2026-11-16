'use client';

import { useEffect, useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import {
  usePlugins,
  useTogglePlugin,
  usePluginDocs,
  useRestartSystem,
  usePluginNav,
  useInstallPlugin,
  PLUGIN_MARKETPLACE_URL,
} from '@/hooks/use-plugins';
import { PluginConfigForm } from '@/components/plugins/plugin-config-form';
import { PluginUpload } from '@/components/plugins/plugin-upload';
import { AppLayout } from '@/components/layout/app-layout';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Loader2, Puzzle, ExternalLink, Store, ArrowUpRight, Download, ShieldAlert } from 'lucide-react';

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
  const [configOpen, setConfigOpen] = useState<string | null>(null);
  const [showDocs, setShowDocs] = useState(false);
  const [needsRestart, setNeedsRestart] = useState(false);
  const installPlugin = useInstallPlugin();
  const [installUrl, setInstallUrl] = useState('');
  const [confirmSource, setConfirmSource] = useState<string | null>(null);

  // Deep link from the marketplace: /plugins?install=<github repo url>.
  // It only opens the confirmation dialog — nothing is installed without a click here.
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const source = params.get('install');
    if (!source) return;
    setConfirmSource(source.trim());
    params.delete('install');
    const rest = params.toString();
    window.history.replaceState(null, '', window.location.pathname + (rest ? `?${rest}` : ''));
  }, []);

  const closeInstall = () => {
    if (installPlugin.isPending) return;
    setConfirmSource(null);
    installPlugin.reset();
  };

  const runInstall = () => {
    if (!confirmSource) return;
    installPlugin.mutate(confirmSource, {
      onSuccess: () => {
        setNeedsRestart(true);
        setInstallUrl('');
      },
    });
  };

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
      // Embedded inside the app shell (sidebar, header) via the generic
      // /plugins/view route, not a bare new tab — see that page for the iframe.
      router.push(`/plugins/view?name=${encodeURIComponent(pluginName)}`);
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
              onClick={() => window.open(PLUGIN_MARKETPLACE_URL, '_blank', 'noopener,noreferrer')}
              title="Abrir el marketplace de plugins"
            >
              <Store size={14} style={{ marginRight: 6, verticalAlign: -2 }} />
              Marketplace
            </button>
            <button className="btn-secondary" onClick={() => setShowDocs((s) => !s)}>
              {showDocs ? 'Ver plugins' : '¿Cómo creo un plugin?'}
            </button>
          </div>
        </div>

        {!showDocs && (
          <form
            className="acm-card"
            style={{ padding: 16, marginBottom: 20, display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}
            onSubmit={(e) => {
              e.preventDefault();
              const source = installUrl.trim();
              if (!source) return;
              installPlugin.reset();
              setConfirmSource(source);
            }}
          >
            <Download size={16} style={{ color: 'var(--acm-fg-4)', flexShrink: 0 }} />
            <input
              className="mono"
              value={installUrl}
              onChange={(e) => setInstallUrl(e.target.value)}
              placeholder="https://github.com/usuario/plugin"
              aria-label="URL del repositorio del plugin en GitHub"
              style={{
                flex: 1, minWidth: 240, background: 'var(--acm-base)', color: 'var(--acm-fg)',
                border: '1px solid var(--acm-border)', borderRadius: 8, padding: '8px 12px', fontSize: 13,
              }}
            />
            <button type="submit" className="btn-primary" disabled={!installUrl.trim()}>
              Instalar desde GitHub
            </button>
          </form>
        )}

        {!showDocs && <PluginUpload />}

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
              Instala uno desde el marketplace o pega arriba la URL de su repositorio en GitHub.
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
                        <button
                          type="button"
                          className="btn-icon"
                          style={{ background: 'none', border: 'none', padding: 0, cursor: 'pointer', display: 'flex' }}
                          onClick={(e) => { e.stopPropagation(); router.push(`/plugins/view?name=${encodeURIComponent(p.name)}`); }}
                          title="Abrir dashboard del plugin"
                        >
                          <ExternalLink size={15} style={{ color: 'var(--acm-fg-4)' }} />
                        </button>
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

        {confirmSource && (
          <div
            style={{
              position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)',
              display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000, padding: 16,
            }}
            onClick={closeInstall}
          >
            <div
              role="dialog"
              aria-modal="true"
              aria-label="Instalar plugin"
              style={{
                background: 'var(--acm-card)', borderRadius: 12, padding: 28, width: 520, maxWidth: '100%',
                maxHeight: '90vh', overflowY: 'auto',
              }}
              onClick={(e) => e.stopPropagation()}
            >
              <h3 style={{ marginBottom: 12, color: 'var(--acm-fg)' }}>
                {installPlugin.isSuccess ? 'Plugin instalado' : 'Instalar plugin'}
              </h3>
              <div
                className="mono"
                style={{
                  fontSize: 13, color: 'var(--acm-fg)', background: 'var(--acm-base)',
                  border: '1px solid var(--acm-border)', borderRadius: 8, padding: '10px 12px',
                  wordBreak: 'break-all', marginBottom: 14,
                }}
              >
                {confirmSource}
              </div>

              {installPlugin.isSuccess ? (
                <p style={{ fontSize: 13, color: 'var(--acm-fg-3)', marginBottom: 18 }}>
                  Reinicia OpenACM para cargarlo. Si el plugin trae pasos extra (por ejemplo una
                  extensión de navegador), están en el README de su repositorio.
                </p>
              ) : (
                <div style={{ display: 'flex', gap: 10, fontSize: 13, color: 'var(--acm-fg-3)', marginBottom: 18 }}>
                  <ShieldAlert size={18} style={{ color: 'var(--acm-accent)', flexShrink: 0, marginTop: 1 }} />
                  <span>
                    Un plugin es código que se ejecuta con el mismo acceso que OpenACM: tus archivos,
                    tus claves y tu equipo. Instálalo solo si confías en este repositorio.
                  </span>
                </div>
              )}

              {installPlugin.isPending && (
                <p style={{ fontSize: 13, color: 'var(--acm-fg-3)', marginBottom: 18, display: 'flex', alignItems: 'center', gap: 8 }}>
                  <Loader2 size={14} className="animate-spin" />
                  Instalando… puede tardar varios minutos si el plugin tiene dependencias grandes.
                </p>
              )}

              {installPlugin.isError && (
                <div style={{ marginBottom: 18 }}>
                  <p style={{ fontSize: 13, color: 'var(--acm-fg)', marginBottom: 8 }}>
                    {installPlugin.error.message}
                  </p>
                  {installPlugin.error.output && (
                    <pre
                      className="mono"
                      style={{
                        fontSize: 11, color: 'var(--acm-fg-3)', background: 'var(--acm-base)',
                        border: '1px solid var(--acm-border)', borderRadius: 8, padding: 10,
                        maxHeight: 200, overflow: 'auto', whiteSpace: 'pre-wrap', margin: 0,
                      }}
                    >
                      {installPlugin.error.output}
                    </pre>
                  )}
                </div>
              )}

              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 10 }}>
                {installPlugin.isSuccess ? (
                  <>
                    <button className="btn-secondary" onClick={closeInstall}>Cerrar</button>
                    <button
                      className="btn-primary"
                      disabled={restartSystem.isPending}
                      onClick={() => { restartSystem.mutate(); closeInstall(); }}
                    >
                      Reiniciar ahora
                    </button>
                  </>
                ) : (
                  <>
                    <button className="btn-secondary" disabled={installPlugin.isPending} onClick={closeInstall}>
                      Cancelar
                    </button>
                    <button className="btn-primary" disabled={installPlugin.isPending} onClick={runInstall}>
                      {installPlugin.isError ? 'Reintentar' : 'Instalar'}
                    </button>
                  </>
                )}
              </div>
            </div>
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
              style={{
                background: 'var(--acm-card)', borderRadius: 12, padding: 28, width: 480,
                maxHeight: '90vh', overflowY: 'auto',
              }}
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
