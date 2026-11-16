'use client';

import { useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Loader2, ShieldAlert, Upload, Trash2, CheckCircle2, ChevronDown } from 'lucide-react';
import { useAPI, useIsAuthenticated } from '@/hooks/use-api';

interface Finding { level: 'high' | 'info'; file: string; line: number; what: string }
interface Analysis {
  id: string;
  sha256: string;
  manifest: { name: string; version: string; description: string; author: string; entry: string };
  files: { path: string; bytes: number }[];
  findings: Finding[];
  high_risk_count: number;
}
interface Uploaded { name: string; version?: string; description?: string; verified: boolean }

const EXAMPLE_MANIFEST = `{
  "name": "mi_plugin",
  "version": "1.0.0",
  "description": "Qué hace mi plugin",
  "author": "Tu nombre",
  "entry": "mi_plugin:PLUGIN"
}`;

const EXAMPLE_CODE = `# mi_plugin/__init__.py
from openacm.plugins import Plugin

class MiPlugin(Plugin):
    name = "mi_plugin"
    version = "1.0.0"
    description = "Qué hace mi plugin"

    def get_context_extension(self) -> str:
        return "Puedes mencionar que el plugin mi_plugin está instalado."

PLUGIN = MiPlugin()`;

const box: React.CSSProperties = {
  background: 'var(--acm-base)', border: '1px solid var(--acm-border)', borderRadius: 8,
  padding: 12, fontSize: 12, overflowX: 'auto', whiteSpace: 'pre', margin: '6px 0 12px',
};

