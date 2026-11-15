'use client';

import { useState } from 'react';
import { AppLayout } from '@/components/layout/app-layout';
import { useAgents, useAgentMutations, type Agent, type AgentFormData } from '@/hooks/use-agents';
import { Bot, Plus, Trash2, Edit2, Power, PowerOff, Send, Copy, Check, Loader2, Key, Globe, X, Sparkles } from 'lucide-react';
import { toast } from 'sonner';
import { AgentFormModal } from '@/components/agents/agent-form';
import { AgentDetailView, TestPanel } from '@/components/agents/agent-detail';

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

  const [modal, setModal] = useState<'create' | null>(null);
  const [viewingAgent, setViewingAgent] = useState<Agent | null>(null);
  const [pendingSecret, setPendingSecret] = useState<{ name: string; secret: string } | null>(null);

  const openCreate = () => setModal('create');
  const openEdit = (a: Agent) => setViewingAgent(a);
  const closeModal = () => setModal(null);

  const handleSave = async (data: AgentFormData) => {
    try {
      const res = await create.mutateAsync(data);
      closeModal();
      // Show the secret once after creation
      if (res?.webhook_secret) {
        setPendingSecret({ name: res.name, secret: res.webhook_secret });
      }
      toast.success('Agent created');
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

        {viewingAgent ? (
          <AgentDetailView agent={viewingAgent} onClose={() => setViewingAgent(null)} />
        ) : (
          <>
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
          </>
        )}
      </div>

      {/* ── Create Modal ───────────────────────────── */}
      {modal && (
        <AgentFormModal
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

// ── Tools / Skills Tabs ──
