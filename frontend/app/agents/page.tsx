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
    <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50 p-4">
      <div className="bg-slate-900 rounded-2xl border border-slate-700 w-full max-w-2xl max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between p-6 border-b border-slate-800">
          <h2 className="text-lg font-semibold text-white">
            {initial ? 'Edit Agent' : 'New Agent'}
          </h2>
          <button onClick={onClose} className="text-slate-400 hover:text-white">
            <X size={20} />
          </button>
        </div>

        <div className="p-6 space-y-4">

          {/* ── AI Generator ───────────────────────────────── */}
          <div className="bg-slate-800/60 border border-violet-500/20 rounded-xl p-4 space-y-3">
            <p className="text-xs font-semibold text-violet-300 flex items-center gap-1.5">
              <Sparkles size={13} /> Generate with AI
            </p>

            <textarea
              value={genDescription}
              onChange={(e) => setGenDescription(e.target.value)}
              placeholder="Describe what your agent should do... e.g. 'A support bot for my clothing store that always responds in Spanish and redirects billing questions to support@mystore.com'"
              rows={3}
              className="w-full px-3 py-2.5 bg-slate-900 border border-slate-700 rounded-lg text-white placeholder-slate-500 text-sm focus:outline-none focus:ring-2 focus:ring-violet-500 resize-none"
            />

            {/* Drop zone */}
            <div
              onDragOver={(e) => { e.preventDefault(); setIsDragging(true); }}
              onDragLeave={() => setIsDragging(false)}
              onDrop={onDrop}
              className={cn(
                'relative border-2 border-dashed rounded-lg px-4 py-3 transition-colors',
                isDragging
                  ? 'border-violet-400 bg-violet-500/10'
                  : 'border-slate-700 hover:border-slate-600'
              )}
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
                    <div key={f.name} className="flex items-center gap-2 text-sm text-slate-300">
                      <FileText size={14} className="text-violet-400 shrink-0" />
                      <span className="font-mono truncate flex-1 text-xs">{f.name}</span>
                      <button
                        onClick={(e) => { e.stopPropagation(); removeFile(f.name); }}
                        className="text-slate-500 hover:text-red-400 shrink-0"
                      >
                        <X size={13} />
                      </button>
                    </div>
                  ))}
                  <button
                    onClick={() => document.getElementById('agent-file-input')?.click()}
                    className="flex items-center gap-1.5 text-xs text-violet-400 hover:text-violet-300 mt-1"
                  >
                    <Upload size={12} /> Add more files
                  </button>
                </div>
              ) : (
                <div
                  className="flex items-center justify-center gap-2 text-xs text-slate-500 cursor-pointer py-1"
                  onClick={() => document.getElementById('agent-file-input')?.click()}
                >
                  <Upload size={14} />
                  Drop PDFs, TXTs or MDs for extra context (optional, multiple allowed)
                </div>
              )}
            </div>

            <button
              onClick={handleGenerate}
              disabled={generate.isPending || !genDescription.trim()}
              className="flex items-center gap-2 px-4 py-2 bg-violet-600 hover:bg-violet-700 disabled:opacity-50 disabled:cursor-not-allowed text-white text-xs font-medium rounded-lg transition-colors"
            >
              {generate.isPending
                ? <><Loader2 size={13} className="animate-spin" /> Generating...</>
                : <><Sparkles size={13} /> Generate rules</>}
            </button>
          </div>

          {/* ── Manual fields ─────────────────────────────── */}
          <div>
            <label className="block text-sm font-medium text-slate-300 mb-1.5">Name *</label>
            <input
              value={form.name}
              onChange={(e) => set('name', e.target.value)}
              placeholder="e.g. Support Bot, Sales Assistant..."
              className="w-full px-4 py-2.5 bg-slate-800 border border-slate-700 rounded-lg text-white placeholder-slate-500 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-slate-300 mb-1.5">Description</label>
            <input
              value={form.description}
              onChange={(e) => set('description', e.target.value)}
              placeholder="What does this agent do?"
              className="w-full px-4 py-2.5 bg-slate-800 border border-slate-700 rounded-lg text-white placeholder-slate-500 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-slate-300 mb-1.5">
              System Prompt (rules) *
            </label>
            <textarea
              value={form.system_prompt}
              onChange={(e) => set('system_prompt', e.target.value)}
              placeholder={`You are a friendly support assistant for Acme Corp.\n\nRules:\n- Always respond in Spanish\n- Never reveal internal pricing\n- If asked about refunds, direct to support@acme.com`}
              rows={8}
              className="w-full px-4 py-2.5 bg-slate-800 border border-slate-700 rounded-lg text-white placeholder-slate-500 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 resize-y font-mono"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-slate-300 mb-1.5">Tools access</label>
            <select
              value={form.allowed_tools}
              onChange={(e) => set('allowed_tools', e.target.value)}
              className="w-full px-4 py-2.5 bg-slate-800 border border-slate-700 rounded-lg text-white text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              {TOOLS_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
            <p className="text-xs text-slate-500 mt-1">
              "All tools" lets the agent run commands, search the web, etc.
              Choose "No tools" for pure text/FAQ bots.
            </p>
          </div>

          <button
            type="button"
            onClick={() => setShowAdvanced(!showAdvanced)}
            className="flex items-center gap-1.5 text-xs text-slate-400 hover:text-slate-200"
          >
            {showAdvanced ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
            Advanced options
          </button>

          {showAdvanced && (
            <div>
              <label className="block text-sm font-medium text-slate-300 mb-1.5">
                Telegram Bot Token (optional)
              </label>
              <input
                value={form.telegram_token}
                onChange={(e) => set('telegram_token', e.target.value)}
                placeholder="1234567890:ABCdef..."
                className="w-full px-4 py-2.5 bg-slate-800 border border-slate-700 rounded-lg text-white placeholder-slate-500 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 font-mono"
              />
              <p className="text-xs text-slate-500 mt-1">
                Connect this agent to its own Telegram bot (coming soon).
              </p>
            </div>
          )}
        </div>

        <div className="flex justify-end gap-3 px-6 pb-6">
          <button
            onClick={onClose}
            className="px-4 py-2 text-sm text-slate-400 hover:text-white border border-slate-700 rounded-lg transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={() => onSave(form)}
            disabled={isSaving || !form.name.trim() || !form.system_prompt.trim()}
            className="flex items-center gap-2 px-5 py-2 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed text-white text-sm font-medium rounded-lg transition-colors"
          >
            {isSaving && <Loader2 size={14} className="animate-spin" />}
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
    <div className="border-t border-slate-800 mt-4 pt-4">
      <p className="text-xs font-medium text-slate-400 mb-3 flex items-center gap-1.5">
        <Send size={12} /> Test this agent
      </p>

      {messages.length > 0 && (
        <div className="space-y-2 mb-3 max-h-48 overflow-y-auto">
          {messages.map((m, i) => (
            <div
              key={i}
              className={cn(
                'text-xs px-3 py-2 rounded-lg max-w-[90%]',
                m.role === 'user'
                  ? 'ml-auto bg-blue-600/20 text-blue-200 border border-blue-600/30'
                  : 'bg-slate-800 text-slate-300'
              )}
            >
              {m.text}
            </div>
          ))}
          {test.isPending && (
            <div className="flex items-center gap-1.5 text-xs text-slate-500">
              <Loader2 size={12} className="animate-spin" /> Thinking...
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
          className="flex-1 px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-white placeholder-slate-500 text-xs focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-50"
        />
        <button
          onClick={send}
          disabled={test.isPending || !input.trim()}
          className="p-2 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white rounded-lg transition-colors"
        >
          <Send size={14} />
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
      className={cn(
        'bg-slate-900 rounded-xl border p-5 transition-all',
        agent.is_active
          ? 'border-slate-800 hover:border-slate-700'
          : 'border-slate-800/40 opacity-60'
      )}
    >
      {/* Header */}
      <div className="flex items-start justify-between mb-3">
        <div className="flex items-center gap-3">
          <div
            className={cn(
              'w-11 h-11 rounded-xl flex items-center justify-center',
              agent.is_active ? 'bg-emerald-600/20' : 'bg-slate-800'
            )}
          >
            <Bot size={22} className={agent.is_active ? 'text-emerald-400' : 'text-slate-500'} />
          </div>
          <div>
            <h3 className="font-semibold text-white">{agent.name}</h3>
            {agent.description && (
              <p className="text-xs text-slate-500 mt-0.5">{agent.description}</p>
            )}
          </div>
        </div>
        <div className="flex items-center gap-1.5">
          <span
            className={cn(
              'text-xs px-2 py-0.5 rounded-full font-medium',
              agent.is_active
                ? 'bg-emerald-500/20 text-emerald-400'
                : 'bg-slate-700 text-slate-400'
            )}
          >
            {agent.is_active ? 'Active' : 'Inactive'}
          </span>
        </div>
      </div>

      {/* System prompt preview */}
      <p className="text-xs text-slate-500 line-clamp-2 mb-4 font-mono bg-slate-800/50 rounded-lg px-3 py-2">
        {agent.system_prompt}
      </p>

      {/* Tools badge */}
      <div className="flex items-center gap-2 mb-4">
        <span className="text-xs bg-slate-800 text-slate-400 px-2 py-0.5 rounded-full">
          Tools: {agent.allowed_tools === 'all' ? 'All' : agent.allowed_tools === 'none' ? 'None' : 'Custom'}
        </span>
      </div>

      {/* Webhook URL */}
      <div className="mb-4">
        <p className="text-xs text-slate-500 mb-1 flex items-center gap-1">
          <Globe size={11} /> Webhook URL
        </p>
        <div className="flex items-center gap-2">
          <code className="flex-1 text-xs text-slate-400 bg-slate-800 px-2 py-1.5 rounded-lg truncate font-mono">
            {webhookUrl}
          </code>
          <button
            onClick={() => { navigator.clipboard.writeText(webhookUrl); toast.success('Copied!'); }}
            className="p-1.5 text-slate-400 hover:text-white bg-slate-800 rounded-lg"
          >
            <Copy size={12} />
          </button>
        </div>
      </div>

      {/* Secret */}
      <div className="mb-4">
        <p className="text-xs text-slate-500 mb-1 flex items-center gap-1">
          <Key size={11} /> X-Agent-Secret header
        </p>
        {showSecret ? (
          <div className="flex items-center gap-2">
            <code className="flex-1 text-xs text-emerald-400 bg-slate-800 px-2 py-1.5 rounded-lg truncate font-mono">
              {secret}
            </code>
            <button onClick={copySecret} className="p-1.5 text-slate-400 hover:text-white bg-slate-800 rounded-lg">
              {copied ? <Check size={12} className="text-emerald-400" /> : <Copy size={12} />}
            </button>
          </div>
        ) : (
          <button
            onClick={revealSecret}
            disabled={getSecret.isPending}
            className="text-xs text-blue-400 hover:text-blue-300 flex items-center gap-1"
          >
            {getSecret.isPending ? <Loader2 size={11} className="animate-spin" /> : <Key size={11} />}
            Reveal secret
          </button>
        )}
      </div>

      {/* Actions */}
      <div className="flex items-center gap-2 pt-3 border-t border-slate-800">
        <button
          onClick={() => onToggle(agent.id, !agent.is_active)}
          title={agent.is_active ? 'Deactivate' : 'Activate'}
          className={cn(
            'flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors',
            agent.is_active
              ? 'bg-slate-800 text-slate-400 hover:bg-red-500/20 hover:text-red-400'
              : 'bg-slate-800 text-slate-400 hover:bg-emerald-500/20 hover:text-emerald-400'
          )}
        >
          {agent.is_active ? <PowerOff size={13} /> : <Power size={13} />}
          {agent.is_active ? 'Deactivate' : 'Activate'}
        </button>

        <button
          onClick={() => onEdit(agent)}
          className="flex items-center gap-1.5 px-3 py-1.5 bg-slate-800 text-slate-400 hover:text-white rounded-lg text-xs font-medium transition-colors"
        >
          <Edit2 size={13} /> Edit
        </button>

        <button
          onClick={() => setShowTest(!showTest)}
          className={cn(
            'flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ml-auto',
            showTest
              ? 'bg-blue-600/20 text-blue-400'
              : 'bg-slate-800 text-slate-400 hover:text-white'
          )}
        >
          <Send size={13} /> Test
        </button>

        <button
          onClick={() => onDelete(agent.id)}
          className="p-1.5 text-slate-600 hover:text-red-400 bg-slate-800 rounded-lg transition-colors"
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

  return (
    <AppLayout>
      <div className="p-6 lg:p-8">
        {/* Header */}
        <header className="mb-8 flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold text-white flex items-center gap-3">
              <Bot size={28} className="text-emerald-400" />
              Autonomous Agents
            </h1>
            <p className="text-slate-400 mt-1 text-sm">
              Independent bots with their own rules — connect via webhook or Telegram.
            </p>
          </div>
          <button
            onClick={openCreate}
            className="flex items-center gap-2 px-4 py-2.5 bg-emerald-600 hover:bg-emerald-700 text-white text-sm font-medium rounded-xl transition-colors"
          >
            <Plus size={16} /> New Agent
          </button>
        </header>

        {/* Content */}
        {isLoading ? (
          <div className="flex items-center justify-center py-20">
            <Loader2 size={28} className="text-slate-400 animate-spin" />
          </div>
        ) : agents.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-24 text-center">
            <div className="w-20 h-20 bg-slate-800 rounded-full flex items-center justify-center mb-5">
              <Bot size={36} className="text-slate-500" />
            </div>
            <h3 className="text-lg font-medium text-slate-300 mb-2">No agents yet</h3>
            <p className="text-sm text-slate-500 max-w-sm mb-6">
              Create an agent with its own rules and connect it to any service via webhook.
            </p>
            <button
              onClick={openCreate}
              className="flex items-center gap-2 px-5 py-2.5 bg-emerald-600 hover:bg-emerald-700 text-white text-sm font-medium rounded-xl transition-colors"
            >
              <Plus size={16} /> Create your first agent
            </button>
          </div>
        ) : (
          <div className="grid grid-cols-1 lg:grid-cols-2 xl:grid-cols-3 gap-5">
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

      {/* Create / Edit Modal */}
      {modal && (
        <AgentFormModal
          initial={editing}
          onSave={handleSave}
          onClose={closeModal}
          isSaving={isSaving}
        />
      )}

      {/* One-time secret reveal after create */}
      {pendingSecret && (
        <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50 p-4">
          <div className="bg-slate-900 rounded-2xl border border-emerald-500/40 w-full max-w-md p-6">
            <div className="flex items-center gap-3 mb-4">
              <Key size={22} className="text-emerald-400" />
              <h2 className="text-lg font-semibold text-white">Save your secret key</h2>
            </div>
            <p className="text-sm text-slate-400 mb-4">
              This is the <strong className="text-white">only time</strong> your webhook secret for{' '}
              <strong className="text-white">{pendingSecret.name}</strong> will be shown.
              Copy it now — you can always get it again from the agent card.
            </p>
            <div className="flex items-center gap-2 bg-slate-800 rounded-xl px-4 py-3 mb-5">
              <code className="flex-1 text-sm text-emerald-400 font-mono break-all">
                {pendingSecret.secret}
              </code>
              <button
                onClick={() => {
                  navigator.clipboard.writeText(pendingSecret.secret);
                  toast.success('Copied!');
                }}
                className="p-1.5 text-slate-400 hover:text-white"
              >
                <Copy size={16} />
              </button>
            </div>
            <p className="text-xs text-slate-500 mb-5">
              Use it as the <code className="text-slate-300 bg-slate-800 px-1 rounded">X-Agent-Secret</code> header
              when calling the webhook endpoint.
            </p>
            <button
              onClick={() => setPendingSecret(null)}
              className="w-full py-2.5 bg-emerald-600 hover:bg-emerald-700 text-white font-medium rounded-xl transition-colors text-sm"
            >
              Got it, I saved it
            </button>
          </div>
        </div>
      )}
    </AppLayout>
  );
}
