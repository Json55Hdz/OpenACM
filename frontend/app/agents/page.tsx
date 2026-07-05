'use client';

import { useState, useRef, useEffect } from 'react';
import { AppLayout } from '@/components/layout/app-layout';
import {
  useAgents, useAgentMutations, useAgentKnowledge, useAgentKnowledgeMutations,
  useAgentChannels, useAgentChannelMutations,
  useAgentSkills, useToggleAgentGlobalSkill, useGenerateAgentSkill, useToggleAgentPrivateSkill, useDeleteAgentPrivateSkill,
  type Agent, type AgentFormData, type KnowledgeItem, type ChannelItem,
} from '@/hooks/use-agents';
import { useTools, type ToolInfo } from '@/hooks/use-api';
import { useAgentFlows, useCreateFlow, useUpdateFlow, useDeleteFlow } from '@/hooks/use-agent-flows';
import { parseAllowedTools, serializeAllowedTools } from '@/hooks/use-worker-config';
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
  BookOpen,
  Pencil,
  AlertTriangle,
  Radio,
  RefreshCw,
  Search,
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

// ── Knowledge Tab ─────────────────────────────────────────────────────────────

function KnowledgeTab({ agentId }: { agentId: number }) {
  const { data: items = [], isLoading } = useAgentKnowledge(agentId);
  const { addText, addFile, updateItem, removeItem } = useAgentKnowledgeMutations(agentId);

  const [showTextForm, setShowTextForm] = useState(false);
  const [textTitle, setTextTitle] = useState('');
  const [textContent, setTextContent] = useState('');
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editTitle, setEditTitle] = useState('');
  const [editContent, setEditContent] = useState('');
  const [deletingId, setDeletingId] = useState<number | null>(null);

  const totalChars = items.reduce((sum, i) => sum + (i.char_count ?? 0), 0);

  const handleAddText = async () => {
    if (!textTitle.trim() || !textContent.trim()) return;
    try {
      await addText.mutateAsync({ title: textTitle.trim(), content: textContent.trim() });
      setTextTitle('');
      setTextContent('');
      setShowTextForm(false);
      toast.success('Sección de texto agregada');
    } catch (err: any) {
      toast.error(err.message || 'Error al agregar la sección');
    }
  };

  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    try {
      await addFile.mutateAsync({ file });
      toast.success(`Archivo "${file.name}" procesado`);
    } catch (err: any) {
      toast.error(err.message || 'Error al procesar el archivo');
    }
    e.target.value = '';
  };

  const startEdit = (item: KnowledgeItem) => {
    setEditingId(item.id);
    setEditTitle(item.title);
    setEditContent('');
  };

  const handleUpdate = async (item: KnowledgeItem) => {
    const updates: { title?: string; content?: string } = {};
    if (editTitle.trim() && editTitle !== item.title) updates.title = editTitle.trim();
    if (item.type === 'text' && editContent.trim()) updates.content = editContent.trim();
    if (Object.keys(updates).length === 0) { setEditingId(null); return; }
    await updateItem.mutateAsync({ kid: item.id, ...updates });
    setEditingId(null);
    toast.success('Item actualizado');
  };

  const handleDelete = async (kid: number) => {
    try {
      setDeletingId(kid);
      await removeItem.mutateAsync(kid);
      toast.success('Item eliminado');
    } catch (err: any) {
      toast.error(err.message || 'Error al eliminar el item');
    } finally {
      setDeletingId(null);
    }
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12 text-zinc-500">
        <Loader2 className="w-5 h-5 animate-spin mr-2" />
        Cargando conocimiento…
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Actions */}
      <div className="flex gap-2">
        <button
          onClick={() => setShowTextForm((v) => !v)}
          className="flex items-center gap-1.5 px-3 py-1.5 text-sm rounded-lg border border-zinc-700 text-zinc-300 hover:bg-zinc-800 transition-colors"
        >
          <Plus className="w-3.5 h-3.5" />
          Agregar texto
        </button>
        <label className="flex items-center gap-1.5 px-3 py-1.5 text-sm rounded-lg border border-zinc-700 text-zinc-300 hover:bg-zinc-800 transition-colors cursor-pointer">
          <Upload className="w-3.5 h-3.5" />
          {addFile.isPending ? 'Procesando…' : 'Subir archivo'}
          <input
            type="file"
            className="hidden"
            accept=".pdf,.docx,.xlsx,.pptx,.txt,.md,.csv,.json,.yaml,.yml"
            onChange={handleFileChange}
            disabled={addFile.isPending}
          />
        </label>
      </div>

      {/* Inline text form */}
      {showTextForm && (
        <div className="border border-zinc-700 rounded-lg p-3 space-y-2 bg-zinc-900/50">
          <input
            value={textTitle}
            onChange={(e) => setTextTitle(e.target.value)}
            placeholder="Título (ej: Política de devoluciones)"
            className="w-full bg-zinc-800 border border-zinc-700 rounded px-3 py-1.5 text-sm text-zinc-100 placeholder-zinc-500 focus:outline-none focus:border-zinc-500"
          />
          <textarea
            value={textContent}
            onChange={(e) => setTextContent(e.target.value)}
            placeholder="Contenido…"
            rows={4}
            className="w-full bg-zinc-800 border border-zinc-700 rounded px-3 py-1.5 text-sm text-zinc-100 placeholder-zinc-500 focus:outline-none focus:border-zinc-500 resize-none"
          />
          <div className="flex gap-2">
            <button
              onClick={handleAddText}
              disabled={addText.isPending || !textTitle.trim() || !textContent.trim()}
              className="px-3 py-1.5 text-sm bg-blue-600 hover:bg-blue-700 disabled:opacity-50 rounded-lg text-white transition-colors"
            >
              {addText.isPending ? 'Guardando…' : 'Guardar'}
            </button>
            <button
              onClick={() => { setShowTextForm(false); setTextTitle(''); setTextContent(''); }}
              className="px-3 py-1.5 text-sm text-zinc-400 hover:text-zinc-200 transition-colors"
            >
              Cancelar
            </button>
          </div>
        </div>
      )}

      {/* Items list */}
      {items.length === 0 && !showTextForm && (
        <div className="text-center py-8 text-zinc-500 text-sm">
          <BookOpen className="w-8 h-8 mx-auto mb-2 opacity-40" />
          Agrega documentos o secciones de texto para que tu agente tenga contexto al responder.
        </div>
      )}

      {items.map((item) => (
        <div key={item.id} className="border border-zinc-700 rounded-lg p-3 bg-zinc-900/30">
          {editingId === item.id ? (
            <div className="space-y-2">
              <input
                value={editTitle}
                onChange={(e) => setEditTitle(e.target.value)}
                className="w-full bg-zinc-800 border border-zinc-700 rounded px-3 py-1.5 text-sm text-zinc-100 focus:outline-none focus:border-zinc-500"
              />
              {item.type === 'text' && (
                <textarea
                  value={editContent}
                  onChange={(e) => setEditContent(e.target.value)}
                  placeholder="Nuevo contenido (dejar vacío para no cambiar)"
                  rows={4}
                  className="w-full bg-zinc-800 border border-zinc-700 rounded px-3 py-1.5 text-sm text-zinc-100 placeholder-zinc-500 focus:outline-none focus:border-zinc-500 resize-none"
                />
              )}
              <div className="flex gap-2">
                <button
                  onClick={() => handleUpdate(item)}
                  disabled={updateItem.isPending}
                  className="px-3 py-1 text-xs bg-blue-600 hover:bg-blue-700 disabled:opacity-50 rounded text-white transition-colors"
                >
                  {updateItem.isPending ? 'Guardando…' : 'Guardar'}
                </button>
                <button
                  onClick={() => setEditingId(null)}
                  className="px-3 py-1 text-xs text-zinc-400 hover:text-zinc-200 transition-colors"
                >
                  Cancelar
                </button>
              </div>
            </div>
          ) : (
            <div className="flex items-start justify-between gap-2">
              <div className="flex items-start gap-2 min-w-0">
                {item.type === 'file' ? (
                  <FileText className="w-4 h-4 text-blue-400 mt-0.5 flex-shrink-0" />
                ) : (
                  <BookOpen className="w-4 h-4 text-purple-400 mt-0.5 flex-shrink-0" />
                )}
                <div className="min-w-0">
                  <p className="text-sm text-zinc-100 truncate">{item.title}</p>
                  <p className="text-xs text-zinc-500 mt-0.5">
                    {item.type === 'file' ? item.filename : 'Texto'}
                    {' · '}
                    {new Date(item.created_at).toLocaleDateString()}
                  </p>
                </div>
              </div>
              <div className="flex items-center gap-1 flex-shrink-0">
                <span className={cn(
                  'text-xs px-1.5 py-0.5 rounded font-mono',
                  item.type === 'file'
                    ? 'bg-blue-900/40 text-blue-300'
                    : 'bg-purple-900/40 text-purple-300'
                )}>
                  {item.type === 'file' ? 'FILE' : 'TEXT'}
                </span>
                <button
                  onClick={() => startEdit(item)}
                  className="p-1 text-zinc-500 hover:text-zinc-300 transition-colors"
                  title="Editar"
                >
                  <Pencil className="w-3.5 h-3.5" />
                </button>
                <button
                  onClick={() => handleDelete(item.id)}
                  disabled={deletingId === item.id}
                  className="p-1 text-zinc-500 hover:text-red-400 transition-colors"
                  title="Eliminar"
                >
                  <Trash2 className="w-3.5 h-3.5" />
                </button>
              </div>
            </div>
          )}
        </div>
      ))}

      {/* Char counter footer */}
      {items.length > 0 && (
        <p className={cn(
          'text-xs text-right',
          totalChars >= 40_000 ? 'text-red-400' : totalChars >= 30_000 ? 'text-yellow-400' : 'text-zinc-600'
        )}>
          {totalChars >= 40_000 && <AlertTriangle className="w-3 h-3 inline mr-1" />}
          {totalChars.toLocaleString()} caracteres
          {totalChars >= 40_000 && ' — se truncará al enviar'}
          {totalChars >= 30_000 && totalChars < 40_000 && ' — cerca del límite (40k)'}
          {' · '}
          {items.length} {items.length === 1 ? 'item' : 'items'}
        </p>
      )}
    </div>
  );
}

