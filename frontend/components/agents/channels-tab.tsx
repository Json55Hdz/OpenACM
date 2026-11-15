'use client';

import { useState } from 'react';
import { useAgentChannels, useAgentChannelMutations, type Agent, type ChannelItem } from '@/hooks/use-agents';
import { Plus, Trash2, Copy, Check, Loader2, ChevronDown, ChevronUp, Radio, RefreshCw } from 'lucide-react';
import { toast } from 'sonner';
import { cn } from './shared';

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

export function ChannelsTab({ agentId }: { agentId: number }) {
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
