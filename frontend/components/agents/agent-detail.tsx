'use client';

import { useState, useRef, useEffect } from 'react';
import { useAgentMutations, useAgentSkills, useToggleAgentGlobalSkill, useGenerateAgentSkill, useToggleAgentPrivateSkill, useDeleteAgentPrivateSkill, type Agent, type AgentFormData } from '@/hooks/use-agents';
import { useTools } from '@/hooks/use-api';
import { useAgentFlows, useCreateFlow, useUpdateFlow, useDeleteFlow } from '@/hooks/use-agent-flows';
import { FlowCanvas } from '@/components/flow-editor/FlowCanvas';
import { parseAllowedTools, serializeAllowedTools } from '@/hooks/use-worker-config';
import { Trash2, Send, Loader2, X, Sparkles, Upload, BookOpen, Radio, Search } from 'lucide-react';
import { toast } from 'sonner';
import { KnowledgeTab } from './knowledge-tab';
import { ChannelsTab } from './channels-tab';
import { cn } from './shared';
import { MemoryModeField, InactivityFollowUpField, ShowInChatField } from './agent-form';

export function AgentDetailView({ agent, onClose }: { agent: Agent; onClose: () => void }) {
  const { update, generate } = useAgentMutations();
  const [form, setForm] = useState<AgentFormData>({
    name: agent.name,
    description: agent.description,
    system_prompt: agent.system_prompt,
    allowed_tools: agent.allowed_tools,
    show_in_chat: agent.show_in_chat ?? true,
    telegram_token: agent.telegram_token ?? '',
    memory_mode: agent.memory_mode ?? 'persistent',
    memory_ttl_hours: agent.memory_ttl_hours ?? 24,
    inactivity_timeout_minutes: agent.inactivity_timeout_minutes ?? 0,
    inactivity_message: agent.inactivity_message ?? '',
  });
  const [genDescription, setGenDescription] = useState('');
  const [droppedFiles, setDroppedFiles] = useState<File[]>([]);
  const [isDragging, setIsDragging] = useState(false);
  const [activeTab, setActiveTab] = useState<'config' | 'knowledge' | 'channels' | 'tools' | 'skills' | 'flows'>('config');

  const set = (field: keyof AgentFormData, val: string | number | boolean) =>
    setForm((f) => ({ ...f, [field]: val }));

  const handleGenerate = async () => {
    if (!genDescription.trim()) return;
    try {
      const res = await generate.mutateAsync({ description: genDescription, files: droppedFiles.length ? droppedFiles : undefined });
      setForm((f) => ({
        ...f,
        name: res.name || f.name,
        description: res.description || f.description,
        system_prompt: res.system_prompt || f.system_prompt,
      }));
      toast.success('Agent config generated!');
    } catch {
      toast.error('Generation failed — try again');
    }
  };

  const addFiles = (incoming: FileList | null) => {
    if (!incoming) return;
    const allowed = ['pdf', 'txt', 'md', 'csv', 'json', 'yaml', 'yml'];
    const next = Array.from(incoming).filter((f) => {
      const ext = f.name.split('.').pop()?.toLowerCase() ?? '';
      return allowed.includes(ext);
    });
    setDroppedFiles((prev) => {
      const names = new Set(prev.map((f) => f.name));
      return [...prev, ...next.filter((f) => !names.has(f.name))];
    });
  };

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    addFiles(e.dataTransfer.files);
  };

  const removeFile = (name: string) =>
    setDroppedFiles((prev) => prev.filter((f) => f.name !== name));

  const handleSave = async () => {
    try {
      // Only send the fields this tab actually has controls for — allowed_tools
      // is saved independently by AgentToolsTab, and including the mount-time
      // snapshot here would silently overwrite whatever was saved there since.
      await update.mutateAsync({
        id: agent.id,
        data: {
          name: form.name,
          description: form.description,
          system_prompt: form.system_prompt,
          memory_mode: form.memory_mode,
          memory_ttl_hours: form.memory_ttl_hours,
          inactivity_timeout_minutes: form.inactivity_timeout_minutes,
          inactivity_message: form.inactivity_message,
          show_in_chat: form.show_in_chat ?? true,
        },
      });
      toast.success('Agent updated');
    } catch {
      toast.error('Failed to save agent');
    }
  };

  return (
    <div className="w-full flex flex-col" style={{ minHeight: '70vh' }}>
      {/* Header */}
      <div className="flex items-center justify-between px-2 py-4 shrink-0" style={{ borderBottom: '1px solid var(--acm-border)' }}>
        <h2 className="text-[18px] font-semibold" style={{ color: 'var(--acm-fg)' }}>{agent.name}</h2>
        <button
          onClick={onClose}
          className="p-1.5 rounded transition-colors"
          style={{ color: 'var(--acm-fg-4)' }}
          onMouseEnter={e => (e.currentTarget.style.color = 'var(--acm-fg)')}
          onMouseLeave={e => (e.currentTarget.style.color = 'var(--acm-fg-4)' )}
        >
          <X size={18} />
        </button>
      </div>

      {/* Tab bar — 5 tabs now */}
      <div className="flex border-b border-zinc-800 px-2 flex-wrap">
        <button onClick={() => setActiveTab('config')} className={cn('px-4 py-2 text-sm font-medium border-b-2 -mb-px transition-colors', activeTab === 'config' ? 'border-blue-500 text-blue-400' : 'border-transparent text-zinc-500 hover:text-zinc-300')}>⚙ Config</button>
        <button onClick={() => setActiveTab('knowledge')} className={cn('px-4 py-2 text-sm font-medium border-b-2 -mb-px transition-colors', activeTab === 'knowledge' ? 'border-blue-500 text-blue-400' : 'border-transparent text-zinc-500 hover:text-zinc-300')}>
          <span className="flex items-center gap-1.5"><BookOpen className="w-3.5 h-3.5" />Knowledge</span>
        </button>
        <button onClick={() => setActiveTab('channels')} className={cn('px-4 py-2 text-sm font-medium border-b-2 -mb-px transition-colors', activeTab === 'channels' ? 'border-blue-500 text-blue-400' : 'border-transparent text-zinc-500 hover:text-zinc-300')}>
          <span className="flex items-center gap-1.5"><Radio className="w-3.5 h-3.5" />Channels</span>
        </button>
        <button onClick={() => setActiveTab('tools')} className={cn('px-4 py-2 text-sm font-medium border-b-2 -mb-px transition-colors', activeTab === 'tools' ? 'border-blue-500 text-blue-400' : 'border-transparent text-zinc-500 hover:text-zinc-300')}>Herramientas</button>
        <button onClick={() => setActiveTab('skills')} className={cn('px-4 py-2 text-sm font-medium border-b-2 -mb-px transition-colors', activeTab === 'skills' ? 'border-blue-500 text-blue-400' : 'border-transparent text-zinc-500 hover:text-zinc-300')}>Skills</button>
        <button onClick={() => setActiveTab('flows')} className={cn('px-4 py-2 text-sm font-medium border-b-2 -mb-px transition-colors', activeTab === 'flows' ? 'border-blue-500 text-blue-400' : 'border-transparent text-zinc-500 hover:text-zinc-300')}>Flujos</button>
      </div>

      <div className="p-2 pt-5 space-y-5 overflow-y-auto acm-scroll flex-1">
        {activeTab === 'channels' ? (
          <ChannelsTab agentId={agent.id} />
        ) : activeTab === 'knowledge' ? (
          <KnowledgeTab agentId={agent.id} />
        ) : activeTab === 'tools' ? (
          <AgentToolsTab agent={agent} />
        ) : activeTab === 'skills' ? (
          <AgentSkillsTab agentId={agent.id} />
        ) : activeTab === 'flows' ? (
          <FlowsTab agentId={agent.id} />
        ) : (
          <>
            {/* ── AI Generator ─────────────────────────────── */}
            <div className="rounded-xl p-4 space-y-3" style={{ background: 'var(--acm-elev)', border: '1px solid var(--acm-border)' }}>
              <p className="text-[11px] font-semibold flex items-center gap-1.5 uppercase tracking-[0.1em]" style={{ color: 'var(--acm-accent)' }}>
                <Sparkles size={12} /> Generate with AI
              </p>
              <textarea
                value={genDescription}
                onChange={(e) => setGenDescription(e.target.value)}
                placeholder="Describe what your agent should do..."
                rows={3}
                className="acm-input w-full resize-none text-[13px]"
              />
              <div
                onDragOver={(e) => { e.preventDefault(); setIsDragging(true); }}
                onDragLeave={() => setIsDragging(false)}
                onDrop={onDrop}
                className="relative rounded-lg px-4 py-3 transition-colors cursor-pointer"
                style={{
                  border: `2px dashed ${isDragging ? 'var(--acm-accent)' : 'var(--acm-border-strong)'}`,
                  background: isDragging ? 'var(--acm-accent-tint)' : 'transparent',
                }}
              >
                <input
                  id="agent-detail-file-input"
                  type="file"
                  accept=".pdf,.txt,.md,.csv,.json,.yaml,.yml"
                  multiple
                  className="hidden"
                  onChange={(e) => addFiles(e.target.files)}
                />
                <label htmlFor="agent-detail-file-input" className="flex items-center gap-2 text-[12px] cursor-pointer" style={{ color: 'var(--acm-fg-3)' }}>
                  <Upload size={14} />
                  Drop files here or click to attach (optional context for generation)
                </label>
                {droppedFiles.length > 0 && (
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {droppedFiles.map((f) => (
                      <span key={f.name} className="flex items-center gap-1 text-[11px] px-2 py-0.5 rounded" style={{ background: 'var(--acm-base)', border: '1px solid var(--acm-border)', color: 'var(--acm-fg-3)' }}>
                        {f.name}
                        <button onClick={(e) => { e.stopPropagation(); removeFile(f.name); }}><X size={10} /></button>
                      </span>
                    ))}
                  </div>
                )}
              </div>
              <button onClick={handleGenerate} disabled={generate.isPending || !genDescription.trim()} className="btn-secondary w-full justify-center">
                {generate.isPending ? <Loader2 size={13} className="animate-spin" /> : <Sparkles size={13} />}
                Generate
              </button>
            </div>

            {/* ── Fields ───────────────────────────────────── */}
            <div className="space-y-1">
              <label className="text-[11px] font-medium" style={{ color: 'var(--acm-fg-3)' }}>Name</label>
              <input value={form.name} onChange={(e) => set('name', e.target.value)} className="acm-input w-full text-[13px]" />
            </div>
            <div className="space-y-1">
              <label className="text-[11px] font-medium" style={{ color: 'var(--acm-fg-3)' }}>Description</label>
              <input value={form.description} onChange={(e) => set('description', e.target.value)} className="acm-input w-full text-[13px]" />
            </div>
            <div className="space-y-1">
              <label className="text-[11px] font-medium" style={{ color: 'var(--acm-fg-3)' }}>System Prompt</label>
              <textarea value={form.system_prompt} onChange={(e) => set('system_prompt', e.target.value)} rows={8} className="acm-input w-full text-[13px] resize-y" />
            </div>

            <MemoryModeField form={form} set={set} />
            <InactivityFollowUpField form={form} set={set} />
            <ShowInChatField form={form} set={set} />

            <button onClick={handleSave} disabled={update.isPending || !form.name.trim() || !form.system_prompt.trim()} className="btn-primary">
              {update.isPending && <Loader2 size={13} className="animate-spin" />}
              Save changes
            </button>
          </>
        )}
      </div>
    </div>
  );
}