// ── Channels Tab ──────────────────────────────────────────────────────────────

const WEBHOOK_CURL = `curl -X POST https://tu-dominio.com/webhooks/whatsapp \\
  -H "Content-Type: application/json" \\
  -d '{"entry":[{"changes":[{"value":{"metadata":{"phone_number_id":"TU_PHONE_ID"},"messages":[{"from":"521234567890","type":"text","text":{"body":"Hola"},"id":"wamid.test1"}]}}]}]}'`;

const WEBHOOK_PYTHON = `import requests
requests.post("https://tu-dominio.com/webhooks/whatsapp", json={
    "entry": [{"changes": [{"value": {
        "metadata": {"phone_number_id": "TU_PHONE_ID"},
        "messages": [{"from": "521234567890", "type": "text",
                      "text": {"body": "Hola"}, "id": "wamid.test1"}]
    }}]}]
})`;

const WEBHOOK_JS = `fetch("https://tu-dominio.com/webhooks/whatsapp", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ entry: [{ changes: [{ value: {
    metadata: { phone_number_id: "TU_PHONE_ID" },
    messages: [{ from: "521234567890", type: "text",
                 text: { body: "Hola" }, id: "wamid.test1" }]
  }}]}]})
})`;

function ChannelsTab({ agentId }: { agentId: number }) {
  const { data: channels = [], isLoading } = useAgentChannels(agentId);
  const { addChannel, removeChannel, restartChannel } = useAgentChannelMutations(agentId);

  const [showAddForm, setShowAddForm] = useState(false);
  const [addType, setAddType] = useState<'telegram' | 'whatsapp' | 'whatsapp_web'>('telegram');
  const [addConfig, setAddConfig] = useState<Record<string, string>>({});
  const [deletingId, setDeletingId] = useState<number | null>(null);
  const [restartingId, setRestartingId] = useState<number | null>(null);
  const [showWebhookDocs, setShowWebhookDocs] = useState(false);
  const [webhookTab, setWebhookTab] = useState<'curl' | 'python' | 'js'>('curl');
  const [copied, setCopied] = useState(false);

  const hasWhatsApp = channels.some((c) => c.type === 'whatsapp' || c.type === 'whatsapp_web') || (showAddForm && (addType === 'whatsapp' || addType === 'whatsapp_web'));

  const handleAdd = async () => {
    try {
      await addChannel.mutateAsync({ type: addType, config: addConfig });
      setShowAddForm(false);
      setAddConfig({});
      toast.success('Canal agregado');
    } catch (err: any) {
      toast.error(err.message || 'Error al agregar canal');
    }
  };

  const handleDelete = async (ch: ChannelItem) => {
    try {
      setDeletingId(ch.id);
      await removeChannel.mutateAsync(ch.id);
      toast.success('Canal eliminado');
    } catch (err: any) {
      toast.error(err.message || 'Error al eliminar');
    } finally {
      setDeletingId(null);
    }
  };

  const handleRestart = async (ch: ChannelItem) => {
    try {
      setRestartingId(ch.id);
      const res = await restartChannel.mutateAsync(ch.id);
      toast.success(res.connected ? 'Canal reconectado' : 'Canal reiniciado (desconectado)');
    } catch (err: any) {
      toast.error(err.message || 'Error al reiniciar');
    } finally {
      setRestartingId(null);
    }
  };

  const copyWebhookUrl = () => {
    navigator.clipboard.writeText('https://tu-dominio.com/webhooks/whatsapp');
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12 text-zinc-500">
        <Loader2 className="w-5 h-5 animate-spin mr-2" />
        Cargando canales…
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Add button */}
      <div className="flex gap-2">
        <button
          onClick={() => { setShowAddForm((v) => !v); setAddConfig({}); }}
          className="flex items-center gap-1.5 px-3 py-1.5 text-sm rounded-lg border border-zinc-700 text-zinc-300 hover:bg-zinc-800 transition-colors"
        >
          <Plus className="w-3.5 h-3.5" />
          Agregar canal
        </button>
      </div>

      {/* Add form */}
      {showAddForm && (
        <div className="border border-zinc-700 rounded-lg p-3 space-y-3 bg-zinc-900/50">
          <div>
            <label className="block text-xs text-zinc-400 mb-1">Tipo de canal</label>
            <select
              value={addType}
              onChange={(e) => { setAddType(e.target.value as 'telegram' | 'whatsapp' | 'whatsapp_web'); setAddConfig({}); }}
              className="w-full bg-zinc-800 border border-zinc-700 rounded px-3 py-1.5 text-sm text-zinc-100 focus:outline-none focus:border-zinc-500"
            >
              <option value="telegram">Telegram</option>
              <option value="whatsapp">WhatsApp Business</option>
              <option value="whatsapp_web">WhatsApp Web</option>
            </select>
          </div>

          {addType === 'telegram' && (
            <div>
              <label className="block text-xs text-zinc-400 mb-1">Token del bot</label>
              <input
                value={addConfig.token || ''}
                onChange={(e) => setAddConfig({ token: e.target.value })}
                placeholder="1234567890:ABCDEFabcdef..."
                className="w-full bg-zinc-800 border border-zinc-700 rounded px-3 py-1.5 text-sm text-zinc-100 placeholder-zinc-500 focus:outline-none focus:border-zinc-500"
              />
            </div>
          )}

          {addType === 'whatsapp' && (
            <>
              <div>
                <label className="block text-xs text-zinc-400 mb-1">Access Token</label>
                <input
                  value={addConfig.access_token || ''}
                  onChange={(e) => setAddConfig((c) => ({ ...c, access_token: e.target.value }))}
                  placeholder="EAAx..."
                  className="w-full bg-zinc-800 border border-zinc-700 rounded px-3 py-1.5 text-sm text-zinc-100 placeholder-zinc-500 focus:outline-none focus:border-zinc-500"
                />
              </div>
              <div>
                <label className="block text-xs text-zinc-400 mb-1">Phone Number ID</label>
                <input
                  value={addConfig.phone_number_id || ''}
                  onChange={(e) => setAddConfig((c) => ({ ...c, phone_number_id: e.target.value }))}
                  placeholder="12345678901234"
                  className="w-full bg-zinc-800 border border-zinc-700 rounded px-3 py-1.5 text-sm text-zinc-100 placeholder-zinc-500 focus:outline-none focus:border-zinc-500"
                />
              </div>
              <div>
                <label className="block text-xs text-zinc-400 mb-1">Verify Token</label>
                <input
                  value={addConfig.verify_token || ''}
                  onChange={(e) => setAddConfig((c) => ({ ...c, verify_token: e.target.value }))}
                  placeholder="mi_verify_token"
                  className="w-full bg-zinc-800 border border-zinc-700 rounded px-3 py-1.5 text-sm text-zinc-100 placeholder-zinc-500 focus:outline-none focus:border-zinc-500"
                />
              </div>
              <div>
                <label className="block text-xs text-zinc-400 mb-1">App Secret <span className="text-zinc-500">(opcional)</span></label>
                <input
                  value={addConfig.app_secret || ''}
                  onChange={(e) => setAddConfig((c) => ({ ...c, app_secret: e.target.value }))}
                  placeholder="aabbcc..."
                  className="w-full bg-zinc-800 border border-zinc-700 rounded px-3 py-1.5 text-sm text-zinc-100 placeholder-zinc-500 focus:outline-none focus:border-zinc-500"
                />
              </div>
            </>
          )}

          {addType === 'whatsapp_web' && (
            <div>
              <label className="block text-xs text-zinc-400 mb-1">Bridge URL</label>
              <input
                value={addConfig.bridge_url || ''}
                onChange={(e) => setAddConfig({ bridge_url: e.target.value })}
                placeholder="http://localhost:3000"
                className="w-full bg-zinc-800 border border-zinc-700 rounded px-3 py-1.5 text-sm text-zinc-100 placeholder-zinc-500 focus:outline-none focus:border-zinc-500"
              />
            </div>
          )}

          <div className="flex gap-2">
            <button
              onClick={handleAdd}
              disabled={addChannel.isPending}
              className="px-3 py-1.5 text-sm bg-blue-600 hover:bg-blue-700 disabled:opacity-50 rounded-lg text-white transition-colors"
            >
              {addChannel.isPending ? 'Guardando…' : 'Guardar'}
            </button>
            <button
              onClick={() => { setShowAddForm(false); setAddConfig({}); }}
              className="px-3 py-1.5 text-sm text-zinc-400 hover:text-zinc-200 transition-colors"
            >
              Cancelar
            </button>
          </div>
        </div>
      )}

      {/* Empty state */}
      {channels.length === 0 && !showAddForm && (
        <div className="text-center py-8 text-zinc-500 text-sm">
          <Radio className="w-8 h-8 mx-auto mb-2 opacity-40" />
          Conecta este agente a Telegram, WhatsApp Business o WhatsApp Web.
        </div>
      )}

      {/* Channel cards */}
      {channels.map((ch) => (
        <div key={ch.id} className="border border-zinc-700 rounded-lg p-3 bg-zinc-900/30">
          <div className="flex items-start justify-between gap-2">
            <div className="flex items-start gap-2 min-w-0">
              <Radio className="w-4 h-4 text-blue-400 mt-0.5 flex-shrink-0" />
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <p className="text-sm text-zinc-100">
                    {ch.type === 'telegram' ? 'Telegram' : ch.type === 'whatsapp' ? 'WhatsApp Business' : 'WhatsApp Web'}
                  </p>
                  <span className={cn(
                    'inline-flex items-center gap-1 text-xs px-1.5 py-0.5 rounded-full',
                    ch.is_connected
                      ? 'bg-green-900/40 text-green-400'
                      : 'bg-zinc-800 text-zinc-500'
                  )}>
                    <span className={cn(
                      'w-1.5 h-1.5 rounded-full',
                      ch.is_connected ? 'bg-green-400' : 'bg-zinc-500'
                    )} />
                    {ch.is_connected ? 'CONECTADO' : 'DESCONECTADO'}
                  </span>
                </div>
                <p className="text-xs text-zinc-500 mt-0.5 truncate">
                  {ch.type === 'telegram'
                    ? `Token: ${ch.config.token ?? '—'}`
                    : ch.type === 'whatsapp'
                    ? `ID: ${ch.config.phone_number_id ?? '—'}`
                    : `Bridge: ${ch.config.bridge_url ?? '—'}`}
                </p>
              </div>
            </div>
            <div className="flex items-center gap-1 flex-shrink-0">
              <button
                onClick={() => handleRestart(ch)}
                disabled={restartingId === ch.id}
                className="p-1 text-zinc-500 hover:text-zinc-300 transition-colors"
                title="Reiniciar canal"
              >
                <RefreshCw className={cn('w-3.5 h-3.5', restartingId === ch.id && 'animate-spin')} />
              </button>
              <button
                onClick={() => handleDelete(ch)}
                disabled={deletingId === ch.id}
                className="p-1 text-zinc-500 hover:text-red-400 transition-colors"
                title="Eliminar canal"
              >
                <Trash2 className="w-3.5 h-3.5" />
              </button>
            </div>
          </div>
        </div>
      ))}

      {/* WhatsApp webhook docs */}
      {hasWhatsApp && (
        <div className="border border-zinc-700 rounded-lg overflow-hidden">
          <button
            onClick={() => setShowWebhookDocs((v) => !v)}
            className="w-full flex items-center justify-between px-3 py-2 text-sm text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800/50 transition-colors"
          >
            <span className="font-medium">Configuración del Webhook</span>
            {showWebhookDocs ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
          </button>

          {showWebhookDocs && (
            <div className="px-3 pb-3 space-y-3 border-t border-zinc-700">
              <div className="mt-3">
                <p className="text-xs text-zinc-400 mb-1">URL del webhook</p>
                <div className="flex items-center gap-2">
                  <code className="flex-1 text-xs bg-zinc-800 px-2 py-1.5 rounded text-zinc-300 truncate">
                    https://tu-dominio.com/webhooks/whatsapp
                  </code>
                  <button
                    onClick={copyWebhookUrl}
                    className="p-1.5 text-zinc-500 hover:text-zinc-300 transition-colors flex-shrink-0"
                    title="Copiar URL"
                  >
                    {copied ? <Check className="w-3.5 h-3.5 text-green-400" /> : <Copy className="w-3.5 h-3.5" />}
                  </button>
                </div>
                <p className="text-xs text-zinc-500 mt-1">
                  Meta Developer Console → WhatsApp → Configuration → Webhook → Edit. Suscribe al evento: <code className="text-zinc-400">messages</code>
                </p>
              </div>

              <div>
                <p className="text-xs text-zinc-400 mb-1">Probar con código</p>
                <div className="flex gap-1 mb-2">
                  {(['curl', 'python', 'js'] as const).map((tab) => (
                    <button
                      key={tab}
                      onClick={() => setWebhookTab(tab)}
                      className={cn(
                        'px-2 py-0.5 text-xs rounded transition-colors',
                        webhookTab === tab
                          ? 'bg-zinc-700 text-zinc-100'
                          : 'text-zinc-500 hover:text-zinc-300'
                      )}
                    >
                      {tab === 'js' ? 'JavaScript' : tab === 'python' ? 'Python' : 'cURL'}
                    </button>
                  ))}
                </div>
                <pre className="text-xs bg-zinc-800 p-2 rounded overflow-x-auto text-zinc-300 acm-scroll">
                  {webhookTab === 'curl' ? WEBHOOK_CURL : webhookTab === 'python' ? WEBHOOK_PYTHON : WEBHOOK_JS}
                </pre>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── Agent Form Modal ──────────────────────────────────────────────────────────

function AgentFormModal({
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
            Create Agent
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Agent Detail View (in-place, replaces the grid — not an overlay) ──────────

function AgentDetailView({ agent, onClose }: { agent: Agent; onClose: () => void }) {
  const { update, generate } = useAgentMutations();
  const [form, setForm] = useState<AgentFormData>({
    name: agent.name,
    description: agent.description,
    system_prompt: agent.system_prompt,
    allowed_tools: agent.allowed_tools,
    telegram_token: agent.telegram_token ?? '',
  });
  const [genDescription, setGenDescription] = useState('');
  const [droppedFiles, setDroppedFiles] = useState<File[]>([]);
  const [isDragging, setIsDragging] = useState(false);
  const [activeTab, setActiveTab] = useState<'config' | 'knowledge' | 'channels' | 'tools' | 'skills' | 'flows'>('config');

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

  const handleSave = async () => {
    try {
      // Only send the fields this tab actually has controls for — allowed_tools
      // is saved independently by AgentToolsTab, and including the mount-time
      // snapshot here would silently overwrite whatever was saved there since.
      await update.mutateAsync({
        id: agent.id,
        data: { name: form.name, description: form.description, system_prompt: form.system_prompt },
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
          onMouseLeave={e => (e.currentTarget.style.color = 'var(--acm-fg-4)')}
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

  if (isLoading || !flows) return <Loader2 size={16} className="animate-spin" />;

  const handleCreate = () => {
    create.mutate({ name: 'Nuevo flujo', description: '' }, {
      onSuccess: (created: any) => setEditingFlowId(created.id),
    });
  };

  if (editingFlowId !== null) {
    return (
      <div className="flex flex-col gap-2">
        <button onClick={() => setEditingFlowId(null)} className="btn-secondary self-start text-[11px] px-2 py-1">
          ← Volver a la lista
        </button>
        <div className="text-[12px]" style={{ color: 'var(--acm-fg-4)' }}>
          Editor de nodos — llega en la Tarea 11. (flow id: {editingFlowId})
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-2">
      <button onClick={handleCreate} disabled={create.isPending} className="btn-secondary self-end text-[11px] px-2 py-1">
        + Nuevo flujo
      </button>
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
