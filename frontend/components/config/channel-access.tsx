'use client';

import { useEffect, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ShieldCheck, Trash2, UserPlus } from 'lucide-react';
import { toast } from 'sonner';
import { useAPI, useIsAuthenticated } from '@/hooks/use-api';
import { ConfigSection } from './primitives';

type Level = 'none' | 'basic' | 'custom';
interface ChannelConf { mode: 'public' | 'whitelist'; owners: string[]; guest: { level: Level; tools: string[] } }
interface ChatConf { level: 'blocked' | Level | 'owner'; tools: string[] }
interface Unknown { channel: string; user_id: string; chat_id: string; last: number; count: number; talked: boolean }
type Draft = { channels: Record<string, ChannelConf>; chats: Record<string, ChatConf> };
interface Data {
  channels: Record<string, ChannelConf>;
  chats: Record<string, ChatConf>;
  grantable: string[];
  unknown: Unknown[];
}

const CHANNELS: { id: string; label: string }[] = [
  { id: 'telegram', label: 'Telegram' },
  { id: 'whatsapp', label: 'WhatsApp' },
  { id: 'discord', label: 'Discord' },
];
const LEVEL_LABEL: Record<string, string> = {
  none: 'Solo conversar (sin herramientas)',
  basic: 'Básico (puede buscar en la web)',
  custom: 'Personalizado',
};
const CHAT_LABEL: Record<string, string> = {
  blocked: 'Bloqueado', none: 'Solo conversar', basic: 'Básico (web)', custom: 'Personalizado', owner: 'Confianza total (como tú)',
};

const input: React.CSSProperties = {
  background: 'var(--acm-base)', color: 'var(--acm-fg)', border: '1px solid var(--acm-border)',
  borderRadius: 8, padding: '7px 10px', fontSize: 13,
};
const box: React.CSSProperties = {
  border: '1px solid var(--acm-border)', borderRadius: 'var(--acm-radius)', background: 'var(--acm-elev)', padding: 14,
};

function ago(ts: number) {
  const m = Math.round((Date.now() / 1000 - ts) / 60);
  return m < 1 ? 'ahora' : m < 60 ? `hace ${m} min` : `hace ${Math.round(m / 60)} h`;
}