// ── Test Panel ────────────────────────────────────────────────────────────────

export function TestPanel({ agent }: { agent: Agent }) {
  const { test } = useAgentMutations();
  const [input, setInput] = useState('');
  const [messages, setMessages] = useState<{ role: 'user' | 'agent'; text: string }[]>([]);

  const send = async () => {
    const msg = input.trim();
    if (!msg) return;
    setInput('');
    setMessages((m) => [...m, { role: 'user', text: msg }]);
    try {
      const res = await test.mutateAsync({ id: agent.id, message: msg });
      setMessages((m) => [...m, { role: 'agent', text: res.response }]);
    } catch {
      setMessages((m) => [...m, { role: 'agent', text: '⚠️ Error getting response.' }]);
    }
  };

  return (
    <div className="mt-4 pt-4" style={{ borderTop: '1px solid var(--acm-border)' }}>
      <p className="text-[11px] font-medium flex items-center gap-1.5 mb-3 uppercase tracking-[0.08em]" style={{ color: 'var(--acm-fg-4)' }}>
        <Send size={11} /> Test this agent
      </p>

      {messages.length > 0 && (
        <div className="space-y-2 mb-3 max-h-48 overflow-y-auto acm-scroll">
          {messages.map((m, i) => (
            <div
              key={i}
              className={cn(
                'text-[12px] px-3 py-2 rounded-lg max-w-[90%]',
                m.role === 'user' ? 'ml-auto' : ''
              )}
              style={
                m.role === 'user'
                  ? {
                      background: 'var(--acm-accent-tint)',
                      borderLeft: '2px solid var(--acm-accent)',
                      color: 'var(--acm-fg-2)',
                    }
                  : {
                      background: 'var(--acm-elev)',
                      color: 'var(--acm-fg-3)',
                    }
              }
            >
              {m.text}
            </div>
          ))}
          {test.isPending && (
            <div className="flex items-center gap-1.5 text-[11px]" style={{ color: 'var(--acm-fg-4)' }}>
              <Loader2 size={11} className="animate-spin" /> Thinking...
            </div>
          )}
        </div>
      )}

      <div className="flex gap-2">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && !e.shiftKey && send()}
          placeholder="Write a test message..."
          disabled={test.isPending}
          className="acm-input flex-1 text-[13px] disabled:opacity-50"
        />
        <button
          onClick={send}
          disabled={test.isPending || !input.trim()}
          className="btn-primary px-2.5 py-2 disabled:opacity-50"
        >
          <Send size={13} />
        </button>
      </div>
    </div>
  );
}

