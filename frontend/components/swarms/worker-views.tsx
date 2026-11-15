'use client';

import { useState, useRef, useEffect } from 'react';
import { Trash2, Loader2, X, ChevronDown, ChevronUp, Edit2, Check, Cpu, Bot } from 'lucide-react';
import { useAPI } from '@/hooks/use-api';
import { useTools, type ToolInfo } from '@/hooks/use-api';
import { useUpdateWorkerTools, parseAllowedTools, serializeAllowedTools, useWorkerSkills, useToggleWorkerGlobalSkill, useToggleWorkerPrivateSkill, useDeleteWorkerPrivateSkill, useGenerateWorkerSkill } from '@/hooks/use-worker-config';
import { Settings, Search } from 'lucide-react';
import { Worker, Task, WORKER_DOT } from './shared';

export function ToolsTab({ worker, swarmId }: { worker: Worker; swarmId: number }) {
  const { data: tools, isLoading } = useTools();
  const updateTools = useUpdateWorkerTools(swarmId, worker.id);
  const [search, setSearch] = useState('');
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const initializedRef = useRef(false);

  useEffect(() => {
    if (tools && !initializedRef.current) {
      const allNames = tools.map(t => t.name);
      setSelected(parseAllowedTools(worker.allowed_tools, allNames));
      initializedRef.current = true;
    }
  }, [tools, worker.allowed_tools]);

  if (isLoading || !tools) return <Loader2 size={16} className="animate-spin" />;

  const allNames = tools.map(t => t.name);
  const filtered = tools.filter(t =>
    !search || t.name.toLowerCase().includes(search.toLowerCase()) || t.category.toLowerCase().includes(search.toLowerCase())
  );
  const byCategory: Record<string, ToolInfo[]> = {};
  for (const t of filtered) (byCategory[t.category] ??= []).push(t);

  const toggle = (name: string) => {
    setSelected(prev => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name); else next.add(name);
      return next;
    });
  };

  const save = () => updateTools.mutate(serializeAllowedTools(selected, allNames));

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center gap-2 bg-[var(--acm-elev)] border border-[var(--acm-border)] rounded px-2 py-1">
        <Search size={12} className="text-[var(--acm-fg-4)]" />
        <input
          value={search}
          onChange={e => setSearch(e.target.value)}
          placeholder="Buscar herramienta o categoría..."
          className="flex-1 bg-transparent text-[11px] text-[var(--acm-fg)] focus:outline-none mono"
        />
      </div>
      <div className="max-h-60 overflow-auto flex flex-col gap-2">
        {Object.entries(byCategory).map(([category, catTools]) => (
          <div key={category}>
            <div className="label text-[var(--acm-fg-4)] mb-1">{category}</div>
            {catTools.map(t => (
              <label key={t.name} className="flex items-center gap-2 py-0.5 text-[11px] text-[var(--acm-fg-2)] cursor-pointer">
                <input type="checkbox" checked={selected.has(t.name)} onChange={() => toggle(t.name)} />
                <span className="mono">{t.name}</span>
              </label>
            ))}
          </div>
        ))}
      </div>
      <button onClick={save} disabled={updateTools.isPending} className="btn-secondary self-end text-[11px] px-2 py-1">
        {updateTools.isPending ? 'Guardando...' : 'Guardar herramientas'}
      </button>
    </div>
  );
}

