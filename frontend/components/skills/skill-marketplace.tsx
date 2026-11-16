'use client';

import { useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { AlertTriangle, Check, Download, Link2, Loader2, Search, ShieldAlert, Store, Upload, X } from 'lucide-react';
import { toast } from 'sonner';
import { useAPI, useIsAuthenticated } from '@/hooks/use-api';

interface CatalogItem {
  name: string; description: string; category: string; author: string; url: string; sha256: string; installed: boolean;
}
interface Catalog { catalog_url: string; skills: CatalogItem[]; error: string }
interface Preview {
  name: string; description: string; category: string; author: string; content: string; raw: string; sha256: string;
  findings: { level: 'high' | 'warn'; message: string; snippet?: string }[];
  risky: boolean; already_installed: boolean; size: number;
}

const box: React.CSSProperties = {
  background: 'var(--acm-card)', border: '1px solid var(--acm-border)', borderRadius: 'var(--acm-radius)', padding: 16,
};
const input: React.CSSProperties = {
  background: 'var(--acm-base)', color: 'var(--acm-fg)', border: '1px solid var(--acm-border)',
  borderRadius: 8, padding: '8px 10px', fontSize: 13,
};

export function SkillMarketplace() {
  const { fetchAPI } = useAPI();
  const isAuthenticated = useIsAuthenticated();
  const qc = useQueryClient();
  const fileRef = useRef<HTMLInputElement>(null);
  const [query, setQuery] = useState('');
  const [link, setLink] = useState('');
  const [pasted, setPasted] = useState('');
  const [preview, setPreview] = useState<Preview | null>(null);
  const [typed, setTyped] = useState('');

  const { data, isLoading } = useQuery<Catalog>({
    queryKey: ['skills-marketplace'],
    queryFn: () => fetchAPI('/api/skills/marketplace'),
    enabled: isAuthenticated,
    staleTime: 60_000,
  });

  const read = useMutation<Preview, Error, { url?: string; sha256?: string; content?: string }>({
    mutationFn: (body) => fetchAPI('/api/skills/market/preview', { method: 'POST', body: JSON.stringify(body) }),
    onSuccess: (p) => { setPreview(p); setTyped(''); },
    onError: (e) => toast.error(e.message),
  });

  const install = useMutation<unknown, Error, Preview>({
    mutationFn: (p) =>
      fetchAPI('/api/skills/market/install', {
        method: 'POST',
        body: JSON.stringify({ content: p.raw, sha256: p.sha256, confirm_name: typed }),
      }),
    onSuccess: () => {
      toast.success('Skill instalada');
      setPreview(null); setLink(''); setPasted('');
      qc.invalidateQueries({ queryKey: ['skills'] });
      qc.invalidateQueries({ queryKey: ['skills-marketplace'] });
    },
    onError: (e) => toast.error(e.message),
  });

  const items = (data?.skills ?? []).filter((s) =>
    `${s.name} ${s.description} ${s.category}`.toLowerCase().includes(query.toLowerCase()),
  );

  const onFile = async (file: File | undefined) => {
    if (!file) return;
    if (file.size > 80_000) { toast.error('El archivo es demasiado grande (máx. 60 KB).'); return; }
    read.mutate({ content: await file.text() });
    if (fileRef.current) fileRef.current.value = '';
  };

  return (
    <section id="skill-marketplace" style={{ marginTop: 36 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 6 }}>
        <Store size={18} style={{ color: 'var(--acm-accent)' }} />
        <h2 style={{ fontSize: 18, fontWeight: 700 }}>Marketplace de skills</h2>
      </div>
      <p style={{ fontSize: 13, color: 'var(--acm-fg-3)', marginBottom: 14, lineHeight: 1.6 }}>
        Skills hechas por la comunidad. Una skill es un documento con instrucciones que el asistente lee: no ejecuta código,
        pero sí lo guía, así que antes de instalar siempre ves su contenido completo y una revisión de señales de riesgo.
      </p>

      <div style={{ ...box, marginBottom: 14 }}>
        <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 8 }}>Instalar desde un enlace o un archivo</div>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 8 }}>
          <input
            style={{ ...input, flex: 1, minWidth: 240 }} value={link} onChange={(e) => setLink(e.target.value)}
            placeholder="https://raw.githubusercontent.com/usuario/repo/main/mi-skill.md"
            aria-label="Enlace de la skill"
          />
          <button className="btn-secondary" disabled={!link.trim() || read.isPending} onClick={() => read.mutate({ url: link.trim() })}>
            <Link2 size={13} /> Revisar enlace
          </button>
          <button className="btn-secondary" disabled={read.isPending} onClick={() => fileRef.current?.click()}>
            <Upload size={13} /> Subir archivo .md
          </button>
          <input ref={fileRef} type="file" accept=".md,text/markdown,text/plain" hidden onChange={(e) => onFile(e.target.files?.[0])} />
        </div>
        <details>
          <summary style={{ fontSize: 12, color: 'var(--acm-fg-4)', cursor: 'pointer' }}>…o pegar el contenido</summary>
          <textarea
            className="mono" style={{ ...input, width: '100%', minHeight: 120, marginTop: 8 }} value={pasted}
            onChange={(e) => setPasted(e.target.value)} placeholder={'---\nname: "mi-skill"\ndescription: "Qué hace"\n---\n\nInstrucciones…'}
            aria-label="Contenido de la skill"
          />
          <button className="btn-secondary" style={{ marginTop: 6 }} disabled={!pasted.trim() || read.isPending} onClick={() => read.mutate({ content: pasted })}>
            Revisar contenido
          </button>
        </details>
        <p style={{ fontSize: 11, color: 'var(--acm-fg-4)', marginTop: 8 }}>
          Los enlaces deben ser https de GitHub (raw.githubusercontent.com o gist). Para publicar la tuya, abre un pull request
          que añada el archivo en <span className="mono">marketplace/skills</span> del repositorio de OpenACM (guía en <span className="mono">docs/25-skills-marketplace.md</span>).
        </p>
      </div>

      {preview && (
        <div style={{ ...box, marginBottom: 14, borderColor: preview.risky ? 'var(--acm-err)' : 'var(--acm-border-strong)' }}>
          <div style={{ display: 'flex', alignItems: 'start', gap: 10 }}>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: 15, fontWeight: 600 }}>{preview.name}
                <span className="mono" style={{ fontSize: 11, color: 'var(--acm-fg-4)', marginLeft: 8 }}>
                  {preview.category}{preview.author ? ` · ${preview.author}` : ''} · {(preview.size / 1000).toFixed(1)} KB
                </span>
              </div>
              <div style={{ fontSize: 13, color: 'var(--acm-fg-3)', marginTop: 2 }}>{preview.description}</div>
            </div>
            <button className="btn-secondary" aria-label="Cerrar revisión" onClick={() => setPreview(null)}><X size={13} /></button>
          </div>

          {preview.findings.length === 0 ? (
            <div style={{ fontSize: 12, color: 'var(--acm-ok)', margin: '10px 0' }}><Check size={13} style={{ verticalAlign: -2 }} /> La revisión automática no encontró señales de riesgo. Léela de todos modos.</div>
          ) : (
            <div style={{ margin: '10px 0', display: 'flex', flexDirection: 'column', gap: 6 }}>
              {preview.findings.map((f, i) => (
                <div key={i} style={{ fontSize: 12, display: 'flex', gap: 8 }}>
                  {f.level === 'high'
                    ? <ShieldAlert size={14} style={{ color: 'var(--acm-err)', flexShrink: 0, marginTop: 1 }} />
                    : <AlertTriangle size={14} style={{ color: 'var(--acm-fg-3)', flexShrink: 0, marginTop: 1 }} />}
                  <span><b>{f.level === 'high' ? 'Grave' : 'Ojo'}:</b> {f.message}
                    {f.snippet && <span className="mono" style={{ display: 'block', color: 'var(--acm-fg-4)', overflowWrap: 'anywhere' }}>…{f.snippet}…</span>}
                  </span>
                </div>
              ))}
            </div>
          )}

          <details>
            <summary style={{ fontSize: 12, cursor: 'pointer', color: 'var(--acm-fg-3)' }}>Leer el contenido completo</summary>
            <pre className="mono" style={{ fontSize: 12, whiteSpace: 'pre-wrap', maxHeight: 320, overflow: 'auto', marginTop: 8, overflowWrap: 'anywhere' }}>{preview.content}</pre>
          </details>

          <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap', marginTop: 12 }}>
            {preview.risky && (
              <input
                className="mono" style={{ ...input, width: 220 }} value={typed} onChange={(e) => setTyped(e.target.value)}
                placeholder={`escribe «${preview.name}» para confirmar`} aria-label="Confirmar el nombre de la skill"
              />
            )}
            <button
              className="btn-primary"
              disabled={preview.already_installed || install.isPending || (preview.risky && typed.trim() !== preview.name)}
              onClick={() => install.mutate(preview)}
            >
              {install.isPending ? <Loader2 size={13} className="animate-spin" /> : <Download size={13} />}
              {preview.already_installed ? 'Ya instalada' : 'Instalar skill'}
            </button>
          </div>
        </div>
      )}

      <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 10 }}>
        <Search size={14} style={{ color: 'var(--acm-fg-4)' }} />
        <input style={{ ...input, flex: 1, maxWidth: 360 }} value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Buscar skills…" aria-label="Buscar en el marketplace" />
      </div>

      {isLoading ? (
        <Loader2 className="animate-spin" size={18} />
      ) : data?.error ? (
        <div style={{ ...box, fontSize: 13, color: 'var(--acm-fg-3)' }}>No se pudo cargar el catálogo: {data.error} Aún puedes instalar desde un enlace o archivo.</div>
      ) : items.length === 0 ? (
        <div style={{ fontSize: 13, color: 'var(--acm-fg-4)' }}>No hay skills que coincidan.</div>
      ) : (
        <div className="grid gap-4" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))' }}>
          {items.map((s) => (
            <div key={s.name} style={{ ...box, display: 'flex', flexDirection: 'column', gap: 6 }}>
              <div style={{ fontSize: 14, fontWeight: 600 }}>{s.name}</div>
              <div style={{ fontSize: 12, color: 'var(--acm-fg-3)', lineHeight: 1.5, flex: 1 }}>{s.description}</div>
              <div className="mono" style={{ fontSize: 11, color: 'var(--acm-fg-4)' }}>{s.category} · {s.author}</div>
              <button
                className={s.installed ? 'btn-secondary' : 'btn-primary'}
                disabled={s.installed || read.isPending}
                onClick={() => read.mutate({ url: s.url, sha256: s.sha256 || undefined })}
              >
                {s.installed ? <><Check size={13} /> Instalada</> : <><Download size={13} /> Revisar e instalar</>}
              </button>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