// ── Agent Card ────────────────────────────────────────────────────────────────

function AgentToolsTab({ agent }: { agent: Agent }) {
  const { data: tools, isLoading } = useTools();
  const { update } = useAgentMutations();
  const [search, setSearch] = useState('');
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const initializedRef = useRef(false);

  useEffect(() => {
    if (tools && !initializedRef.current) {
      const allNames = tools.map(t => t.name);
      setSelected(parseAllowedTools(agent.allowed_tools, allNames));
      initializedRef.current = true;
    }
  }, [tools, agent.allowed_tools]);

  if (isLoading || !tools) return <Loader2 size={16} className="animate-spin" />;

  const allNames = tools.map(t => t.name);
  const filtered = tools.filter(t =>
    !search || t.name.toLowerCase().includes(search.toLowerCase()) || t.category.toLowerCase().includes(search.toLowerCase())
  );
  const byCategory: Record<string, typeof tools> = {};
  for (const t of filtered) (byCategory[t.category] ??= []).push(t);

  const toggle = (name: string) => {
    setSelected(prev => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name); else next.add(name);
      return next;
    });
  };

  const save = () => update.mutate({ id: agent.id, data: { allowed_tools: serializeAllowedTools(selected, allNames) } });

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
      <div className="max-h-96 overflow-auto flex flex-col gap-2">
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
      <button onClick={save} disabled={update.isPending} className="btn-secondary self-end text-[11px] px-2 py-1">
        {update.isPending ? 'Guardando...' : 'Guardar herramientas'}
      </button>
    </div>
  );
}