export function ChannelAccessSection() {
  const { fetchAPI } = useAPI();
  const isAuthenticated = useIsAuthenticated();
  const qc = useQueryClient();
  const { data } = useQuery<Data>({
    queryKey: ['channel-access'],
    queryFn: () => fetchAPI('/api/channel-access'),
    enabled: isAuthenticated,
    refetchInterval: 15_000,
  });
  const [draft, setDraft] = useState<{ channels: Record<string, ChannelConf>; chats: Record<string, ChatConf> } | null>(null);
  const [newOwner, setNewOwner] = useState<Record<string, string>>({});
  const [chatKey, setChatKey] = useState('');
  const [chatLevel, setChatLevel] = useState<ChatConf['level']>('basic');

  // Take the saved settings once; later refreshes only update the "recent senders" list
  useEffect(() => {
    if (data && !draft) setDraft({ channels: data.channels, chats: data.chats });
  }, [data, draft]);

  const save = useMutation<unknown, Error, Draft | void>({
    mutationFn: (next) => fetchAPI('/api/channel-access', { method: 'PUT', body: JSON.stringify(next ?? draft) }),
    onSuccess: () => { toast.success('Permisos guardados'); qc.invalidateQueries({ queryKey: ['channel-access'] }); },
    onError: (e) => toast.error(e.message),
  });

  if (!data || !draft) return null;
  const dirty = JSON.stringify(draft) !== JSON.stringify({ channels: data.channels, chats: data.chats });

  const setChannel = (id: string, patch: Partial<ChannelConf>) =>
    setDraft({ ...draft, channels: { ...draft.channels, [id]: { ...draft.channels[id], ...patch } } });
  // Adding or removing an owner is saved at once: it used to wait for the "Guardar permisos" button
  // at the bottom, so people added their ID, never pressed it, and the bot kept treating them as a guest.
  const saveOwners = (id: string, owners: string[]) => {
    const next = { ...draft, channels: { ...draft.channels, [id]: { ...draft.channels[id], owners } } };
    setDraft(next);
    save.mutate(next);
  };
  const addOwner = (id: string, value: string) => {
    const v = value.trim();
    if (!v || draft.channels[id].owners.includes(v)) return;
    saveOwners(id, [...draft.channels[id].owners, v]);
    setNewOwner({ ...newOwner, [id]: '' });
  };

  return (
    <ConfigSection
      id="section-channel-access"
      title="Acceso desde canales externos"
      subtitle="quién puede escribirle al asistente por Telegram, WhatsApp o Discord, y qué puede hacer"
      icon={ShieldCheck}
    >
      <p style={{ fontSize: 12, color: 'var(--acm-fg-3)', lineHeight: 1.6, marginBottom: 14 }}>
        El panel y la consola son tuyos y nunca se limitan. Cada persona de un canal externo es <b>propietario</b> (todo),
        <b> invitado</b> (solo lo que elijas aquí) o queda <b>bloqueada</b>. A un invitado nunca se le pueden dar comandos,
        archivos, correo ni configuración, y no ve tu memoria ni tus datos.
      </p>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        {CHANNELS.map(({ id, label }) => {
          const c = draft.channels[id];
          if (!c) return null;
          return (
            <div key={id} style={box}>
              <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 10 }}>{label}</div>

              <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap', marginBottom: 10, fontSize: 13 }}>
                <label style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                  <input type="radio" name={`mode-${id}`} checked={c.mode === 'whitelist'} onChange={() => setChannel(id, { mode: 'whitelist' })} />
                  Solo lista de permitidos <span style={{ color: 'var(--acm-fg-4)' }}>(el resto es ignorado)</span>
                </label>
                <label style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                  <input type="radio" name={`mode-${id}`} checked={c.mode === 'public'} onChange={() => setChannel(id, { mode: 'public' })} />
                  Público <span style={{ color: 'var(--acm-fg-4)' }}>(cualquiera puede escribir como invitado)</span>
                </label>
              </div>

              <div className="label" style={{ marginBottom: 6 }}>Propietarios (todo permitido)</div>
              <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 8 }}>
                {c.owners.length === 0 && <span style={{ fontSize: 12, color: 'var(--acm-fg-4)' }}>Nadie todavía: ni tú tienes herramientas en este canal. Añade tu id.</span>}
                {c.owners.map((o) => (
                  <span key={o} className="mono" style={{ fontSize: 12, padding: '3px 8px', border: '1px solid var(--acm-border)', borderRadius: 999, display: 'inline-flex', gap: 6, alignItems: 'center' }}>
                    {o}
                    <button aria-label={`Quitar ${o}`} onClick={() => saveOwners(id, c.owners.filter((x) => x !== o))} style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--acm-fg-4)' }}>×</button>
                  </span>
                ))}
                <input
                  className="mono" style={{ ...input, width: 170 }} placeholder="id de usuario" value={newOwner[id] ?? ''}
                  onChange={(e) => setNewOwner({ ...newOwner, [id]: e.target.value })}
                  onKeyDown={(e) => { if (e.key === 'Enter') addOwner(id, newOwner[id] ?? ''); }}
                  aria-label={`Añadir propietario de ${label}`}
                />
                <button className="btn-secondary" onClick={() => addOwner(id, newOwner[id] ?? '')}><UserPlus size={12} /> Añadir</button>
              </div>

              {c.mode === 'public' && (
                <>
                  <div className="label" style={{ margin: '12px 0 6px' }}>Qué puede hacer un invitado</div>
                  <select style={input} value={c.guest.level} onChange={(e) => setChannel(id, { guest: { ...c.guest, level: e.target.value as Level } })} aria-label={`Permisos de invitados en ${label}`}>
                    {Object.entries(LEVEL_LABEL).map(([v, l]) => (<option key={v} value={v}>{l}</option>))}
                  </select>
                  {c.guest.level === 'custom' && (
                    <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', marginTop: 8, fontSize: 13 }}>
                      {data.grantable.map((t) => (
                        <label key={t} style={{ display: 'flex', gap: 5, alignItems: 'center' }}>
                          <input
                            type="checkbox" checked={c.guest.tools.includes(t)}
                            onChange={(e) => setChannel(id, { guest: { ...c.guest, tools: e.target.checked ? [...c.guest.tools, t] : c.guest.tools.filter((x) => x !== t) } })}
                          />
                          <span className="mono">{t}</span>
                        </label>
                      ))}
                    </div>
                  )}
                </>
              )}
            </div>
          );
        })}
      </div>

      <div style={{ ...box, marginTop: 12 }}>
        <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 4 }}>Chats con permisos propios</div>
        <p style={{ fontSize: 12, color: 'var(--acm-fg-4)', marginBottom: 8 }}>
          Para un grupo o un cliente concreto. Sustituye el perfil de invitado solo en ese chat y deja entrar aunque el canal sea de lista cerrada.
        </p>
        {Object.entries(draft.chats).map(([key, conf]) => (
          <div key={key} style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap', padding: '3px 0', fontSize: 12 }}>
            <span className="mono" style={{ flex: 1, minWidth: 140 }}>{key}</span>
            <select style={input} value={conf.level} aria-label={`Nivel de ${key}`}
              onChange={(e) => setDraft({ ...draft, chats: { ...draft.chats, [key]: { ...conf, level: e.target.value as ChatConf['level'] } } })}>
              {Object.entries(CHAT_LABEL).map(([v, l]) => (<option key={v} value={v}>{l}</option>))}
            </select>
            <button className="btn-secondary" aria-label={`Quitar ${key}`}
              onClick={() => { const next = { ...draft.chats }; delete next[key]; setDraft({ ...draft, chats: next }); }}>
              <Trash2 size={12} />
            </button>
          </div>
        ))}
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 8 }}>
          <input className="mono" style={{ ...input, minWidth: 200 }} placeholder="canal:id  (ej. telegram:-100123)" value={chatKey} onChange={(e) => setChatKey(e.target.value)} aria-label="Chat" />
          <select style={input} value={chatLevel} onChange={(e) => setChatLevel(e.target.value as ChatConf['level'])} aria-label="Nivel del chat nuevo">
            {Object.entries(CHAT_LABEL).map(([v, l]) => (<option key={v} value={v}>{l}</option>))}
          </select>
          <button className="btn-secondary" disabled={!chatKey.includes(':')}
            onClick={() => { setDraft({ ...draft, chats: { ...draft.chats, [chatKey.trim()]: { level: chatLevel, tools: [] } } }); setChatKey(''); }}>
            Añadir chat
          </button>
        </div>
      </div>

      {data.unknown.length > 0 && (
        <div style={{ ...box, marginTop: 12 }}>
          <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 4 }}>Escribieron recientemente sin ser propietarios</div>
          <p style={{ fontSize: 12, color: 'var(--acm-fg-4)', marginBottom: 8 }}>¿Eres tú? Pulsa «Soy yo» para darte todos los permisos en ese canal.</p>
          {data.unknown.map((u) => (
            <div key={`${u.channel}:${u.user_id}:${u.chat_id}`} style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap', padding: '3px 0', fontSize: 12 }}>
              <span className="mono" style={{ flex: 1, minWidth: 180 }}>{u.channel} · usuario {u.user_id}{u.chat_id !== u.user_id ? ` · chat ${u.chat_id}` : ''}</span>
              <span style={{ color: 'var(--acm-fg-4)' }}>{u.count} msj · {ago(u.last)} · {u.talked ? 'atendido como invitado' : 'ignorado'}</span>
              <button className="btn-secondary" onClick={() => { if (draft.channels[u.channel]) addOwner(u.channel, u.user_id); }}>Soy yo</button>
            </div>
          ))}
        </div>
      )}

      <div style={{ marginTop: 14, display: 'flex', gap: 10, alignItems: 'center' }}>
        <button className="btn-primary" disabled={!dirty || save.isPending} onClick={() => save.mutate()}>Guardar permisos</button>
        {dirty && <span style={{ fontSize: 12, color: 'var(--acm-accent)', fontWeight: 600 }}>Hay cambios sin guardar: pulsa «Guardar permisos».</span>}
      </div>
    </ConfigSection>
  );
}
