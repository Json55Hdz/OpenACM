'use client';

import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { AlertTriangle, CheckCircle2, ShieldCheck } from 'lucide-react';
import { useAPI, useIsAuthenticated } from '@/hooks/use-api';

interface Monitor {
  days: number;
  totals: { requests?: number; tokens?: number; cost?: number; errors?: number; failovers?: number };
  models: { provider: string; model: string; requests: number; tokens: number; cost: number; avg_ms: number }[];
  errors_by_provider: { provider: string; errors: number; failovers: number }[];
  errors: { timestamp: string; provider: string; model: string; role: string; error_class: string; message: string; failover_to: string }[];
  health: Record<string, { fails: number; cooling_for_s: number }>;
}

const th: React.CSSProperties = { textAlign: 'left', padding: '6px 10px 6px 0', fontWeight: 500, color: 'var(--acm-fg-4)', fontSize: 11 };
const td: React.CSSProperties = { padding: '6px 10px 6px 0', fontSize: 12 };

function Tile({ label, value, warn }: { label: string; value: string; warn?: boolean }) {
  return (
    <div className="acm-card" style={{ padding: 12, flex: '1 1 130px', minWidth: 120 }}>
      <div style={{ fontSize: 11, color: 'var(--acm-fg-4)' }}>{label}</div>
      <div className="mono" style={{ fontSize: 18, color: warn ? 'var(--acm-err)' : 'var(--acm-fg)' }}>{value}</div>
    </div>
  );
}

/** Models: what was spent, what failed, and which providers are being skipped right now. */
export function LlmHealthPanel() {
  const { fetchAPI } = useAPI();
  const isAuthenticated = useIsAuthenticated();
  const [days, setDays] = useState(7);
  const { data } = useQuery<Monitor>({
    queryKey: ['llm-monitor', days],
    queryFn: () => fetchAPI(`/api/llm/monitor?days=${days}`),
    enabled: isAuthenticated,
    refetchInterval: 30_000,
  });
  if (!data) return null;

  const cooling = Object.entries(data.health ?? {}).filter(([, h]) => h.cooling_for_s > 0);
  const t = data.totals ?? {};

  return (
    <div style={{ marginTop: 32 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap', marginBottom: 12 }}>
        <div style={{ flex: 1, minWidth: 200 }}>
          <div style={{ fontSize: 15, fontWeight: 600 }}>Modelos: costos y errores</div>
          <div style={{ fontSize: 12, color: 'var(--acm-fg-4)' }}>Qué se gastó, qué falló y cuándo se usó un respaldo.</div>
        </div>
        {[1, 7, 30].map((d) => (
          <button key={d} className={days === d ? 'btn-primary' : 'btn-secondary'} onClick={() => setDays(d)}>
            {d === 1 ? '24 h' : `${d} días`}
          </button>
        ))}
      </div>

      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 12 }}>
        <Tile label="Llamadas" value={String(t.requests ?? 0)} />
        <Tile label="Costo" value={`$${(t.cost ?? 0).toFixed(2)}`} />
        <Tile label="Errores" value={String(t.errors ?? 0)} warn={(t.errors ?? 0) > 0} />
        <Tile label="Respaldos usados" value={String(t.failovers ?? 0)} />
      </div>

      {cooling.length > 0 ? (
        <div className="acm-card" style={{ padding: 12, marginBottom: 12, borderColor: 'var(--acm-err)' }}>
          {cooling.map(([provider, h]) => (
            <div key={provider} style={{ fontSize: 13, display: 'flex', gap: 8, alignItems: 'center' }}>
              <AlertTriangle size={14} style={{ color: 'var(--acm-err)', flexShrink: 0 }} />
              <span>
                <b>{provider}</b> falló {h.fails} {h.fails === 1 ? 'vez' : 'veces'} seguidas: se omite
                durante {h.cooling_for_s} s y se usa el siguiente modelo de respaldo.
              </span>
            </div>
          ))}
        </div>
      ) : (
        <div style={{ fontSize: 12, color: 'var(--acm-ok)', marginBottom: 12, display: 'flex', gap: 6, alignItems: 'center' }}>
          <ShieldCheck size={14} /> Todos los proveedores responden con normalidad.
        </div>
      )}

      <div className="acm-card" style={{ padding: 12, marginBottom: 12, overflowX: 'auto' }}>
        <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 6 }}>Por modelo</div>
        {data.models.length === 0 ? (
          <div style={{ fontSize: 12, color: 'var(--acm-fg-4)' }}>Sin llamadas en este período.</div>
        ) : (
          <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: 460 }}>
            <thead>
              <tr><th style={th}>Modelo</th><th style={th}>Llamadas</th><th style={th}>Tokens</th><th style={th}>Costo</th><th style={th}>Velocidad</th></tr>
            </thead>
            <tbody>
              {data.models.map((m) => (
                <tr key={`${m.provider}/${m.model}`}>
                  <td className="mono" style={td}>{m.provider ? `${m.provider}/` : ''}{m.model}</td>
                  <td style={td}>{m.requests}</td>
                  <td style={td}>{m.tokens.toLocaleString()}</td>
                  <td style={td}>${m.cost.toFixed(3)}</td>
                  <td style={td}>{(m.avg_ms / 1000).toFixed(1)} s</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div className="acm-card" style={{ padding: 12, overflowX: 'auto' }}>
        <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 6 }}>Errores recientes</div>
        {data.errors.length === 0 ? (
          <div style={{ fontSize: 12, color: 'var(--acm-ok)' }}>
            <CheckCircle2 size={13} style={{ verticalAlign: -2 }} /> Ningún error en este período.
          </div>
        ) : (
          <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: 520 }}>
            <thead>
              <tr><th style={th}>Hora</th><th style={th}>Modelo</th><th style={th}>Error</th><th style={th}>Respaldo</th></tr>
            </thead>
            <tbody>
              {data.errors.map((e, i) => (
                <tr key={i} style={{ verticalAlign: 'top' }}>
                  <td className="mono" style={td}>{new Date(e.timestamp).toLocaleString()}</td>
                  <td className="mono" style={td}>{e.provider}/{e.model}{e.role ? ` (${e.role})` : ''}</td>
                  <td style={{ ...td, wordBreak: 'break-word' }}>{e.error_class}: {e.message}</td>
                  <td className="mono" style={td}>{e.failover_to || 'ninguno'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
