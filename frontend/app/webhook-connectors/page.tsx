'use client';

import { useState } from 'react';
import { AppLayout } from '@/components/layout/app-layout';
import {
  useWebhookConnectors, useWebhookConnectorEvents, useWebhookConnectorMutations,
  type WebhookConnector,
} from '@/hooks/use-webhook-connectors';

export default function WebhookConnectorsPage() {
  const { data: connectors, isLoading } = useWebhookConnectors();
  const { update } = useWebhookConnectorMutations();
  const [selected, setSelected] = useState<number | null>(null);
  const { data: eventsData } = useWebhookConnectorEvents(selected);

  return (
    <AppLayout>
      <div style={{ padding: 32, maxWidth: 1000, margin: '0 auto' }}>
        <h1 className="font-bold" style={{ fontSize: 24, marginBottom: 20 }}>Conectores de Webhook</h1>
        {isLoading ? (
          <p>Cargando…</p>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {(connectors ?? []).map((c: WebhookConnector) => (
              <div
                key={c.id}
                className="acm-card"
                style={{ padding: 16, cursor: 'pointer' }}
                onClick={() => setSelected(c.id)}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <div>
                    <strong>{c.name}</strong>
                    <div className="mono" style={{ fontSize: 12, color: 'var(--acm-fg-4)' }}>
                      /api/webhooks/{c.slug} · {c.auth_scheme}
                    </div>
                  </div>
                  <button
                    className="btn-secondary"
                    onClick={(e) => { e.stopPropagation(); update.mutate({ id: c.id, enabled: c.enabled ? 0 : 1 }); }}
                  >
                    {c.enabled ? 'Apagar' : 'Encender'}
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}

        {selected && eventsData && (
          <div style={{ marginTop: 24 }}>
            <h2 style={{ fontSize: 16, marginBottom: 8 }}>
              Actividad — total {eventsData.stats.total}
            </h2>
            <table style={{ width: '100%', fontSize: 13 }}>
              <tbody>
                {eventsData.events.map((e) => (
                  <tr key={e.id}>
                    <td>{e.received_at}</td>
                    <td>{e.status}</td>
                    <td>{e.result}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </AppLayout>
  );
}
