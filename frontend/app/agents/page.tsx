'use client';

import { useState } from 'react';
import { AppLayout } from '@/components/layout/app-layout';
import { useAgents, useAgentMutations, type Agent, type AgentFormData } from '@/hooks/use-agents';
import {
  Bot,
  Plus,
  Trash2,
  Edit2,
  Power,
  PowerOff,
  Send,
  Copy,
  Check,
  Loader2,
  Key,
  Globe,
  ChevronDown,
  ChevronUp,
  X,
  Sparkles,
  FileText,
  Upload,
} from 'lucide-react';
import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';
import { toast } from 'sonner';

function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

const TOOLS_OPTIONS = [
  { value: 'all', label: 'All tools' },
  { value: 'none', label: 'No tools (text only)' },
];

const DEFAULT_FORM: AgentFormData = {
  name: '',
  description: '',
  system_prompt: '',
  allowed_tools: 'all',
  telegram_token: '',
};

// ── Agent Form Modal ──────────────────────────────────────────────────────────

function AgentFormModal({
  initial,
  onSave,
  onClose,
  isSaving,
}: {
  initial?: Agent | null;
  onSave: (data: AgentFormData) => void;
  onClose: () => void;
  isSaving: boolean;
}) {
  const { generate } = useAgentMutations();
  const [form, setForm] = useState<AgentFormData>(
    initial
      ? {
          name: initial.name,
          description: initial.description,
          system_prompt: initial.system_prompt,
          allowed_tools: initial.allowed_tools,
          telegram_token: initial.telegram_token ?? '',
        }
      : DEFAULT_FORM
  );
  const [genDescription, setGenDescription] = useState('');
  const [droppedFiles, setDroppedFiles] = useState<File[]>([]);
  const [isDragging, setIsDragging] = useState(false);
  const [showAdvanced, setShowAdvanced] = useState(false);

  const set = (field: keyof AgentFormData, val: string) =>
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

  return (
    <div className="fixed inset-0 bg-black/70 backdrop-blur-sm flex items-center justify-center z-50 p-4">
      <div
        className="w-full max-w-2xl max-h-[90vh] overflow-y-auto acm-scroll flex flex-col"
        style={{ background: 'var(--acm-base)', border: '1px solid var(--acm-border)', borderRadius: '12px' }}
      >
        {/* Header */}
        <div
          className="flex items-center justify-between px-6 py-4 shrink-0"
          style={{ borderBottom: '1px solid var(--acm-border)' }}
        >
          <h2 className="text-[15px] font-semibold" style={{ color: 'var(--acm-fg)' }}>
            {initial ? 'Edit Agent' : 'New Agent'}
          </h2>
          <button
            onClick={onClose}
            className="p-1.5 rounded transition-colors"
            style={{ color: 'var(--acm-fg-4)' }}
            onMouseEnter={e => (e.currentTarget.style.color = 'var(--acm-fg)')}
            onMouseLeave={e => (e.currentTarget.style.color = 'var(--acm-fg-4)')}
          >
            <X size={16} />
          </button>
        </div>

        <div className="p-6 space-y-5 overflow-y-auto acm-scroll">

          {/* ── AI Generator ─────────────────────────────── */}
          <div
            className="rounded-xl p-4 space-y-3"
            style={{ background: 'var(--acm-elev)', border: '1px solid var(--acm-border)' }}
          >
            <p
              className="text-[11px] font-semibold flex items-center gap-1.5 uppercase tracking-[0.1em]"
              style={{ color: 'var(--acm-accent)' }}
            >
              <Sparkles size={12} /> Generate with AI
            </p>

            <textarea
              value={genDescription}
              onChange={(e) => setGenDescription(e.target.value)}
              placeholder="Describe what your agent should do... e.g. 'A support bot for my clothing store that always responds in Spanish and redirects billing questions to support@mystore.com'"
              rows={3}
              className="acm-input w-full resize-none text-[13px]"
            />

            {/* Drop zone */}
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
                id="agent-file-input"
                type="file"
                accept=".pdf,.txt,.md,.csv,.json,.yaml,.yml"
                multiple
                className="hidden"
                onChange={(e) => addFiles(e.target.files)}
              />
              {droppedFiles.length > 0 ? (
                <div className="space-y-1.5">
                  {droppedFiles.map((f) => (
                    <div key={f.name} className="flex items-center gap-2 text-[13px]" style={{ color: 'var(--acm-fg-2)' }}>
                      <FileText size={13} className="shrink-0" style={{ color: 'var(--acm-accent)' }} />
                      <span className="mono truncate flex-1 text-[11px]">{f.name}</span>
                      <button
                        onClick={(e) => { e.stopPropagation(); removeFile(f.name); }}
                        className="shrink-0 transition-colors"
                        style={{ color: 'var(--acm-fg-4)' }}
                        onMouseEnter={e => (e.currentTarget.style.color = 'var(--acm-err)')}
                        onMouseLeave={e => (e.currentTarget.style.color = 'var(--acm-fg-4)')}
                      >
                        <X size={12} />
                      </button>
                    </div>
                  ))}
                  <button
                    onClick={() => document.getElementById('agent-file-input')?.click()}
                    className="flex items-center gap-1.5 text-[11px] transition-colors mt-1"
                    style={{ color: 'var(--acm-accent-dim)' }}
                    onMouseEnter={e => (e.currentTarget.style.color = 'var(--acm-accent)')}
                    onMouseLeave={e => (e.currentTarget.style.color = 'var(--acm-accent-dim)')}
                  >
                    <Upload size={11} /> Add more files
                  </button>
                </div>
              ) : (
                <div
                  className="flex items-center justify-center gap-2 text-[11px] py-1"
                  style={{ color: 'var(--acm-fg-4)' }}
                  onClick={() => document.getElementById('agent-file-input')?.click()}
                >
                  <Upload size={13} />
                  Drop PDFs, TXTs or MDs for extra context (optional, multiple allowed)
                </div>
              )}
            </div>

            <button
              onClick={handleGenerate}
              disabled={generate.isPending || !genDescription.trim()}
              className="btn-primary text-[12px] px-3 py-1.5"
            >
              {generate.isPending
                ? <><Loader2 size={12} className="animate-spin" /> Generating...</>
                : <><Sparkles size={12} /> Generate rules</>}
            </button>
          </div>

          {/* ── Name ──────────────────────────────────────── */}
          <div>
            <label className="label block mb-2">Name *</label>
            <input
              value={form.name}
              onChange={(e) => set('name', e.target.value)}
              placeholder="e.g. Support Bot, Sales Assistant..."
              className="acm-input w-full"
            />
          </div>

          {/* ── Description ───────────────────────────────── */}
          <div>
            <label className="label block mb-2">Description</label>
            <input
              value={form.description}
              onChange={(e) => set('description', e.target.value)}
              placeholder="What does this agent do?"
              className="acm-input w-full"
            />
          </div>

          {/* ── System Prompt ──────────────────────────────── */}
          <div>
            <label className="label block mb-2">System Prompt (rules) *</label>
            <textarea
              value={form.system_prompt}
              onChange={(e) => set('system_prompt', e.target.value)}
              placeholder={`You are a friendly support assistant for Acme Corp.\n\nRules:\n- Always respond in Spanish\n- Never reveal internal pricing\n- If asked about refunds, direct to support@acme.com`}
              rows={8}
              className="acm-input w-full mono resize-y text-[13px]"
            />
          </div>

          {/* ── Tools Access ───────────────────────────────── */}
          <div>
            <label className="label block mb-2">Tools access</label>
            <select
              value={form.allowed_tools}
              onChange={(e) => set('allowed_tools', e.target.value)}
              className="w-full appearance-none text-[14px] outline-none py-2 px-0 transition-colors"
              style={{
                background: 'transparent',
                border: 'none',
                borderBottom: '1px solid var(--acm-border)',
                color: 'var(--acm-fg)',
              }}
              onFocus={e => (e.currentTarget.style.borderBottomColor = 'var(--acm-accent)')}
              onBlur={e => (e.currentTarget.style.borderBottomColor = 'var(--acm-border)')}
            >
              {TOOLS_OPTIONS.map((o) => (
                <option key={o.value} value={o.value} style={{ background: 'var(--acm-card)' }}>
                  {o.label}
                </option>
              ))}
            </select>
            <p className="text-[11px] mt-1.5" style={{ color: 'var(--acm-fg-4)' }}>
              "All tools" lets the agent run commands, search the web, etc.
              Choose "No tools" for pure text/FAQ bots.
            </p>
          </div>

          {/* ── Advanced toggle ────────────────────────────── */}
          <button
            type="button"
            onClick={() => setShowAdvanced(!showAdvanced)}
            className="flex items-center gap-1.5 text-[12px] transition-colors"
            style={{ color: 'var(--acm-fg-4)' }}
            onMouseEnter={e => (e.currentTarget.style.color = 'var(--acm-fg-2)')}
            onMouseLeave={e => (e.currentTarget.style.color = 'var(--acm-fg-4)')}
          >
            {showAdvanced ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
            Advanced options
          </button>

          {showAdvanced && (
            <div>
              <label className="label block mb-2">Telegram Bot Token (optional)</label>
              <input
                value={form.telegram_token}
                onChange={(e) => set('telegram_token', e.target.value)}
                placeholder="1234567890:ABCdef..."
                className="acm-input mono w-full"
              />
              <p className="text-[11px] mt-1.5" style={{ color: 'var(--acm-fg-4)' }}>
                Connect this agent to its own Telegram bot (coming soon).
              </p>
            </div>
          )}
        </div>

        {/* Footer */}
        <div
          className="flex justify-end gap-2 px-6 py-4 shrink-0"
          style={{ borderTop: '1px solid var(--acm-border)' }}
        >
          <button
            onClick={onClose}
            className="px-4 py-2 text-[13px] transition-colors rounded"
            style={{ color: 'var(--acm-fg-3)' }}
            onMouseEnter={e => (e.currentTarget.style.color = 'var(--acm-fg)')}
            onMouseLeave={e => (e.currentTarget.style.color = 'var(--acm-fg-3)')}
          >
            Cancel
          </button>
          <button
            onClick={() => onSave(form)}
            disabled={isSaving || !form.name.trim() || !form.system_prompt.trim()}
            className="btn-primary"
          >
            {isSaving && <Loader2 size={13} className="animate-spin" />}
            {initial ? 'Save changes' : 'Create Agent'}
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Test Panel ────────────────────────────────────────────────────────────────

function TestPanel({ agent }: { agent: Agent }) {
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

function AgentCard({
  agent,
  onEdit,
  onDelete,
  onToggle,
}: {
  agent: Agent;
  onEdit: (a: Agent) => void;
  onDelete: (id: number) => void;
  onToggle: (id: number, active: boolean) => void;
}) {
  const [showTest, setShowTest] = useState(false);
  const [showSecret, setShowSecret] = useState(false);
  const [secret, setSecret] = useState('');
  const [copied, setCopied] = useState(false);
  const { getSecret } = useAgentMutations();

  const revealSecret = async () => {
    if (secret) {
      setShowSecret(true);
      return;
    }
    try {
      const res = await getSecret.mutateAsync(agent.id);
      setSecret(res.webhook_secret);
      setShowSecret(true);
    } catch {
      toast.error('Could not retrieve secret');
    }
  };

  const copySecret = () => {
    navigator.clipboard.writeText(secret);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const webhookUrl = typeof window !== 'undefined'
    ? `${window.location.origin}/api/agents/${agent.id}/chat`
    : `/api/agents/${agent.id}/chat`;

  return (
    <div
      className="acm-card p-5 flex flex-col gap-0"
      style={{ opacity: agent.is_active ? 1 : 0.6 }}
    >
      {/* Header */}
      <div className="flex items-start justify-between mb-3">
        <div className="flex items-center gap-3 min-w-0 flex-1">
          {/* Icon box */}
          <div
            className="w-10 h-10 rounded-lg flex items-center justify-center shrink-0"
            style={{ background: 'var(--acm-elev)' }}
          >
            <Bot size={20} style={{ color: agent.is_active ? 'var(--acm-accent)' : 'var(--acm-fg-4)' }} />
          </div>
          <div className="min-w-0">
            <h3 className="text-[14px] font-semibold truncate" style={{ color: 'var(--acm-fg)' }}>
              {agent.name}
            </h3>
            {agent.description && (
              <p className="text-[12px] mt-0.5 truncate" style={{ color: 'var(--acm-fg-3)' }}>
                {agent.description}
              </p>
            )}
          </div>
        </div>

        {/* Status indicator */}
        <div className="flex items-center gap-1.5 shrink-0 ml-2">
          {agent.is_active
            ? <span className="dot dot-ok acm-pulse" />
            : <span className="dot dot-idle" />}
          <span
            className="mono text-[10px] uppercase tracking-[0.1em]"
            style={{ color: agent.is_active ? 'var(--acm-ok)' : 'var(--acm-fg-4)' }}
          >
            {agent.is_active ? 'Active' : 'Inactive'}
          </span>
        </div>
      </div>

      {/* System prompt preview */}
      <div
        className="mono text-[11px] line-clamp-2 px-3 py-2 rounded-lg mb-4"
        style={{ color: 'var(--acm-fg-4)', background: 'var(--acm-elev)' }}
      >
        {agent.system_prompt}
      </div>

      {/* Badges row */}
      <div className="flex items-center gap-2 mb-4 flex-wrap">
        <span
          className="mono text-[10px] px-[6px] py-[2px] rounded-[3px] uppercase tracking-[0.06em]"
          style={{ color: 'var(--acm-fg-4)', border: '1px solid var(--acm-border)' }}
        >
          Tools: {agent.allowed_tools === 'all' ? 'All' : agent.allowed_tools === 'none' ? 'None' : 'Custom'}
        </span>
        {agent.telegram_token && (
          <span
            className="mono text-[10px] px-[6px] py-[2px] rounded-[3px] uppercase tracking-[0.06em]"
            style={{ color: 'var(--acm-fg-4)', border: '1px solid var(--acm-border)' }}
          >
            Telegram
          </span>
        )}
      </div>

      {/* Webhook URL */}
      <div className="mb-4">
        <p
          className="text-[11px] mb-1.5 flex items-center gap-1 uppercase tracking-[0.08em]"
          style={{ color: 'var(--acm-fg-4)' }}
        >
          <Globe size={10} /> Webhook URL
        </p>
        <div className="flex items-center gap-2">
          <code
            className="mono flex-1 text-[11px] px-2 py-1.5 rounded-lg truncate"
            style={{ color: 'var(--acm-fg-3)', background: 'var(--acm-elev)' }}
          >
            {webhookUrl}
          </code>
          <button
            onClick={() => { navigator.clipboard.writeText(webhookUrl); toast.success('Copied!'); }}
            className="p-1.5 rounded-lg transition-colors shrink-0"
            style={{ color: 'var(--acm-fg-4)', background: 'var(--acm-elev)' }}
            onMouseEnter={e => (e.currentTarget.style.color = 'var(--acm-fg)')}
            onMouseLeave={e => (e.currentTarget.style.color = 'var(--acm-fg-4)')}
          >
            <Copy size={12} />
          </button>
        </div>
      </div>

      {/* Secret */}
      <div className="mb-4">
        <p
          className="text-[11px] mb-1.5 flex items-center gap-1 uppercase tracking-[0.08em]"
          style={{ color: 'var(--acm-fg-4)' }}
        >
          <Key size={10} /> X-Agent-Secret header
        </p>
        {showSecret ? (
          <div className="flex items-center gap-2">
            <code
              className="mono flex-1 text-[11px] px-2 py-1.5 rounded-lg truncate"
              style={{ color: 'var(--acm-ok)', background: 'var(--acm-elev)' }}
            >
              {secret}
            </code>
            <button
              onClick={copySecret}
              className="p-1.5 rounded-lg transition-colors shrink-0"
              style={{ color: 'var(--acm-fg-4)', background: 'var(--acm-elev)' }}
              onMouseEnter={e => (e.currentTarget.style.color = 'var(--acm-fg)')}
              onMouseLeave={e => (e.currentTarget.style.color = 'var(--acm-fg-4)')}
            >
              {copied
                ? <Check size={12} style={{ color: 'var(--acm-ok)' }} />
                : <Copy size={12} />}
            </button>
          </div>
        ) : (
          <button
            onClick={revealSecret}
            disabled={getSecret.isPending}
            className="flex items-center gap-1.5 text-[12px] transition-colors"
            style={{ color: 'var(--acm-accent-dim)' }}
            onMouseEnter={e => (e.currentTarget.style.color = 'var(--acm-accent)')}
            onMouseLeave={e => (e.currentTarget.style.color = 'var(--acm-accent-dim)')}
          >
            {getSecret.isPending ? <Loader2 size={11} className="animate-spin" /> : <Key size={11} />}
            Reveal secret
          </button>
        )}
      </div>

      {/* Footer actions */}
      <div
        className="flex items-center gap-1.5 pt-3"
        style={{ borderTop: '1px solid var(--acm-border)' }}
      >
        {/* Toggle: btn-secondary that changes text on hover */}
        <button
          onClick={() => onToggle(agent.id, !agent.is_active)}
          className="btn-secondary text-[12px] px-3 py-1.5 group"
        >
          {agent.is_active
            ? <><PowerOff size={12} /><span className="group-hover:hidden">Deactivate</span><span className="hidden group-hover:inline">Pause</span></>
            : <><Power size={12} /><span className="group-hover:hidden">Activate</span><span className="hidden group-hover:inline">Enable</span></>}
        </button>

        {/* Edit ghost */}
        <button
          onClick={() => onEdit(agent)}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded text-[12px] transition-colors"
          style={{ color: 'var(--acm-fg-4)' }}
          onMouseEnter={e => (e.currentTarget.style.color = 'var(--acm-fg)')}
          onMouseLeave={e => (e.currentTarget.style.color = 'var(--acm-fg-4)')}
        >
          <Edit2 size={12} /> Edit
        </button>

        {/* Clone ghost */}
        <button
          onClick={() => setShowTest(!showTest)}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded text-[12px] transition-colors ml-auto"
          style={{
            color: showTest ? 'var(--acm-accent)' : 'var(--acm-fg-4)',
          }}
          onMouseEnter={e => !showTest && (e.currentTarget.style.color = 'var(--acm-fg)')}
          onMouseLeave={e => !showTest && (e.currentTarget.style.color = 'var(--acm-fg-4)')}
        >
          <Send size={12} /> Test
        </button>

        {/* Delete ghost */}
        <button
          onClick={() => onDelete(agent.id)}
          className="p-1.5 rounded transition-colors"
          style={{ color: 'var(--acm-fg-4)' }}
          onMouseEnter={e => (e.currentTarget.style.color = 'var(--acm-err)')}
          onMouseLeave={e => (e.currentTarget.style.color = 'var(--acm-fg-4)')}
        >
          <Trash2 size={13} />
        </button>
      </div>

      {showTest && <TestPanel agent={agent} />}
    </div>
  );
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function AgentsPage() {
  const { data: agents = [], isLoading } = useAgents();
  const { create, update, remove } = useAgentMutations();

  const [modal, setModal] = useState<'create' | 'edit' | null>(null);
  const [editing, setEditing] = useState<Agent | null>(null);
  const [pendingSecret, setPendingSecret] = useState<{ name: string; secret: string } | null>(null);

  const openCreate = () => { setEditing(null); setModal('create'); };
  const openEdit = (a: Agent) => { setEditing(a); setModal('edit'); };
  const closeModal = () => { setModal(null); setEditing(null); };

  const handleSave = async (data: AgentFormData) => {
    try {
      if (modal === 'edit' && editing) {
        await update.mutateAsync({ id: editing.id, data });
        toast.success('Agent updated');
        closeModal();
      } else {
        const res = await create.mutateAsync(data);
        closeModal();
        // Show the secret once after creation
        if (res?.webhook_secret) {
          setPendingSecret({ name: res.name, secret: res.webhook_secret });
        }
        toast.success('Agent created');
      }
    } catch (e: unknown) {
      toast.error('Failed to save agent');
    }
  };

  const handleDelete = async (id: number) => {
    if (!confirm('Delete this agent? This cannot be undone.')) return;
    try {
      await remove.mutateAsync(id);
      toast.success('Agent deleted');
    } catch {
      toast.error('Failed to delete agent');
    }
  };

  const handleToggle = async (id: number, active: boolean) => {
    try {
      await update.mutateAsync({ id, data: { is_active: active } });
      toast.success(active ? 'Agent activated' : 'Agent deactivated');
    } catch {
      toast.error('Failed to update agent');
    }
  };

  const isSaving = create.isPending || update.isPending;
  const activeCount = agents.filter((a) => a.is_active).length;

  return (
    <AppLayout>
      <div className="p-6 lg:p-8">

        {/* ── Page Header ──────────────────────────────────── */}
        <header className="mb-8 flex items-start justify-between gap-4 flex-wrap">
          <div>
            <span className="acm-breadcrumb">/ agents</span>
            <h1 className="text-[22px] font-semibold tracking-[-0.01em]" style={{ color: 'var(--acm-fg)' }}>
              Autonomous Agents
            </h1>
            <p className="text-[12px] mt-1" style={{ color: 'var(--acm-fg-3)' }}>
              {agents.length} agents · {activeCount} active
            </p>
          </div>
          <button onClick={openCreate} className="btn-primary">
            <Plus size={14} /> New Agent
          </button>
        </header>

        {/* ── Content ──────────────────────────────────────── */}
        {isLoading ? (
          <div className="flex items-center justify-center py-20">
            <Loader2 size={24} className="animate-spin" style={{ color: 'var(--acm-fg-4)' }} />
          </div>
        ) : agents.length === 0 ? (
          /* Empty state */
          <div
            className="flex flex-col items-center justify-center py-24 text-center rounded-xl"
            style={{ border: '1px dashed var(--acm-border)' }}
          >
            <div
              className="w-16 h-16 rounded-full flex items-center justify-center mb-5"
              style={{ background: 'var(--acm-elev)' }}
            >
              <Bot size={30} style={{ color: 'var(--acm-fg-4)' }} />
            </div>
            <h3 className="text-[15px] font-medium mb-2" style={{ color: 'var(--acm-fg-2)' }}>
              No agents yet
            </h3>
            <p className="text-[13px] max-w-sm mb-2" style={{ color: 'var(--acm-fg-4)' }}>
              Create an agent with its own rules and connect it to any service via webhook.
            </p>
            <p className="text-[12px] mb-6 flex items-center gap-1.5" style={{ color: 'var(--acm-accent-dim)' }}>
              <Sparkles size={12} /> Try generating one with AI
            </p>
            <button onClick={openCreate} className="btn-primary">
              <Plus size={14} /> Create your first agent
            </button>
          </div>
        ) : (
          /* Agent grid */
          <div className="grid gap-4" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(340px, 1fr))' }}>
            {agents.map((agent) => (
              <AgentCard
                key={agent.id}
                agent={agent}
                onEdit={openEdit}
                onDelete={handleDelete}
                onToggle={handleToggle}
              />
            ))}
          </div>
        )}
      </div>

      {/* ── Create / Edit Modal ───────────────────────────── */}
      {modal && (
        <AgentFormModal
          initial={editing}
          onSave={handleSave}
          onClose={closeModal}
          isSaving={isSaving}
        />
      )}

      {/* ── One-time secret reveal after create ──────────── */}
      {pendingSecret && (
        <div className="fixed inset-0 bg-black/70 backdrop-blur-sm flex items-center justify-center z-50 p-4">
          <div
            className="w-full max-w-md p-6 rounded-2xl"
            style={{
              background: 'var(--acm-base)',
              border: '1px solid var(--acm-border-strong)',
            }}
          >
            <div className="flex items-center gap-3 mb-4">
              <Key size={20} style={{ color: 'var(--acm-ok)' }} />
              <h2 className="text-[16px] font-semibold" style={{ color: 'var(--acm-fg)' }}>
                Save your secret key
              </h2>
            </div>
            <p className="text-[13px] mb-4" style={{ color: 'var(--acm-fg-3)' }}>
              This is the{' '}
              <strong style={{ color: 'var(--acm-fg)' }}>only time</strong> your webhook
              secret for{' '}
              <strong style={{ color: 'var(--acm-fg)' }}>{pendingSecret.name}</strong> will
              be shown. Copy it now — you can always retrieve it again from the agent card.
            </p>

            <div
              className="flex items-center gap-2 rounded-xl px-4 py-3 mb-5"
              style={{ background: 'var(--acm-elev)', border: '1px solid var(--acm-border)' }}
            >
              <code
                className="mono flex-1 text-[13px] break-all"
                style={{ color: 'var(--acm-ok)' }}
              >
                {pendingSecret.secret}
              </code>
              <button
                onClick={() => {
                  navigator.clipboard.writeText(pendingSecret.secret);
                  toast.success('Copied!');
                }}
                className="p-1.5 transition-colors shrink-0"
                style={{ color: 'var(--acm-fg-4)' }}
                onMouseEnter={e => (e.currentTarget.style.color = 'var(--acm-fg)')}
                onMouseLeave={e => (e.currentTarget.style.color = 'var(--acm-fg-4)')}
              >
                <Copy size={15} />
              </button>
            </div>

            <p className="text-[12px] mb-5" style={{ color: 'var(--acm-fg-4)' }}>
              Use it as the{' '}
              <code
                className="mono px-1 rounded text-[11px]"
                style={{ color: 'var(--acm-fg-3)', background: 'var(--acm-elev)' }}
              >
                X-Agent-Secret
              </code>{' '}
              header when calling the webhook endpoint.
            </p>

            <button
              onClick={() => setPendingSecret(null)}
              className="btn-primary w-full justify-center py-2.5"
            >
              Got it, I saved it
            </button>
          </div>
        </div>
      )}
    </AppLayout>
  );
}
