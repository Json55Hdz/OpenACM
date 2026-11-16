'use client';

import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Loader2, Route, Trash2 } from 'lucide-react';
import { toast } from 'sonner';
import { useAPI, useIsAuthenticated } from '@/hooks/use-api';
import { ConfigSection } from './primitives';

interface RoleInfo { id: string; label: string; hint: string }
interface Route { provider: string; model: string }
type RouteMap = Record<string, Route>;
interface Data {
  roles: RoleInfo[];
  global: RouteMap;
  workspaces: Record<string, RouteMap>;
  chats: Record<string, RouteMap>;
  providers: { id: string; default_model: string; configured: boolean }[];
  main: { provider: string; model: string };
}

const inputStyle: React.CSSProperties = {
  background: 'var(--acm-base)', color: 'var(--acm-fg)', border: '1px solid var(--acm-border)',
  borderRadius: 8, padding: '7px 10px', fontSize: 13,
};

function RoleRow({
  role, value, data, onSave, busy,
}: { role: RoleInfo; value?: Route; data: Data; onSave: (r: Route | null) => void; busy: boolean }) {
  const [provider, setProvider] = useState(value?.provider ?? '');
  const [model, setModel] = useState(value?.model ?? '');
  const choose = (p: string) => {
    setProvider(p);
    setModel(data.providers.find((x) => x.id === p)?.default_model ?? '');
  };
  const changed = (value?.provider ?? '') !== provider || (value?.model ?? '') !== model;
  return (
    <div style={{ padding: '10px 0', borderBottom: '1px solid var(--acm-border)' }}>
      <div style={{ fontSize: 13, fontWeight: 600 }}>{role.label}</div>
      <div style={{ fontSize: 12, color: 'var(--acm-fg-4)', marginBottom: 8 }}>{role.hint}</div>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
        <select style={inputStyle} value={provider} onChange={(e) => choose(e.target.value)} aria-label={`Proveedor para ${role.label}`}>
          <option value="">Igual que el modelo principal</option>
          {data.providers.map((p) => (
            <option key={p.id} value={p.id}>{p.id}{p.configured ? '' : ' (sin clave)'}</option>
          ))}
        </select>
        {provider && (
          <input
            className="mono"
            style={{ ...inputStyle, minWidth: 220 }}
            value={model}
            onChange={(e) => setModel(e.target.value)}
            placeholder="modelo (vacío = el del proveedor)"
            aria-label={`Modelo para ${role.label}`}
          />
        )}
        <button
          className="btn-primary"
          disabled={!changed || busy}
          onClick={() => onSave(provider ? { provider, model: model.trim() } : null)}
        >
          Guardar
        </button>
      </div>
    </div>
  );
}

export function ModelRoutesSection() {
  const { fetchAPI } = useAPI();
  const isAuthenticated = useIsAuthenticated();
  const qc = useQueryClient();
  const [scope, setScope] = useState<'global' | 'workspace'>('global');
  const [workspace, setWorkspace] = useState('');

  const { data } = useQuery<Data>({
    queryKey: ['model-routes'],
    queryFn: () => fetchAPI('/api/llm/routes'),
    enabled: isAuthenticated,
  });

  const save = useMutation<unknown, Error, { scope: string; id: string; role: string; route: Route | null }>({
    mutationFn: ({ scope: s, id, role, route }) =>
      fetchAPI('/api/llm/routes', { method: 'PUT', body: JSON.stringify({ scope: s, id, routes: { [role]: route } }) }),
    onSuccess: () => { toast.success('Guardado'); qc.invalidateQueries({ queryKey: ['model-routes'] }); },
    onError: (e) => toast.error(e.message),
  });

  if (!data) return null;
  const wsKey = Object.keys(data.workspaces).find((k) => k === workspace.trim()) ?? '';
  const current: RouteMap = scope === 'global' ? data.global : (wsKey ? data.workspaces[wsKey] : {});
  const scopeId = scope === 'global' ? '' : workspace.trim();

  return (
    <ConfigSection
      id="section-routes"
      title="Modelos por tarea"
      subtitle="usa un modelo distinto para orquestar, para herramientas y para tareas internas"
      icon={Route}
    >
      <p style={{ fontSize: 12, color: 'var(--acm-fg-3)', lineHeight: 1.6, marginBottom: 12 }}>
        Por defecto todo usa el modelo principal ({data.main.provider}/{data.main.model}). Aquí puedes asignar otro a
        cada tipo de trabajo; lo que dejes en «Igual que el modelo principal» no cambia. Orden de prioridad:
        <b> chat</b> (comando <span className="mono">/route</span> dentro del chat) → <b>workspace</b> → <b>global</b>.
        Los agentes y enjambres tienen su propio modelo y no se ven afectados.
      </p>

      <div style={{ display: 'flex', gap: 8, marginBottom: 10, flexWrap: 'wrap' }}>
        <button className={scope === 'global' ? 'btn-primary' : 'btn-secondary'} onClick={() => setScope('global')}>
          Global
        </button>
        <button className={scope === 'workspace' ? 'btn-primary' : 'btn-secondary'} onClick={() => setScope('workspace')}>
          Por workspace
        </button>
        {scope === 'workspace' && (
          <input
            className="mono"
            style={{ ...inputStyle, flex: 1, minWidth: 240 }}
            value={workspace}
            onChange={(e) => setWorkspace(e.target.value)}
            placeholder="Ruta del workspace (la que fijas con /workspace)"
            list="route-workspaces"
          />
        )}
        <datalist id="route-workspaces">
          {Object.keys(data.workspaces).map((w) => (<option key={w} value={w} />))}
        </datalist>
      </div>

      {scope === 'workspace' && !workspace.trim() ? (
        <p style={{ fontSize: 12, color: 'var(--acm-fg-4)' }}>Escribe la ruta de un workspace para configurarlo.</p>
      ) : (
        data.roles.map((role) => (
          <RoleRow
            key={`${scope}:${scopeId}:${role.id}:${current[role.id]?.provider}:${current[role.id]?.model}`}
            role={role}
            value={current[role.id]}
            data={data}
            busy={save.isPending}
            onSave={(route) => save.mutate({ scope, id: scopeId, role: role.id, route })}
          />
        ))
      )}

      {Object.keys(data.chats).length > 0 && (
        <div style={{ marginTop: 14 }}>
          <div style={{ fontSize: 12, color: 'var(--acm-fg-4)', marginBottom: 6 }}>Chats con configuración propia (se cambian con /route)</div>
          {Object.entries(data.chats).map(([key, routes]) => (
            <div key={key} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12, padding: '3px 0' }}>
              <span className="mono" style={{ flex: 1 }}>
                {key}: {Object.entries(routes).map(([r, v]) => `${r}=${v.provider}/${v.model || 'default'}`).join(', ')}
              </span>
              <button
                className="btn-secondary"
                aria-label={`Quitar configuración de ${key}`}
                onClick={() => Object.keys(routes).forEach((r) => save.mutate({ scope: 'chat', id: key, role: r, route: null }))}
              >
                {save.isPending ? <Loader2 size={12} className="animate-spin" /> : <Trash2 size={12} />}
              </button>
            </div>
          ))}
        </div>
      )}
    </ConfigSection>
  );
}