export function PluginUpload() {
  const { fetchAPI } = useAPI();
  const isAuthenticated = useIsAuthenticated();
  const qc = useQueryClient();
  const fileRef = useRef<HTMLInputElement>(null);
  const [guideOpen, setGuideOpen] = useState(false);
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [typed, setTyped] = useState('');
  const [done, setDone] = useState<string | null>(null);

  const uploaded = useQuery<{ plugins: Uploaded[] }>({
    queryKey: ['plugins-uploaded'],
    queryFn: () => fetchAPI('/api/plugins/uploaded'),
    enabled: isAuthenticated,
  });

  const analyse = useMutation<Analysis, Error, File>({
    mutationFn: (file) =>
      fetchAPI('/api/plugins/upload', {
        method: 'POST',
        headers: { 'Content-Type': 'application/octet-stream' },
        body: file,
      }),
    onSuccess: (a) => { setAnalysis(a); setTyped(''); setDone(null); },
  });

  const install = useMutation<{ message: string }, Error, Analysis>({
    mutationFn: (a) =>
      fetchAPI(`/api/plugins/upload/${a.id}/install`, {
        method: 'POST',
        body: JSON.stringify({ name: typed, sha256: a.sha256 }),
      }),
    onSuccess: (r) => {
      setDone(r.message);
      setAnalysis(null);
      qc.invalidateQueries({ queryKey: ['plugins-uploaded'] });
    },
  });

  const discard = () => {
    if (analysis) fetchAPI(`/api/plugins/upload/${analysis.id}`, { method: 'DELETE' }).catch(() => {});
    setAnalysis(null);
    analyse.reset();
    install.reset();
  };

  const remove = useMutation<unknown, Error, string>({
    mutationFn: (name) => fetchAPI(`/api/plugins/uploaded/${name}`, { method: 'DELETE' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['plugins-uploaded'] }),
  });

  const high = analysis?.findings.filter((f) => f.level === 'high') ?? [];
  const info = analysis?.findings.filter((f) => f.level === 'info') ?? [];

  return (
    <div className="acm-card" style={{ padding: 16, marginBottom: 20 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
        <Upload size={16} style={{ color: 'var(--acm-fg-4)' }} />
        <div style={{ flex: 1, minWidth: 220 }}>
          <div style={{ fontSize: 13, fontWeight: 600 }}>Subir mi propio plugin (.zip)</div>
          <div style={{ fontSize: 12, color: 'var(--acm-fg-4)' }}>
            Primero se revisa, no se instala nada hasta que lo apruebes tú.
          </div>
        </div>
        <input
          ref={fileRef}
          type="file"
          accept=".zip,application/zip"
          style={{ display: 'none' }}
          onChange={(e) => {
            const file = e.target.files?.[0];
            e.target.value = '';
            if (file) { install.reset(); analyse.mutate(file); }
          }}
        />
        <button className="btn-primary" disabled={analyse.isPending} onClick={() => fileRef.current?.click()}>
          {analyse.isPending ? <Loader2 size={13} className="animate-spin" /> : <Upload size={13} />}
          {' '}Elegir .zip
        </button>
        <button className="btn-secondary" onClick={() => setGuideOpen((o) => !o)}>
          <ChevronDown size={13} style={{ transform: guideOpen ? 'rotate(180deg)' : 'none' }} /> Cómo se hace
        </button>
      </div>

      {guideOpen && (
        <div style={{ marginTop: 14, fontSize: 13, lineHeight: 1.6 }}>
          <p>Un plugin es una carpeta de Python dentro de un <b>.zip</b>, con este formato:</p>
          <div className="mono" style={box}>{`mi_plugin.zip
├─ openacm_plugin.json     ← describe el plugin (obligatorio)
└─ mi_plugin/
   └─ __init__.py          ← define PLUGIN = MiPlugin()`}</div>
          <p><b>openacm_plugin.json</b></p>
          <div className="mono" style={box}>{EXAMPLE_MANIFEST}</div>
          <p><b>mi_plugin/__init__.py</b> (un plugin mínimo; puede aportar herramientas, skills, rutas de API y más, igual que los plugins base):</p>
          <div className="mono" style={box}>{EXAMPLE_CODE}</div>
          <ol style={{ paddingLeft: 18 }}>
            <li>Comprime la carpeta y el JSON en un <b>.zip</b> (máx. 10 MB, 500 archivos).</li>
            <li>Súbelo aquí. Se guarda en cuarentena y se muestra un informe: archivos, y las llamadas delicadas que usa (ejecutar programas, red, variables de entorno, etc.).</li>
            <li>Si lo apruebas escribiendo su nombre, se instala <b>sin ejecutar nada</b> (no usa pip ni setup.py).</li>
            <li>Reinicia OpenACM y actívalo en la lista de plugins.</li>
          </ol>
          <div style={{ display: 'flex', gap: 8, color: 'var(--acm-fg-3)', fontSize: 12 }}>
            <ShieldAlert size={14} style={{ flexShrink: 0, marginTop: 2 }} />
            <span>
              Un plugin se ejecuta con el mismo acceso que OpenACM (archivos, claves, red). Solo instala código
              que hayas escrito tú o leído completo. Solo se admiten archivos de texto y Python (nada de .exe, .dll,
              .so ni scripts); las dependencias deben estar ya instaladas. Si alguien modifica los archivos después
              de aprobarlos, OpenACM deja de cargarlos.
            </span>
          </div>
        </div>
      )}

      {analyse.isError && (
        <p style={{ color: 'var(--acm-err)', fontSize: 13, marginTop: 12 }}>{analyse.error.message}</p>
      )}
      {done && (
        <p style={{ color: 'var(--acm-ok)', fontSize: 13, marginTop: 12 }}>
          <CheckCircle2 size={14} style={{ verticalAlign: -2 }} /> {done}
        </p>
      )}

      {analysis && (
        <div style={{ marginTop: 14, borderTop: '1px solid var(--acm-border)', paddingTop: 14, fontSize: 13 }}>
          <div style={{ fontWeight: 600 }}>
            {analysis.manifest.name} <span className="mono" style={{ fontWeight: 400 }}>v{analysis.manifest.version}</span>
          </div>
          {analysis.manifest.description && <div style={{ color: 'var(--acm-fg-3)' }}>{analysis.manifest.description}</div>}
          {analysis.manifest.author && <div style={{ color: 'var(--acm-fg-4)', fontSize: 12 }}>por {analysis.manifest.author}</div>}
          <div className="mono" style={{ fontSize: 11, color: 'var(--acm-fg-4)', margin: '6px 0' }}>
            SHA-256 {analysis.sha256.slice(0, 16)}… · {analysis.files.length} archivos
          </div>

          {high.length > 0 ? (
            <div style={{ border: '1px solid var(--acm-err)', borderRadius: 8, padding: 10, margin: '8px 0' }}>
              <b style={{ color: 'var(--acm-err)' }}>
                <ShieldAlert size={14} style={{ verticalAlign: -2 }} /> {high.length} llamada(s) de riesgo alto
              </b>
              <ul className="mono" style={{ fontSize: 11, margin: '6px 0 0', paddingLeft: 16 }}>
                {high.slice(0, 40).map((f, i) => (<li key={i}>{f.file}:{f.line} — {f.what}</li>))}
              </ul>
            </div>
          ) : (
            <p style={{ color: 'var(--acm-ok)', fontSize: 12 }}>No usa llamadas de riesgo alto (esto no es una garantía; léelo igualmente).</p>
          )}
          {info.length > 0 && (
            <details style={{ fontSize: 12, margin: '6px 0' }}>
              <summary>{info.length} aviso(s) informativos (red, sistema, etc.)</summary>
              <ul className="mono" style={{ fontSize: 11, paddingLeft: 16 }}>
                {info.slice(0, 60).map((f, i) => (<li key={i}>{f.file}:{f.line} — {f.what}</li>))}
              </ul>
            </details>
          )}
          <details style={{ fontSize: 12, margin: '6px 0' }}>
            <summary>Archivos</summary>
            <ul className="mono" style={{ fontSize: 11, paddingLeft: 16 }}>
              {analysis.files.map((f) => (<li key={f.path}>{f.path} ({f.bytes} B)</li>))}
            </ul>
          </details>

          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center', marginTop: 10 }}>
            <input
              className="mono"
              value={typed}
              onChange={(e) => setTyped(e.target.value)}
              placeholder={`Escribe «${analysis.manifest.name}» para aprobar`}
              aria-label="Nombre del plugin para aprobar"
              style={{
                flex: 1, minWidth: 220, background: 'var(--acm-base)', color: 'var(--acm-fg)',
                border: '1px solid var(--acm-border)', borderRadius: 8, padding: '8px 12px', fontSize: 13,
              }}
            />
            <button
              className="btn-primary"
              disabled={typed !== analysis.manifest.name || install.isPending}
              onClick={() => install.mutate(analysis)}
            >
              {install.isPending ? <Loader2 size={13} className="animate-spin" /> : null} Aprobar e instalar
            </button>
            <button className="btn-secondary" onClick={discard}>Descartar</button>
          </div>
          {install.isError && <p style={{ color: 'var(--acm-err)', marginTop: 8 }}>{install.error.message}</p>}
        </div>
      )}

      {(uploaded.data?.plugins.length ?? 0) > 0 && (
        <div style={{ marginTop: 14, borderTop: '1px solid var(--acm-border)', paddingTop: 12 }}>
          <div style={{ fontSize: 12, color: 'var(--acm-fg-4)', marginBottom: 6 }}>Plugins subidos por ti</div>
          {uploaded.data!.plugins.map((p) => (
            <div key={p.name} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13, padding: '4px 0' }}>
              <span style={{ flex: 1 }}>
                {p.name} {p.version && <span className="mono" style={{ color: 'var(--acm-fg-4)' }}>v{p.version}</span>}
                {!p.verified && (
                  <span style={{ color: 'var(--acm-err)', marginLeft: 8 }}>
                    modificado tras la aprobación — no se carga
                  </span>
                )}
              </span>
              <button
                className="btn-secondary"
                disabled={remove.isPending}
                onClick={() => { if (window.confirm(`¿Eliminar el plugin «${p.name}»?`)) remove.mutate(p.name); }}
                aria-label={`Eliminar ${p.name}`}
              >
                <Trash2 size={13} />
              </button>
            </div>
          ))}
          <div style={{ fontSize: 11, color: 'var(--acm-fg-4)', marginTop: 6 }}>
            Los cambios (instalar o eliminar) se aplican al reiniciar OpenACM.
          </div>
        </div>
      )}
    </div>
  );
}