export function SkillsTab({ worker, swarmId }: { worker: Worker; swarmId: number }) {
  const { data, isLoading } = useWorkerSkills(swarmId, worker.id);
  const toggleGlobal = useToggleWorkerGlobalSkill(swarmId, worker.id);
  const togglePrivate = useToggleWorkerPrivateSkill(swarmId, worker.id);
  const deletePrivate = useDeleteWorkerPrivateSkill(swarmId, worker.id);
  const generate = useGenerateWorkerSkill(swarmId, worker.id);
  const [showGenerateForm, setShowGenerateForm] = useState(false);
  const [genName, setGenName] = useState('');
  const [genDescription, setGenDescription] = useState('');
  const [genUseCases, setGenUseCases] = useState('');

  if (isLoading || !data) return <Loader2 size={16} className="animate-spin" />;

  const submitGenerate = () => {
    generate.mutate(
      { name: genName, description: genDescription, use_cases: genUseCases },
      { onSuccess: () => { setShowGenerateForm(false); setGenName(''); setGenDescription(''); setGenUseCases(''); } },
    );
  };

  return (
    <div className="flex flex-col gap-3">
      <div>
        <div className="label text-[var(--acm-fg-4)] mb-1">Skills del sistema</div>
        {data.global_skills.map(s => (
          <label key={s.id} className="flex items-center gap-2 py-0.5 text-[11px] text-[var(--acm-fg-2)] cursor-pointer">
            <input
              type="checkbox"
              checked={!!s.enabled}
              onChange={() => toggleGlobal.mutate({ skillId: s.id, enable: !s.enabled })}
            />
            <span>{s.name}</span>
          </label>
        ))}
      </div>

      <div className="border-t border-[var(--acm-border)] pt-2">
        <div className="label text-[var(--acm-fg-4)] mb-1">Skills de este worker</div>
        {data.private_skills.map(s => (
          <div key={s.id} className="flex items-center gap-2 py-0.5 text-[11px] text-[var(--acm-fg-2)]">
            <input type="checkbox" checked={!!s.is_active} onChange={() => togglePrivate.mutate(s.id)} />
            <span className="flex-1">{s.name}</span>
            <button onClick={() => deletePrivate.mutate(s.id)} className="text-[var(--acm-fg-4)] hover:text-[var(--acm-err)]">
              <Trash2 size={11} />
            </button>
          </div>
        ))}

        {showGenerateForm ? (
          <div className="flex flex-col gap-1 mt-2">
            <input value={genName} onChange={e => setGenName(e.target.value)} placeholder="Nombre"
              className="bg-[var(--acm-elev)] border border-[var(--acm-border)] rounded px-2 py-1 text-[11px]" />
            <input value={genDescription} onChange={e => setGenDescription(e.target.value)} placeholder="Descripción"
              className="bg-[var(--acm-elev)] border border-[var(--acm-border)] rounded px-2 py-1 text-[11px]" />
            <input value={genUseCases} onChange={e => setGenUseCases(e.target.value)} placeholder="Casos de uso"
              className="bg-[var(--acm-elev)] border border-[var(--acm-border)] rounded px-2 py-1 text-[11px]" />
            <div className="flex gap-1 justify-end">
              <button onClick={() => setShowGenerateForm(false)} className="btn-secondary text-[11px] px-2 py-1">Cancelar</button>
              <button onClick={submitGenerate} disabled={generate.isPending || !genName} className="btn-secondary text-[11px] px-2 py-1">
                {generate.isPending ? 'Generando...' : 'Generar'}
              </button>
            </div>
          </div>
        ) : (
          <button onClick={() => setShowGenerateForm(true)} className="btn-secondary text-[11px] px-2 py-1 mt-2">
            + Nueva skill personalizada
          </button>
        )}
      </div>
    </div>
  );
}

// ─── Worker Card ──────────────────────────────────────────────────────────────

