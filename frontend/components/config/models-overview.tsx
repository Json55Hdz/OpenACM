'use client';

import { useQuery } from '@tanstack/react-query';
import { ArrowRight, Layers } from 'lucide-react';
import { useAPI, useIsAuthenticated } from '@/hooks/use-api';
import { ConfigSection } from './primitives';
import type { NavSection } from './nav';

interface Route { provider: string; model: string }
interface Data {
  roles: { id: string; label: string }[];
  global: Record<string, Route>;
  main: Route;
  fallbacks: Route[];
  providers: { id: string; configured: boolean }[];
}

const cardStyle: React.CSSProperties = {
  flex: '1 1 220px', minWidth: 0, border: '1px solid var(--acm-border)', borderRadius: 'var(--acm-radius)',
  background: 'var(--acm-elev)', padding: 14, display: 'flex', flexDirection: 'column', gap: 8,
};
const linkBtn: React.CSSProperties = {
  alignSelf: 'flex-start', background: 'none', border: 'none', padding: 0, cursor: 'pointer',
  color: 'var(--acm-accent)', fontSize: 12, marginTop: 'auto',
};

const name = (r: Route) => `${r.provider}${r.model ? `/${r.model}` : ''}`;

/** The whole model setup in one glance: who answers, who does what, who covers when one fails. */
export function ModelsOverview({ onGo }: { onGo: (id: NavSection) => void }) {
  const { fetchAPI } = useAPI();
  const isAuthenticated = useIsAuthenticated();
  const { data } = useQuery<Data>({
    queryKey: ['model-routes'],
    queryFn: () => fetchAPI('/api/llm/routes'),
    enabled: isAuthenticated,
  });
  if (!data) return null;

  const customized = data.roles.filter((r) => data.global[r.id]);
  const noKey = data.providers.filter((p) => !p.configured).length;

  return (
    <ConfigSection
      id="section-models-overview"
      title="Modelos: resumen"
      subtitle="cómo está configurada la IA ahora mismo, de un vistazo"
      icon={Layers}
    >
      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'stretch' }}>
        <div style={cardStyle}>
          <span className="label">1 · Responde</span>
          <span className="mono" style={{ fontSize: 14, overflowWrap: 'anywhere' }}>{data.main.model ? name(data.main) : 'Sin configurar'}</span>
          <span style={{ fontSize: 12, color: 'var(--acm-fg-4)' }}>El modelo principal: lo usa todo lo que no tenga otro asignado.</span>
          <button style={linkBtn} onClick={() => onGo('model')}>Cambiar modelo principal →</button>
        </div>

        <ArrowRight size={16} style={{ alignSelf: 'center', color: 'var(--acm-fg-4)', flexShrink: 0 }} className="hidden lg:block" />

        <div style={cardStyle}>
          <span className="label">2 · Por tarea</span>
          {customized.length === 0 ? (
            <span style={{ fontSize: 13 }}>Todo usa el modelo principal.</span>
          ) : (
            customized.map((r) => (
              <span key={r.id} style={{ fontSize: 12 }}>
                <b>{r.label}:</b> <span className="mono">{name(data.global[r.id])}</span>
              </span>
            ))
          )}
          <span style={{ fontSize: 12, color: 'var(--acm-fg-4)' }}>Opcional: otro modelo para orquestar, usar herramientas o tareas internas.</span>
          <button style={linkBtn} onClick={() => onGo('routes')}>Asignar modelos por tarea →</button>
        </div>

        <ArrowRight size={16} style={{ alignSelf: 'center', color: 'var(--acm-fg-4)', flexShrink: 0 }} className="hidden lg:block" />

        <div style={cardStyle}>
          <span className="label">3 · Si falla</span>
          {data.fallbacks.length === 0 ? (
            <span style={{ fontSize: 13, color: 'var(--acm-warn, var(--acm-fg-3))' }}>Sin respaldo: un error del proveedor llega al chat.</span>
          ) : (
            data.fallbacks.map((f, i) => (
              <span key={name(f)} className="mono" style={{ fontSize: 12, overflowWrap: 'anywhere' }}>{i + 1}. {name(f)}</span>
            ))
          )}
          <span style={{ fontSize: 12, color: 'var(--acm-fg-4)' }}>Se prueban en orden cuando el modelo elegido no responde.</span>
          <button style={linkBtn} onClick={() => onGo('fallbacks')}>Configurar respaldo →</button>
        </div>
      </div>

      <p style={{ fontSize: 12, color: 'var(--acm-fg-4)', marginTop: 12 }}>
        Para que un modelo esté disponible, primero conecta su proveedor
        (<a style={{ color: 'var(--acm-accent)', cursor: 'pointer' }} onClick={() => onGo('providers')}>paso A</a>
        {noKey > 0 ? `; ${noKey} proveedores aún sin clave` : ''}).
      </p>
    </ConfigSection>
  );
}
