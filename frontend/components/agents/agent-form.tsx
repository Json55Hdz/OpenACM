'use client';

import { useState } from 'react';
import { useAgentMutations, type Agent, type AgentFormData } from '@/hooks/use-agents';
import { Bot, Loader2, ChevronDown, ChevronUp, X, Sparkles, FileText, Upload } from 'lucide-react';
import { toast } from 'sonner';
import { cn, TOOLS_OPTIONS, DEFAULT_FORM } from './shared';

export function AgentFormModal({
  onSave,
  onClose,
  isSaving,
}: {
  onSave: (data: AgentFormData) => void;
  onClose: () => void;
  isSaving: boolean;
}) {
  const { generate } = useAgentMutations();
  const [form, setForm] = useState<AgentFormData>(DEFAULT_FORM);
  const [genDescription, setGenDescription] = useState('');
  const [droppedFiles, setDroppedFiles] = useState<File[]>([]);
  const [isDragging, setIsDragging] = useState(false);
  const [showAdvanced, setShowAdvanced] = useState(false);

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
            New Agent
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
            <div className="space-y-4">
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

              <MemoryModeField form={form} set={set} />
              <InactivityFollowUpField form={form} set={set} />
              <ShowInChatField form={form} set={set} />
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
            Create Agent
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Memory mode field (shared by create + edit forms) ─────────────────────────

export function MemoryModeField({
  form,
  set,
}: {
  form: AgentFormData;
  set: (key: keyof AgentFormData, value: string | number) => void;
}) {
  return (
    <div>
      <label className="label block mb-2">Memory</label>
      <select
        value={form.memory_mode}
        onChange={(e) => set('memory_mode', e.target.value)}
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
        <option value="persistent" style={{ background: 'var(--acm-card)' }}>
          Persistent — always remember this conversation
        </option>
        <option value="session_ttl" style={{ background: 'var(--acm-card)' }}>
          Reset after inactivity
        </option>
      </select>

      {form.memory_mode === 'session_ttl' && (
        <div className="mt-3 flex items-center gap-2">
          <input
            type="number"
            min={1}
            value={form.memory_ttl_hours}
            onChange={(e) => set('memory_ttl_hours', Math.max(1, parseInt(e.target.value, 10) || 1))}
            className="acm-input w-24"
          />
          <span className="text-[13px]" style={{ color: 'var(--acm-fg-3)' }}>
            hours of inactivity before starting a new conversation
          </span>
        </div>
      )}
      <p className="text-[11px] mt-1.5" style={{ color: 'var(--acm-fg-4)' }}>
        {form.memory_mode === 'persistent'
          ? "This agent never forgets a chat, no matter how much time passes between messages."
          : "If a chat goes quiet past this window, the agent starts fresh on the next message. Old messages stay visible in history — they're just no longer used as context."}
      </p>
    </div>
  );
}

// ── Inactivity follow-up field ───────────────────────────────────────────────

export function InactivityFollowUpField({
  form,
  set,
}: {
  form: AgentFormData;
  set: (key: keyof AgentFormData, value: string | number) => void;
}) {
  return (
    <div className="space-y-2">
      <label className="label block">Inactivity Follow-up (Nudge)</label>
      <div className="flex items-center gap-2">
        <input
          type="number"
          min={0}
          value={form.inactivity_timeout_minutes}
          onChange={(e) => set('inactivity_timeout_minutes', Math.max(0, parseInt(e.target.value, 10) || 0))}
          className="acm-input w-24"
        />
        <span className="text-[13px]" style={{ color: 'var(--acm-fg-3)' }}>
          minutes of silence before sending follow-up (0 = disabled)
        </span>
      </div>
      {form.inactivity_timeout_minutes > 0 && (
        <div className="space-y-1 mt-2">
          <label className="text-[11px] font-medium" style={{ color: 'var(--acm-fg-3)' }}>
            Custom message template (optional, supports {'{name}'}):
          </label>
          <textarea
            value={form.inactivity_message}
            onChange={(e) => set('inactivity_message', e.target.value)}
            rows={2}
            placeholder="Leave blank to use default friendly follow-up message"
            className="acm-input w-full text-[13px] resize-y"
          />
        </div>
      )}
      <p className="text-[11px]" style={{ color: 'var(--acm-fg-4)' }}>
        Automatically sends a proactive follow-up reminder to customers on WhatsApp if they stop responding during a conversation.
      </p>
    </div>
  );
}

export function ShowInChatField({
  form,
  set,
}: {
  form: AgentFormData;
  set: (key: keyof AgentFormData, value: boolean) => void;
}) {
  const isChecked = form.show_in_chat ?? true;
  return (
    <div
      className="flex items-center justify-between p-3 rounded-lg cursor-pointer transition-colors"
      style={{
        border: '1px solid var(--acm-border)',
        background: 'var(--acm-elev)',
      }}
      onClick={() => set('show_in_chat', !isChecked)}
    >
      <div className="space-y-0.5 pr-4">
        <label className="text-[13px] font-medium block cursor-pointer" style={{ color: 'var(--acm-fg)' }}>
          Show in chat list
        </label>
        <p className="text-[11px]" style={{ color: 'var(--acm-fg-4)' }}>
          Display this agent's folder and conversations in the /chat sidebar.
        </p>
      </div>
      <button
        type="button"
        role="switch"
        aria-checked={isChecked}
        onClick={(e) => {
          e.stopPropagation();
          set('show_in_chat', !isChecked);
        }}
        className={cn(
          'relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-none',
          isChecked ? 'bg-[var(--acm-accent)]' : 'bg-zinc-700'
        )}
      >
        <span
          className={cn(
            'pointer-events-none inline-block h-4 w-4 transform rounded-full bg-white shadow ring-0 transition duration-200 ease-in-out',
            isChecked ? 'translate-x-4' : 'translate-x-0'
          )}
        />
      </button>
    </div>
  );
}

// ── Agent Detail View (in-place, replaces the grid — not an overlay) ──────────
