'use client';

import { useState } from 'react';
import { AppLayout } from '@/components/layout/app-layout';
import { useMCPServers, type MCPServer } from '@/hooks/use-api';
import { translations } from '@/lib/translations';
import {
  Plug,
  Plus,
  Trash2,
  RefreshCw,
  ChevronDown,
  ChevronUp,
  CheckCircle,
  XCircle,
  Loader2,
  Pencil,
  X,
  Globe,
  Terminal,
  Key,
} from 'lucide-react';
import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';

function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

const t = translations.mcp;

// ─── Form types ───────────────────────────────────────────────────────────────

type Mode = 'remote' | 'local';
type RemoteProtocol = 'streamable_http' | 'sse';

interface ServerFormData {
  name: string;
  mode: Mode;
  // remote
  url: string;
  api_key: string;
  protocol: RemoteProtocol;
  // local (stdio)
  command: string;
  args: string;        // one per line
  // shared
  auto_connect: boolean;
}

const EMPTY_FORM: ServerFormData = {
  name: '',
  mode: 'remote',
  url: '',
  api_key: '',
  protocol: 'streamable_http',
  command: '',
  args: '',
  auto_connect: true,
};

function serverToForm(s: MCPServer): ServerFormData {
  return {
    name: s.name,
    mode: s.transport === 'stdio' ? 'local' : 'remote',
    url: s.url,
    api_key: s.api_key ?? '',
    protocol: (s.transport === 'sse' ? 'sse' : 'streamable_http') as RemoteProtocol,
    command: s.command,
    args: s.args.join('\n'),
    auto_connect: s.auto_connect,
  };
}

function formToPayload(f: ServerFormData) {
  const base = { name: f.name.trim(), auto_connect: f.auto_connect };
  if (f.mode === 'remote') {
    return {
      ...base,
      transport: f.protocol,
      url: f.url.trim(),
      api_key: f.api_key.trim(),
      command: '',
      args: [],
    };
  }
  return {
    ...base,
    transport: 'stdio',
    url: '',
    api_key: '',
    command: f.command.trim(),
    args: f.args.split('\n').map((a) => a.trim()).filter(Boolean),
  };
}

// ─── Server card ──────────────────────────────────────────────────────────────