function AgentSkillsTab({ agentId }: { agentId: number }) {
  const { data, isLoading } = useAgentSkills(agentId);
  const toggleGlobal = useToggleAgentGlobalSkill(agentId);
  const togglePrivate = useToggleAgentPrivateSkill(agentId);
  const deletePrivate = useDeleteAgentPrivateSkill(agentId);
  const generate = useGenerateAgentSkill(agentId);
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
        <div className="label text-[var(--acm-fg-4)] mb-1">Skills de este agente</div>
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

function FlowsTab({ agentId }: { agentId: number }) {
  const { data: flows, isLoading } = useAgentFlows(agentId);
  const create = useCreateFlow(agentId);
  const update = useUpdateFlow(agentId);
  const del = useDeleteFlow(agentId);
  const [editingFlowId, setEditingFlowId] = useState<number | null>(null);
  const [showImport, setShowImport] = useState(false);
  const [importText, setImportText] = useState('');
  const [importError, setImportError] = useState<string | null>(null);

  if (isLoading || !flows) return <Loader2 size={16} className="animate-spin" />;

  const handleCreate = () => {
    create.mutate({ name: 'Nuevo flujo', description: '' }, {
      onSuccess: (created: any) => setEditingFlowId(created.id),
    });
  };

  const handleImport = () => {
    setImportError(null);
    let parsed: any;
    try {
      parsed = JSON.parse(importText);
    } catch {
      setImportError('Eso no es JSON válido.');
      return;
    }
    if (parsed.kind !== 'openacm-flow' || !parsed.graph_json) {
      setImportError('Esto no parece un flujo de OpenACM exportado.');
      return;
    }
    create.mutate(
      {
        name: parsed.name || 'Flujo importado',
        description: parsed.description || '',
        graph_json: JSON.stringify(parsed.graph_json),
      },
      {
        onSuccess: (created: any) => {
          setShowImport(false);
          setImportText('');
          setEditingFlowId(created.id);
        },
        onError: (err: Error) => setImportError(err.message || 'Error al importar el flujo.'),
      }
    );
  };

  if (editingFlowId !== null) {
    const editingFlow = flows.find(f => f.id === editingFlowId);
    if (!editingFlow) return null;
    return (
      <div className="flex flex-col gap-2">
        <button onClick={() => setEditingFlowId(null)} className="btn-secondary self-start text-[11px] px-2 py-1">
          ← Volver a la lista
        </button>
        <FlowCanvas
          agentId={agentId}
          flow={editingFlow}
          onSave={(graphJson) => {
            update.mutate(
              { id: editingFlow.id, data: { graph_json: graphJson } },
              { onError: (err: Error) => toast.error(err.message || 'Error al guardar el flujo') }
            );
          }}
        />
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-2">
      <div className="flex gap-2 self-end">
        <button onClick={() => setShowImport(v => !v)} className="btn-secondary text-[11px] px-2 py-1">
          Importar flujo
        </button>
        <button onClick={handleCreate} disabled={create.isPending} className="btn-secondary text-[11px] px-2 py-1">
          + Nuevo flujo
        </button>
      </div>
      {showImport && (
        <div className="flex flex-col gap-1 p-2 rounded" style={{ background: 'var(--acm-elev)', border: '1px solid var(--acm-border)' }}>
          <textarea
            value={importText}
            onChange={e => setImportText(e.target.value)}
            placeholder="Pega el JSON exportado aquí"
            rows={6}
            className="text-[11px] p-2 rounded"
            style={{ background: 'var(--acm-base)', border: '1px solid var(--acm-border)', color: 'var(--acm-fg-2)', fontFamily: 'monospace' }}
          />
          {importError && <div className="text-[11px]" style={{ color: 'var(--acm-danger, #e55)' }}>{importError}</div>}
          <button onClick={handleImport} disabled={create.isPending || !importText.trim()} className="btn-primary text-[11px] px-2 py-1 self-start">
            Importar
          </button>
        </div>
      )}
      {flows.length === 0 ? (
        <div className="text-[12px]" style={{ color: 'var(--acm-fg-4)' }}>Este agente no tiene flujos todavía.</div>
      ) : (
        flows.map(f => (
          <div key={f.id} className="flex items-center gap-2 py-1.5 px-2 rounded text-[12px]" style={{ background: 'var(--acm-elev)', border: '1px solid var(--acm-border)' }}>
            <input
              type="checkbox"
              checked={!!f.is_active}
              onChange={() => update.mutate({ id: f.id, data: { is_active: f.is_active ? 0 : 1 } })}
              title="Activo"
            />
            <div className="flex-1">
              <div style={{ color: 'var(--acm-fg-2)' }}>{f.name}</div>
              {f.description && <div style={{ color: 'var(--acm-fg-4)' }}>{f.description}</div>}
            </div>
            <button onClick={() => setEditingFlowId(f.id)} className="btn-secondary text-[11px] px-2 py-1">Editar</button>
            <button onClick={() => del.mutate(f.id)} className="text-[var(--acm-fg-4)] hover:text-[var(--acm-err)]">
              <Trash2 size={12} />
            </button>
          </div>
        ))
      )}
    </div>
  );
}
