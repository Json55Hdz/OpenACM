'use client';

import { useState } from 'react';
import { AppLayout } from '@/components/layout/app-layout';
import {
  useWebhookConnectors, useWebhookConnectorEvents, useWebhookConnectorMutations,
  type WebhookConnector,
} from '@/hooks/use-webhook-connectors';
import { useAgents } from '@/hooks/use-agents';
import { useAgentFlows } from '@/hooks/use-agent-flows';

type AuthScheme = WebhookConnector['auth_scheme'];

const AUTH_SCHEME_LABELS: Record<AuthScheme, string> = {
  bearer_token: 'Bearer token',
  static_header_secret: 'Header estático',
  hmac_sha256: 'HMAC-SHA256',
};

function NewConnectorForm({ onDone }: { onDone: () => void }) {
  const { create } = useWebhookConnectorMutations();
  const { data: agents } = useAgents();
  const [slug, setSlug] = useState('');
  const [name, setName] = useState('');
  const [authScheme, setAuthScheme] = useState<AuthScheme>('bearer_token');
  const [agentId, setAgentId] = useState<number | null>(null);
  const [flowId, setFlowId] = useState<number | null>(null);
  const [dedupeHeader, setDedupeHeader] = useState('');

  // bearer_token / static_header_secret
  const [headerName, setHeaderName] = useState('Authorization');
  const [secret, setSecret] = useState('');
  // hmac_sha256
  const [timestampHeader, setTimestampHeader] = useState('X-Timestamp');
  const [signatureHeader, setSignatureHeader] = useState('X-Signature');
  const [maxSkewSeconds, setMaxSkewSeconds] = useState('300');

  const { data: flows } = useAgentFlows(agentId ?? 0);

  const authConfig = (): object => {
    if (authScheme === 'bearer_token') return { token: secret, header_name: headerName };
    if (authScheme === 'static_header_secret') return { header_name: headerName, secret };
    return {
      secret, timestamp_header: timestampHeader, signature_header: signatureHeader,
      max_skew_seconds: Number(maxSkewSeconds) || 300,
    };
  };

  const canSubmit = slug.trim() && name.trim() && flowId && secret.trim();

  const submit = () => {
    if (!canSubmit || !flowId) return;
    create.mutate(
      {
        slug: slug.trim(), name: name.trim(), auth_scheme: authScheme,
        auth_config: authConfig(), flow_id: flowId,
        dedupe_header: dedupeHeader.trim() || null,
      } as Omit<WebhookConnector, 'id' | 'created_at' | 'enabled'> & { auth_config: object },
      { onSuccess: onDone },
    );
  };

  return (
    <div className="acm-card" style={{ padding: 16, marginBottom: 16, display: 'flex', flexDirection: 'column', gap: 10 }}>
      <label>Slug (arma la ruta /api/webhooks/&lt;slug&gt;)</label>
      <input className="acm-input w-full" value={slug} onChange={e => setSlug(e.target.value)} placeholder="ej: pagos" />

      <label>Nombre</label>
      <input className="acm-input w-full" value={name} onChange={e => setName(e.target.value)} placeholder="ej: Pagos EEP" />

      <label>Esquema de autenticación</label>
      <select className="acm-input w-full" value={authScheme} onChange={e => setAuthScheme(e.target.value as AuthScheme)}>
        {(Object.keys(AUTH_SCHEME_LABELS) as AuthScheme[]).map(s => (
          <option key={s} value={s}>{AUTH_SCHEME_LABELS[s]}</option>
        ))}
      </select>

      {authScheme !== 'hmac_sha256' ? (
        <>
          <label>Nombre del header</label>
          <input className="acm-input w-full" value={headerName} onChange={e => setHeaderName(e.target.value)} />
          <label>{authScheme === 'bearer_token' ? 'Token' : 'Secreto'}</label>
          <input className="acm-input w-full" type="password" value={secret} onChange={e => setSecret(e.target.value)} />
        </>
      ) : (
        <>
          <label>Secreto compartido</label>
          <input className="acm-input w-full" type="password" value={secret} onChange={e => setSecret(e.target.value)} />
          <label>Header de timestamp</label>
          <input className="acm-input w-full" value={timestampHeader} onChange={e => setTimestampHeader(e.target.value)} />
          <label>Header de firma</label>
          <input className="acm-input w-full" value={signatureHeader} onChange={e => setSignatureHeader(e.target.value)} />
          <label>Tolerancia de reloj (segundos)</label>
          <input className="acm-input w-full" value={maxSkewSeconds} onChange={e => setMaxSkewSeconds(e.target.value)} />
        </>
      )}

      <label>Agente dueño del Flow</label>
      <select
        className="acm-input w-full"
        value={agentId ?? ''}
        onChange={e => { setAgentId(e.target.value ? Number(e.target.value) : null); setFlowId(null); }}
      >
        <option value="">Seleccionar...</option>
        {(agents || []).map(a => <option key={a.id} value={a.id}>{a.name}</option>)}
      </select>

      <label>Flow a ejecutar</label>
      <select
        className="acm-input w-full"
        value={flowId ?? ''}
        onChange={e => setFlowId(e.target.value ? Number(e.target.value) : null)}
        disabled={!agentId}
      >
        <option value="">Seleccionar...</option>
        {(flows || []).map(f => <option key={f.id} value={f.id}>{f.name}</option>)}
      </select>

      <label>Header de deduplicación (opcional)</label>
      <input className="acm-input w-full" value={dedupeHeader} onChange={e => setDedupeHeader(e.target.value)} placeholder="ej: X-Event-Id" />

      <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 8 }}>
        <button className="btn-secondary" onClick={onDone}>Cancelar</button>
        <button className="btn-secondary" disabled={!canSubmit || create.isPending} onClick={submit}>
          {create.isPending ? 'Creando…' : 'Crear conector'}
        </button>
      </div>
      {create.isError && <p style={{ color: 'var(--acm-danger, #e5484d)' }}>Error al crear el conector.</p>}
    </div>
  );
}

export default function WebhookConnectorsPage() {
  const { data: connectors, isLoading } = useWebhookConnectors();
  const { update, remove } = useWebhookConnectorMutations();
  const [selected, setSelected] = useState<number | null>(null);
  const [showNewForm, setShowNewForm] = useState(false);
  const { data: eventsData } = useWebhookConnectorEvents(selected);

  return (
    <AppLayout>
      <div style={{ padding: 32, maxWidth: 1000, margin: '0 auto' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
          <h1 className="font-bold" style={{ fontSize: 24 }}>Conectores de Webhook</h1>
          {!showNewForm && (
            <button className="btn-secondary" onClick={() => setShowNewForm(true)}>+ Nuevo conector</button>
          )}
        </div>

        {showNewForm && <NewConnectorForm onDone={() => setShowNewForm(false)} />}

        {isLoading ? (
          <p>Cargando…</p>
        ) : (connectors ?? []).length === 0 ? (
          !showNewForm && <p style={{ color: 'var(--acm-fg-4)' }}>No hay conectores todavía.</p>
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
                  <div style={{ display: 'flex', gap: 8 }}>
                    <button
                      className="btn-secondary"
                      onClick={(e) => { e.stopPropagation(); update.mutate({ id: c.id, enabled: c.enabled ? 0 : 1 }); }}
                    >
                      {c.enabled ? 'Apagar' : 'Encender'}
                    </button>
                    <button
                      className="btn-secondary"
                      onClick={(e) => {
                        e.stopPropagation();
                        if (selected === c.id) setSelected(null);
                        remove.mutate(c.id);
                      }}
                    >
                      Eliminar
                    </button>
                  </div>
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