export function WorkerCard({ worker, swarmId, onUpdate, ctxPct }: { worker: Worker; swarmId: number; onUpdate: () => void; ctxPct?: number | null }) {
  const { fetchAPI } = useAPI();
  const [editModel, setEditModel] = useState(false);
  const [modelVal, setModelVal] = useState(worker.model || '');
  const [expanded, setExpanded] = useState(false);
  const [configOpen, setConfigOpen] = useState(false);
  const [configTab, setConfigTab] = useState<'tools' | 'skills'>('tools');

  const saveModel = async () => {
    await fetchAPI(`/api/swarms/${swarmId}/workers/${worker.id}`, {
      method: 'PUT', body: JSON.stringify({ model: modelVal || null }),
    });
    setEditModel(false);
    onUpdate();
  };

  return (
    <div className="acm-card p-[12px] flex flex-col gap-[10px] relative overflow-hidden">
      {worker.status === 'busy' && (
        <div className="acm-pulse absolute top-0 left-0 right-0 h-px bg-[var(--acm-accent)]" />
      )}
      <div className="flex items-start gap-3">
        <div className="w-8 h-8 rounded-lg bg-[var(--acm-elev)] flex items-center justify-center flex-shrink-0 border border-[var(--acm-border)]">
          <Bot size={15} className="text-[var(--acm-fg-3)]" />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="mono text-[12px] text-[var(--acm-fg)] font-semibold">{worker.name}</span>
            <span className={`label px-1.5 py-0.5 rounded border ${
              worker.role === 'orchestrator'
                ? 'border-[var(--acm-accent)] text-[var(--acm-accent)]'
                : 'border-[var(--acm-border-strong)] text-[var(--acm-fg-3)]'
            }`}>
              {worker.role}
            </span>
            <span className={`dot ${WORKER_DOT[worker.status] || 'dot-idle'} ml-auto`} />
            <span className="mono text-[10px] text-[var(--acm-fg-4)]">{worker.status}</span>
            {ctxPct != null && (
              <span className={`mono text-[10px] px-1 py-0.5 rounded border ${
                ctxPct >= 90 ? 'text-[var(--acm-err)] border-[var(--acm-err)]' :
                ctxPct >= 75 ? 'text-[var(--acm-warn)] border-[var(--acm-warn)]' :
                ctxPct >= 50 ? 'text-[oklch(0.75_0.12_55)] border-[oklch(0.75_0.12_55)]' :
                'text-[var(--acm-fg-4)] border-[var(--acm-border)]'
              }`}>{ctxPct >= 90 ? '⚠ ' : ''}{ctxPct}% ctx</span>
            )}
          </div>
          <p className="text-[var(--acm-fg-3)] text-[11px] mt-1 leading-relaxed">{worker.description}</p>
          <div className="flex items-center gap-2 mt-2">
            <Cpu size={11} className="text-[var(--acm-fg-4)]" />
            {editModel ? (
              <div className="flex items-center gap-1 flex-1">
                <input
                  value={modelVal}
                  onChange={e => setModelVal(e.target.value)}
                  placeholder="e.g. anthropic/claude-opus-4-6"
                  className="flex-1 bg-[var(--acm-elev)] border border-[var(--acm-border)] rounded px-2 py-0.5 text-[11px] text-[var(--acm-fg)] focus:outline-none focus:border-[var(--acm-accent)] mono"
                  autoFocus
                />
                <button onClick={saveModel} className="text-[var(--acm-ok)] hover:opacity-80 transition-opacity">
                  <Check size={13} />
                </button>
                <button
                  onClick={() => { setEditModel(false); setModelVal(worker.model || ''); }}
                  className="text-[var(--acm-fg-4)] hover:text-[var(--acm-fg)] transition-colors"
                >
                  <X size={13} />
                </button>
              </div>
            ) : (
              <button
                onClick={() => setEditModel(true)}
                className="flex items-center gap-1 text-[11px] text-[var(--acm-fg-4)] hover:text-[var(--acm-fg-2)] transition-colors group"
              >
                <span className="mono">{worker.model || 'system default'}</span>
                <Edit2 size={10} className="opacity-0 group-hover:opacity-100 transition-opacity" />
              </button>
            )}
          </div>
        </div>
      </div>
      <button
        onClick={() => setExpanded(v => !v)}
        className="flex items-center gap-1 text-[10px] text-[var(--acm-fg-4)] hover:text-[var(--acm-fg-3)] transition-colors"
      >
        {expanded ? <ChevronUp size={11} /> : <ChevronDown size={11} />}
        <span className="label">System prompt</span>
      </button>
      {expanded && (
        <pre className="text-[11px] text-[var(--acm-fg-3)] bg-[var(--acm-elev)] border border-[var(--acm-border)] rounded-lg p-3 overflow-auto max-h-40 whitespace-pre-wrap mono">
          {worker.system_prompt}
        </pre>
      )}
      <button
        onClick={() => setConfigOpen(v => !v)}
        className="flex items-center gap-1 text-[10px] text-[var(--acm-fg-4)] hover:text-[var(--acm-fg-3)] transition-colors"
      >
        <Settings size={11} />
        <span className="label">Configurar</span>
      </button>
      {configOpen && (
        <div className="flex flex-col gap-2 border-t border-[var(--acm-border)] pt-2">
          <div className="flex gap-2">
            <button
              onClick={() => setConfigTab('tools')}
              className={`label px-2 py-1 rounded ${configTab === 'tools' ? 'bg-[var(--acm-elev)] text-[var(--acm-fg)]' : 'text-[var(--acm-fg-4)]'}`}
            >
              Herramientas
            </button>
            <button
              onClick={() => setConfigTab('skills')}
              className={`label px-2 py-1 rounded ${configTab === 'skills' ? 'bg-[var(--acm-elev)] text-[var(--acm-fg)]' : 'text-[var(--acm-fg-4)]'}`}
            >
              Skills
            </button>
          </div>
          {configTab === 'tools' ? <ToolsTab worker={worker} swarmId={swarmId} /> : <SkillsTab worker={worker} swarmId={swarmId} />}
        </div>
      )}
    </div>
  );
}

// ─── Task Row ─────────────────────────────────────────────────────────────────
