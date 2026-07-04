'use client';

import { useMemo } from 'react';
import { AppLayout } from '@/components/layout/app-layout';
import { useHADevices, useHAScenes, useHAControl, useHAActivateScene, type HAEntity } from '@/hooks/use-home-assistant';
import { useHAStore } from '@/stores/ha-store';
import { Loader2, Home, Power } from 'lucide-react';

const DOMAIN_LABELS: Record<string, string> = {
  light: 'Luces',
  switch: 'Enchufes',
  climate: 'Clima',
  cover: 'Cortinas',
  media_player: 'Reproductores',
  vacuum: 'Aspiradoras',
};

const TOGGLEABLE_DOMAINS = new Set(['light', 'switch', 'climate', 'media_player']);

export default function HomeAssistantPage() {
  const { data, isLoading, error } = useHADevices();
  const { data: scenesData } = useHAScenes();
  const liveEntities = useHAStore((s) => s.entities);
  const control = useHAControl();
  const activateScene = useHAActivateScene();

  const entities = useMemo<HAEntity[]>(() => {
    const base = data?.devices ?? [];
    return base.map((e) => liveEntities[e.entity_id] ?? e);
  }, [data, liveEntities]);

  const byDomain = useMemo(() => {
    const groups: Record<string, HAEntity[]> = {};
    for (const e of entities) {
      const domain = e.entity_id.split('.')[0];
      if (!DOMAIN_LABELS[domain]) continue;
      (groups[domain] ??= []).push(e);
    }
    return groups;
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
        <h1 className="font-bold" style={{ fontSize: 24, color: 'var(--acm-fg)', marginBottom: 28 }}>
          Home Assistant
        </h1>

        {isLoading ? (
          <Loader2 size={24} className="animate-spin" />
        ) : (
          <>
            {Object.entries(byDomain).map(([domain, devs]) => (
              <div key={domain} style={{ marginBottom: 28 }}>
                <h2 className="label" style={{ marginBottom: 12, color: 'var(--acm-fg-3)' }}>
                  {DOMAIN_LABELS[domain]}
                </h2>
                <div className="grid gap-4" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(240px, 1fr))' }}>
                  {devs.map((e) => {
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
                          <div style={{ fontSize: 12, color: 'var(--acm-fg-4)' }}>{e.state}</div>
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
