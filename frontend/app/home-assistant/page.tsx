'use client';

import { useMemo } from 'react';
import { AppLayout } from '@/components/layout/app-layout';
import { useHADevices, useHAScenes, useHAControl, useHAActivateScene, type HAEntity } from '@/hooks/use-home-assistant';
import { usePluginConfig } from '@/hooks/use-plugins';
import { useHAStore } from '@/stores/ha-store';
import { Loader2, Home, Power, ExternalLink } from 'lucide-react';

const DOMAIN_LABELS: Record<string, string> = {
  light: 'Luces',
  switch: 'Enchufes',
  climate: 'Clima',
  cover: 'Cortinas',
  media_player: 'Reproductores',
  vacuum: 'Aspiradoras',
};

const TOGGLEABLE_DOMAINS = new Set(['light', 'switch', 'climate', 'media_player']);
const SIN_AREA = 'Sin área';

export default function HomeAssistantPage() {
  const { data, isLoading, error } = useHADevices();
  const { data: scenesData } = useHAScenes();
  const { data: pluginConfig } = usePluginConfig('home_assistant');
  const liveEntities = useHAStore((s) => s.entities);
  const control = useHAControl();
  const activateScene = useHAActivateScene();

  const haUrl = pluginConfig?.values?.ha_url;

  const entities = useMemo<HAEntity[]>(() => {
    const base = data?.devices ?? [];
    return base.map((e) => ({ ...e, ...liveEntities[e.entity_id] }));
  }, [data, liveEntities]);

  const byArea = useMemo(() => {
    const groups: Record<string, HAEntity[]> = {};
    for (const e of entities) {
      const domain = e.entity_id.split('.')[0];
      if (!DOMAIN_LABELS[domain]) continue;
      const area = e.area || SIN_AREA;
      (groups[area] ??= []).push(e);
    }
    // "Sin área" last, everything else alphabetical
    return Object.fromEntries(
      Object.entries(groups).sort(([a], [b]) => {
        if (a === SIN_AREA) return 1;
        if (b === SIN_AREA) return -1;
        return a.localeCompare(b);
      })
    );
  }, [entities]);

  if (error) {
    return (
      <AppLayout>
        <div style={{ padding: 32, maxWidth: 1100, margin: '0 auto' }}>
          <div className="acm-card flex flex-col items-center justify-center" style={{ padding: '64px 32px', textAlign: 'center' }}>
            <Home size={40} style={{ color: 'var(--acm-fg-4)', marginBottom: 16 }} />
            <h3 className="text-base font-semibold mb-2" style={{ color: 'var(--acm-fg-2)' }}>
              Home Assistant no está configurado
            </h3>
            <p className="text-sm" style={{ color: 'var(--acm-fg-4)' }}>
              Configura la URL y el token desde <span className="mono">/plugins</span>.
            </p>
          </div>
        </div>
      </AppLayout>
    );
  }

  return (
    <AppLayout>
      <div style={{ padding: 32, maxWidth: 1100, margin: '0 auto' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 28, flexWrap: 'wrap', gap: 12 }}>
          <h1 className="font-bold" style={{ fontSize: 24, color: 'var(--acm-fg)' }}>
            Home Assistant
          </h1>
          {haUrl && (
            <a
              href={haUrl}
              target="_blank"
              rel="noopener noreferrer"
              referrerPolicy="no-referrer"
              className="btn-secondary"
              style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}
            >
              <ExternalLink size={14} />
              Abrir Home Assistant completo
            </a>
          )}
        </div>
        <p style={{ fontSize: 13, color: 'var(--acm-fg-4)', marginTop: -18, marginBottom: 24 }}>
          Vistazo rápido y control básico acá — para color, mapas de aspiradora y controles avanzados, usa el dashboard completo de Home Assistant.
        </p>

        {isLoading ? (
          <Loader2 size={24} className="animate-spin" />
        ) : (
          <>
            {Object.entries(byArea).map(([area, devs]) => (
              <div key={area} style={{ marginBottom: 28 }}>
                <h2 className="label" style={{ marginBottom: 12, color: 'var(--acm-fg-3)' }}>
                  {area}
                </h2>
                <div className="grid gap-4" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(240px, 1fr))' }}>
                  {devs.map((e) => {
                    const domain = e.entity_id.split('.')[0];
                    const name = e.attributes?.friendly_name || e.entity_id;
                    const isOn = e.state === 'on';
                    return (
                      <div
                        key={e.entity_id}
                        className="acm-card"
                        style={{ padding: 16, display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 10 }}
                      >
                        <div style={{ minWidth: 0 }}>
                          <div
                            style={{
                              fontWeight: 600, color: 'var(--acm-fg)',
                              overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                            }}
                          >
                            {name}
                          </div>
                          <div style={{ fontSize: 12, color: 'var(--acm-fg-4)' }}>
                            {DOMAIN_LABELS[domain]} · {e.state}
                          </div>
                        </div>
                        {TOGGLEABLE_DOMAINS.has(domain) && (
                          <button
                            className="btn-secondary"
                            style={{ padding: '4px 10px', fontSize: 12, flexShrink: 0 }}
                            onClick={() => control.mutate({ entityId: e.entity_id, action: isOn ? 'turn_off' : 'turn_on' })}
                          >
                            <Power size={13} style={{ color: isOn ? 'var(--acm-accent)' : 'var(--acm-fg-4)' }} />
                          </button>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>
            ))}

            {(scenesData?.scenes ?? []).length > 0 && (
              <div>
                <h2 className="label" style={{ marginBottom: 12, color: 'var(--acm-fg-3)' }}>Escenas</h2>
                <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
                  {scenesData!.scenes.map((s) => (
                    <button key={s.entity_id} className="btn-secondary" onClick={() => activateScene.mutate(s.entity_id)}>
                      {s.attributes?.friendly_name || s.entity_id}
                    </button>
                  ))}
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </AppLayout>
  );
}