function ServerCard({
  server,
  onConnect,
  onDisconnect,
  onRemove,
  onEdit,
  isActing,
}: {
  server: MCPServer;
  onConnect: () => void;
  onDisconnect: () => void;
  onRemove: () => void;
  onEdit: () => void;
  isActing: boolean;
}) {
  const [showTools, setShowTools] = useState(false);
  const isRemote = server.transport !== 'stdio';

  return (
    <div
      className={cn(
        'bg-slate-900 rounded-xl border p-5 transition-colors',
        server.connected ? 'border-green-600/40' : 'border-slate-800 hover:border-slate-700',
      )}
    >
      {/* Header */}
      <div className="flex items-start justify-between mb-3">
        <div className="flex items-center gap-3">
          <div
            className={cn(
              'w-10 h-10 rounded-lg flex items-center justify-center',
              server.connected ? 'bg-green-600/20' : 'bg-slate-800',
            )}
          >
            {isRemote
              ? <Globe size={19} className={server.connected ? 'text-green-400' : 'text-slate-400'} />
              : <Terminal size={19} className={server.connected ? 'text-green-400' : 'text-slate-400'} />
            }
          </div>
          <div>
            <h3 className="font-semibold text-white">{server.name}</h3>
            <span className="text-xs text-slate-500">
              {!isRemote ? 'Local (stdio)' :
               server.transport === 'sse' ? 'Remote (SSE)' : 'Remote (HTTP)'}
            </span>
          </div>
        </div>

        <div className="flex items-center gap-1">
          <button onClick={onEdit} className="p-1.5 text-slate-500 hover:text-white rounded transition-colors" title="Edit">
            <Pencil size={14} />
          </button>
          <button onClick={onRemove} className="p-1.5 text-slate-500 hover:text-red-400 rounded transition-colors" title="Remove">
            <Trash2 size={14} />
          </button>
        </div>
      </div>

      {/* URL / command preview */}
      <p className="text-xs text-slate-500 font-mono mb-4 truncate">
        {isRemote
          ? (server.url || '—')
          : [server.command, ...server.args].join(' ') || '—'
        }
      </p>

      {/* Status row */}
      <div className="flex items-center gap-3">
        {server.connected ? (
          <span className="flex items-center gap-1.5 text-xs font-medium text-green-400">
            <CheckCircle size={13} /> Connected
          </span>
        ) : server.error ? (
          <span className="flex items-center gap-1.5 text-xs font-medium text-red-400" title={server.error}>
            <XCircle size={13} /> Error
          </span>
        ) : (
          <span className="text-xs text-slate-500">Disconnected</span>
        )}

        <div className="ml-auto">
          {server.connected ? (
            <button
              onClick={onDisconnect}
              disabled={isActing}
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 transition-colors disabled:opacity-50"
            >
              {isActing ? <Loader2 size={12} className="animate-spin" /> : <XCircle size={12} />}
              Disconnect
            </button>
          ) : (
            <button
              onClick={onConnect}
              disabled={isActing}
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-lg bg-blue-600 hover:bg-blue-500 text-white transition-colors disabled:opacity-50"
            >
              {isActing ? <Loader2 size={12} className="animate-spin" /> : <RefreshCw size={12} />}
              Connect
            </button>
          )}
        </div>
      </div>

      {/* Tools */}
      {server.connected && server.tools.length > 0 && (
        <div className="mt-4">
          <button
            onClick={() => setShowTools(!showTools)}
            className="flex items-center gap-1.5 text-xs text-slate-400 hover:text-white transition-colors"
          >
            {showTools ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
            {server.tools.length} tools available
          </button>
          {showTools && (
            <div className="mt-2 space-y-1.5 pl-1">
              {server.tools.map((tool) => (
                <div key={tool.name} className="bg-slate-950 rounded-lg px-3 py-2">
                  <p className="text-xs font-mono text-blue-400">{tool.name}</p>
                  {tool.description && (
                    <p className="text-xs text-slate-500 mt-0.5 line-clamp-2">{tool.description}</p>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Error */}
      {server.error && !server.connected && (
        <p className="mt-3 text-xs text-red-400/80 font-mono bg-red-950/30 rounded px-2 py-1.5 break-all">
          {server.error}
        </p>
      )}
    </div>
  );
}

// ─── Add / Edit modal ─────────────────────────────────────────────────────────

function ServerModal({
  initial,
  isEdit,
  onSave,
  onClose,
}: {
  initial?: ServerFormData;
  isEdit?: boolean;
  onSave: (payload: ReturnType<typeof formToPayload>) => void;
  onClose: () => void;
}) {
  const [form, setForm] = useState<ServerFormData>(initial ?? EMPTY_FORM);
  const set = <K extends keyof ServerFormData>(k: K, v: ServerFormData[K]) =>
    setForm((p) => ({ ...p, [k]: v }));

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    onSave(formToPayload(form));
    onClose();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 px-4">
      <div className="bg-slate-900 border border-slate-700 rounded-2xl w-full max-w-md shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between p-6 border-b border-slate-800">
          <h2 className="text-lg font-semibold text-white">
            {isEdit ? 'Edit MCP Server' : 'Add MCP Server'}
          </h2>
          <button onClick={onClose} className="text-slate-400 hover:text-white">
            <X size={20} />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="p-6 space-y-5">

          {/* Mode toggle */}
          {!isEdit && (
            <div className="grid grid-cols-2 gap-2 p-1 bg-slate-800 rounded-xl">
              <button
                type="button"
                onClick={() => set('mode', 'remote')}
                className={cn(
                  'flex items-center justify-center gap-2 py-2.5 rounded-lg text-sm font-medium transition-all',
                  form.mode === 'remote'
                    ? 'bg-blue-600 text-white shadow'
                    : 'text-slate-400 hover:text-white',
                )}
              >
                <Globe size={16} />
                Remote (URL)
              </button>
              <button
                type="button"
                onClick={() => set('mode', 'local')}
                className={cn(
                  'flex items-center justify-center gap-2 py-2.5 rounded-lg text-sm font-medium transition-all',
                  form.mode === 'local'
                    ? 'bg-blue-600 text-white shadow'
                    : 'text-slate-400 hover:text-white',
                )}
              >
                <Terminal size={16} />
                Local (stdio)
              </button>
            </div>
          )}

          {/* Name */}
          <div>
            <label className="block text-xs font-medium text-slate-400 mb-1.5">Server name</label>
            <input
              type="text"
              value={form.name}
              onChange={(e) => set('name', e.target.value)}
              disabled={isEdit}
              required
              placeholder="my-server"
              className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2.5 text-sm text-white placeholder-slate-500 focus:outline-none focus:border-blue-500 disabled:opacity-50"
            />
          </div>

          {/* Remote fields */}
          {form.mode === 'remote' && (
            <>
              <div>
                <label className="block text-xs font-medium text-slate-400 mb-1.5">
                  Server URL
                </label>
                <input
                  type="text"
                  value={form.url}
                  onChange={(e) => set('url', e.target.value)}
                  required
                  placeholder="http://localhost:6000/mcp"
                  className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2.5 text-sm text-white placeholder-slate-500 focus:outline-none focus:border-blue-500 font-mono"
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-slate-400 mb-1.5">Protocol</label>
                <div className="grid grid-cols-2 gap-2 p-1 bg-slate-800 rounded-xl">
                  <button
                    type="button"
                    onClick={() => set('protocol', 'streamable_http')}
                    className={cn(
                      'py-2 rounded-lg text-xs font-medium transition-all',
                      form.protocol === 'streamable_http'
                        ? 'bg-blue-600 text-white shadow'
                        : 'text-slate-400 hover:text-white',
                    )}
                  >
                    HTTP <span className="text-slate-400 font-normal">(modern)</span>
                  </button>
                  <button
                    type="button"
                    onClick={() => set('protocol', 'sse')}
                    className={cn(
                      'py-2 rounded-lg text-xs font-medium transition-all',
                      form.protocol === 'sse'
                        ? 'bg-blue-600 text-white shadow'
                        : 'text-slate-400 hover:text-white',
                    )}
                  >
                    SSE <span className="text-slate-400 font-normal">(legacy)</span>
                  </button>
                </div>
                <p className="text-xs text-slate-600 mt-1.5">
                  Use HTTP for unity-mcp and most modern servers. SSE for older ones.
                </p>
              </div>
              <div>
                <label className="flex items-center gap-1.5 text-xs font-medium text-slate-400 mb-1.5">
                  <Key size={12} />
                  API Key <span className="text-slate-600">(optional)</span>
                </label>
                <input
                  type="password"
                  value={form.api_key}
                  onChange={(e) => set('api_key', e.target.value)}
                  placeholder="sk-..."
                  className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2.5 text-sm text-white placeholder-slate-500 focus:outline-none focus:border-blue-500"
                />
              </div>
            </>
          )}

          {/* Local / stdio fields */}
          {form.mode === 'local' && (
            <>
              <div>
                <label className="block text-xs font-medium text-slate-400 mb-1.5">Command</label>
                <input
                  type="text"
                  value={form.command}
                  onChange={(e) => set('command', e.target.value)}
                  required
                  placeholder="npx"
                  className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2.5 text-sm text-white placeholder-slate-500 focus:outline-none focus:border-blue-500 font-mono"
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-slate-400 mb-1.5">
                  Arguments <span className="text-slate-600">(one per line)</span>
                </label>
                <textarea
                  value={form.args}
                  onChange={(e) => set('args', e.target.value)}
                  rows={4}
                  placeholder={`-y\n@modelcontextprotocol/server-filesystem\nC:\\Users\\your_username`}
                  className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2.5 text-sm text-white placeholder-slate-500 focus:outline-none focus:border-blue-500 font-mono resize-none"
                />
              </div>
            </>
          )}

          {/* Auto-connect */}
          <label className="flex items-center gap-3 cursor-pointer select-none">
            <input
              type="checkbox"
              checked={form.auto_connect}
              onChange={(e) => set('auto_connect', e.target.checked)}
              className="w-4 h-4 accent-blue-500"
            />
            <span className="text-sm text-slate-300">Auto-connect on startup</span>
          </label>

          {/* Buttons */}
          <div className="flex gap-3 pt-1">
            <button
              type="button"
              onClick={onClose}
              className="flex-1 px-4 py-2.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 text-sm transition-colors"
            >
              Cancel
            </button>
            <button
              type="submit"
              className="flex-1 px-4 py-2.5 rounded-lg bg-blue-600 hover:bg-blue-500 text-white text-sm font-medium transition-colors"
            >
              {isEdit ? 'Save changes' : 'Add server'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function MCPPage() {
  const {
    servers,
    isLoading,
    addServer,
    updateServer,
    removeServer,
    connectServer,
    disconnectServer,
    isConnecting,
    isDisconnecting,
  } = useMCPServers();

  const [showAdd, setShowAdd] = useState(false);
  const [editTarget, setEditTarget] = useState<MCPServer | null>(null);

  const handleSave = (payload: ReturnType<typeof formToPayload>, isEdit: boolean, name?: string) => {
    if (isEdit && name) {
      updateServer({ name, data: payload });
    } else {
      addServer(payload);
    }
  };

  return (
    <AppLayout>
      <div className="p-6 lg:p-8">
        {/* Header */}
        <header className="mb-8">
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
            <div>
              <h1 className="text-3xl font-bold text-white">MCP Servers</h1>
              <p className="text-slate-400 mt-1">
                Connect external tools to the assistant via Model Context Protocol
              </p>
            </div>
            <button
              onClick={() => setShowAdd(true)}
              className="flex items-center gap-2 px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-500 text-white font-medium transition-colors"
            >
              <Plus size={18} />
              Add server
            </button>
          </div>
        </header>

        {/* Content */}
        {isLoading ? (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {[1, 2, 3].map((i) => (
              <div key={i} className="bg-slate-900 rounded-xl border border-slate-800 p-5 h-48 animate-pulse" />
            ))}
          </div>
        ) : servers.length === 0 ? (
          <div className="text-center py-20 bg-slate-900 rounded-xl border border-slate-800">
            <Plug size={48} className="mx-auto text-slate-600 mb-4" />
            <h3 className="text-lg font-medium text-slate-300 mb-2">No MCP servers yet</h3>
            <p className="text-sm text-slate-500 mb-6 max-w-sm mx-auto">
              Paste the URL of a remote server or configure a local one with a command.
            </p>
            <button
              onClick={() => setShowAdd(true)}
              className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-500 text-white font-medium transition-colors"
            >
              <Plus size={18} />
              Add server
            </button>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {servers.map((server) => (
              <ServerCard
                key={server.name}
                server={server}
                isActing={isConnecting || isDisconnecting}
                onConnect={() => connectServer(server.name)}
                onDisconnect={() => disconnectServer(server.name)}
                onRemove={() => removeServer(server.name)}
                onEdit={() => setEditTarget(server)}
              />
            ))}
          </div>
        )}
      </div>

      {/* Add modal */}
      {showAdd && (
        <ServerModal
          onSave={(p) => handleSave(p, false)}
          onClose={() => setShowAdd(false)}
        />
      )}

      {/* Edit modal */}
      {editTarget && (
        <ServerModal
          initial={serverToForm(editTarget)}
          isEdit
          onSave={(p) => handleSave(p, true, editTarget.name)}
          onClose={() => setEditTarget(null)}
        />
      )}
    </AppLayout>
  );
}
