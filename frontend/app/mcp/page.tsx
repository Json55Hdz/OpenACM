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
  Loader2,
  Pencil,
  X,
  Globe,
  Terminal,
  Key,
  Wrench,
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

  // Status dot
  let dotClass = 'dot dot-idle';
  if (server.connected) dotClass = 'dot dot-ok acm-pulse';
  else if (server.error) dotClass = 'dot dot-err';

  // Status text
  let statusText = 'DISCONNECTED';
  if (server.connected) statusText = 'CONNECTED';
  else if (server.error) statusText = 'ERROR';

  // Mode · protocol label
  const modeLabel = !isRemote
    ? 'STDIO'
    : server.transport === 'sse'
    ? 'SSE'
    : 'HTTP';

  return (
    <div className="acm-card p-5 flex flex-col gap-4">
      {/* Header row */}
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-3 min-w-0">
          {/* Status dot */}
          <span className={dotClass} />

          {/* Icon + name */}
          <div
            className="w-9 h-9 rounded-lg flex items-center justify-center shrink-0"
            style={{ background: 'var(--acm-elev)' }}
          >
            {isRemote
              ? <Globe size={16} style={{ color: server.connected ? 'var(--acm-ok)' : 'var(--acm-fg-3)' }} />
              : <Terminal size={16} style={{ color: server.connected ? 'var(--acm-ok)' : 'var(--acm-fg-3)' }} />
            }
          </div>

          <div className="min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="font-semibold text-sm mono" style={{ color: 'var(--acm-fg)' }}>
                {server.name}
              </span>
              <span
                className="mono text-[10px] font-semibold tracking-widest uppercase px-1.5 py-0.5 rounded"
                style={{
                  color: server.connected ? 'var(--acm-ok)' : server.error ? 'var(--acm-err)' : 'var(--acm-fg-4)',
                  background: 'var(--acm-elev)',
                }}
              >
                {modeLabel} · {statusText}
              </span>
            </div>
            <p
              className="mono text-[11px] truncate mt-0.5"
              style={{ color: 'var(--acm-fg-4)' }}
            >
              {isRemote
                ? (server.url || '—')
                : [server.command, ...server.args].join(' ') || '—'
              }
            </p>
          </div>
        </div>

        {/* Action buttons */}
        <div className="flex items-center gap-1 shrink-0">
          {server.connected ? (
            <button
              onClick={onDisconnect}
              disabled={isActing}
              className="btn-secondary"
              style={{ fontSize: '11px', padding: '5px 10px' }}
            >
              {isActing ? <Loader2 size={11} className="animate-spin" /> : <X size={11} />}
              Disconnect
            </button>
          ) : (
            <button
              onClick={onConnect}
              disabled={isActing}
              className="btn-primary"
              style={{ fontSize: '11px', padding: '5px 10px' }}
            >
              {isActing ? <Loader2 size={11} className="animate-spin" /> : <RefreshCw size={11} />}
              Connect
            </button>
          )}
          <button
            onClick={onEdit}
            className="p-1.5 rounded transition-colors"
            style={{ color: 'var(--acm-fg-4)' }}
            title="Edit"
          >
            <Pencil size={13} />
          </button>
          <button
            onClick={onRemove}
            className="p-1.5 rounded transition-colors"
            style={{ color: 'var(--acm-fg-4)' }}
            title="Remove"
            onMouseEnter={e => (e.currentTarget.style.color = 'var(--acm-err)')}
            onMouseLeave={e => (e.currentTarget.style.color = 'var(--acm-fg-4)')}
          >
            <Trash2 size={13} />
          </button>
        </div>
      </div>

      {/* Tool count pill + expand */}
      {server.connected && server.tools.length > 0 && (
        <div>
          <button
            onClick={() => setShowTools(!showTools)}
            className="flex items-center gap-2 transition-colors"
            style={{ color: 'var(--acm-fg-3)' }}
            onMouseEnter={e => (e.currentTarget.style.color = 'var(--acm-fg)')}
            onMouseLeave={e => (e.currentTarget.style.color = 'var(--acm-fg-3)')}
          >
            <span
              className="mono text-[10px] font-semibold px-2 py-0.5 rounded border"
              style={{
                borderColor: 'var(--acm-border)',
                color: 'var(--acm-accent)',
                background: 'var(--acm-elev)',
              }}
            >
              <Wrench size={9} className="inline mr-1" />
              {server.tools.length} tools
            </span>
            {showTools ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
          </button>

          {showTools && (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {server.tools.map((tool) => (
                <span
                  key={tool.name}
                  className="mono text-[10px] px-2 py-0.5 rounded border"
                  style={{
                    borderColor: 'var(--acm-border)',
                    color: 'var(--acm-fg-3)',
                    background: 'var(--acm-elev)',
                  }}
                  title={tool.description ?? ''}
                >
                  {tool.name}
                </span>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Error message */}
      {server.error && !server.connected && (
        <p
          className="mono text-[11px] rounded px-3 py-2 break-all"
          style={{
            color: 'var(--acm-err)',
            background: 'oklch(0.68 0.13 22 / 0.1)',
            border: '1px solid oklch(0.68 0.13 22 / 0.25)',
          }}
        >
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

  const toggleBtn = (active: boolean) =>
    cn(
      'flex items-center justify-center gap-2 py-2.5 rounded-lg text-sm font-semibold transition-all',
      active
        ? 'text-[oklch(0.18_0.015_80)]'
        : 'hover:text-[var(--acm-fg)]',
    );

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 px-4">
      <div
        className="w-full max-w-md rounded-2xl shadow-2xl overflow-hidden"
        style={{
          background: 'var(--acm-base)',
          border: '1px solid var(--acm-border)',
        }}
      >
        {/* Header */}
        <div
          className="flex items-center justify-between px-6 py-5"
          style={{ borderBottom: '1px solid var(--acm-border)' }}
        >
          <h2 className="text-base font-bold" style={{ color: 'var(--acm-fg)' }}>
            {isEdit ? 'Edit MCP Server' : 'Add MCP Server'}
          </h2>
          <button
            onClick={onClose}
            style={{ color: 'var(--acm-fg-4)' }}
            onMouseEnter={e => (e.currentTarget.style.color = 'var(--acm-fg)')}
            onMouseLeave={e => (e.currentTarget.style.color = 'var(--acm-fg-4)')}
          >
            <X size={18} />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="px-6 py-5 space-y-5">

          {/* Mode toggle */}
          {!isEdit && (
            <div
              className="grid grid-cols-2 gap-1.5 p-1 rounded-xl"
              style={{ background: 'var(--acm-elev)' }}
            >
              <button
                type="button"
                onClick={() => set('mode', 'remote')}
                className={toggleBtn(form.mode === 'remote')}
                style={form.mode === 'remote' ? { background: 'var(--acm-accent)' } : { color: 'var(--acm-fg-3)' }}
              >
                <Globe size={15} />
                Remote (URL)
              </button>
              <button
                type="button"
                onClick={() => set('mode', 'local')}
                className={toggleBtn(form.mode === 'local')}
                style={form.mode === 'local' ? { background: 'var(--acm-accent)' } : { color: 'var(--acm-fg-3)' }}
              >
                <Terminal size={15} />
                Local (stdio)
              </button>
            </div>
          )}

          {/* Name */}
          <div>
            <label className="label block mb-2">Server name</label>
            <input
              type="text"
              value={form.name}
              onChange={(e) => set('name', e.target.value)}
              disabled={isEdit}
              required
              placeholder="my-server"
              className="acm-input"
            />
          </div>

          {/* Remote fields */}
          {form.mode === 'remote' && (
            <>
              <div>
                <label className="label block mb-2">Server URL</label>
                <input
                  type="text"
                  value={form.url}
                  onChange={(e) => set('url', e.target.value)}
                  required
                  placeholder="http://localhost:6000/mcp"
                  className="acm-input mono"
                />
              </div>

              {/* Protocol toggle */}
              <div>
                <label className="label block mb-2">Protocol</label>
                <div
                  className="grid grid-cols-2 gap-1.5 p-1 rounded-xl"
                  style={{ background: 'var(--acm-elev)' }}
                >
                  <button
                    type="button"
                    onClick={() => set('protocol', 'streamable_http')}
                    className={toggleBtn(form.protocol === 'streamable_http')}
                    style={
                      form.protocol === 'streamable_http'
                        ? { background: 'var(--acm-accent)' }
                        : { color: 'var(--acm-fg-3)' }
                    }
                  >
                    HTTP
                    <span
                      className="text-[10px] font-normal"
                      style={{
                        color: form.protocol === 'streamable_http'
                          ? 'oklch(0.18 0.015 80 / 0.7)'
                          : 'var(--acm-fg-4)',
                      }}
                    >
                      (modern)
                    </span>
                  </button>
                  <button
                    type="button"
                    onClick={() => set('protocol', 'sse')}
                    className={toggleBtn(form.protocol === 'sse')}
                    style={
                      form.protocol === 'sse'
                        ? { background: 'var(--acm-accent)' }
                        : { color: 'var(--acm-fg-3)' }
                    }
                  >
                    SSE
                    <span
                      className="text-[10px] font-normal"
                      style={{
                        color: form.protocol === 'sse'
                          ? 'oklch(0.18 0.015 80 / 0.7)'
                          : 'var(--acm-fg-4)',
                      }}
                    >
                      (legacy)
                    </span>
                  </button>
                </div>
                <p className="text-[11px] mt-1.5" style={{ color: 'var(--acm-fg-4)' }}>
                  Use HTTP for unity-mcp and most modern servers. SSE for older ones.
                </p>
              </div>

              <div>
                <label className="label flex items-center gap-1.5 mb-2">
                  <Key size={11} />
                  API Key
                  <span style={{ color: 'var(--acm-fg-4)', fontWeight: 400 }}>(optional)</span>
                </label>
                <input
                  type="password"
                  value={form.api_key}
                  onChange={(e) => set('api_key', e.target.value)}
                  placeholder="sk-..."
                  className="acm-input"
                />
              </div>
            </>
          )}

          {/* Local / stdio fields */}
          {form.mode === 'local' && (
            <>
              <div>
                <label className="label block mb-2">Command</label>
                <input
                  type="text"
                  value={form.command}
                  onChange={(e) => set('command', e.target.value)}
                  required
                  placeholder="npx"
                  className="acm-input mono"
                />
              </div>
              <div>
                <label className="label block mb-2">
                  Arguments
                  <span style={{ color: 'var(--acm-fg-4)', fontWeight: 400 }}> (one per line)</span>
                </label>
                <textarea
                  value={form.args}
                  onChange={(e) => set('args', e.target.value)}
                  rows={4}
                  placeholder={`-y\n@modelcontextprotocol/server-filesystem\nC:\\Users\\your_username`}
                  className="mono w-full resize-none outline-none text-[13px] px-0 py-2"
                  style={{
                    background: 'transparent',
                    borderBottom: '1px solid var(--acm-border)',
                    color: 'var(--acm-fg)',
                  }}
                  onFocus={e => (e.currentTarget.style.borderBottomColor = 'var(--acm-accent)')}
                  onBlur={e => (e.currentTarget.style.borderBottomColor = 'var(--acm-border)')}
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
              className="w-4 h-4"
              style={{ accentColor: 'var(--acm-accent)' }}
            />
            <span className="text-sm" style={{ color: 'var(--acm-fg-2)' }}>
              Auto-connect on startup
            </span>
          </label>

          {/* Buttons */}
          <div className="flex gap-3 pt-1">
            <button type="button" onClick={onClose} className="btn-secondary flex-1">
              Cancel
            </button>
            <button type="submit" className="btn-primary flex-1 justify-center">
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
      <div className="p-6 lg:p-8" style={{ background: 'var(--acm-base)', minHeight: '100%' }}>

        {/* Page header */}
        <header className="mb-8">
          <span className="acm-breadcrumb">Integrations</span>
          <div className="flex flex-col sm:flex-row sm:items-end sm:justify-between gap-4">
            <div>
              <h1 className="text-2xl font-bold" style={{ color: 'var(--acm-fg)' }}>
                MCP Servers
              </h1>
              <p className="text-sm mt-1" style={{ color: 'var(--acm-fg-3)' }}>
                Connect external tools to the assistant via Model Context Protocol
              </p>
            </div>
            <button
              onClick={() => setShowAdd(true)}
              className="btn-primary shrink-0"
            >
              <Plus size={15} />
              Add server
            </button>
          </div>
        </header>

        {/* Content */}
        {isLoading ? (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {[1, 2, 3].map((i) => (
              <div
                key={i}
                className="acm-card p-5 h-40 animate-pulse"
                style={{ opacity: 0.5 }}
              />
            ))}
          </div>
        ) : servers.length === 0 ? (
          <div
            className="acm-card text-center py-20 flex flex-col items-center gap-4"
          >
            <div
              className="w-14 h-14 rounded-2xl flex items-center justify-center"
              style={{ background: 'var(--acm-elev)' }}
            >
              <Plug size={26} style={{ color: 'var(--acm-fg-4)' }} />
            </div>
            <div>
              <h3 className="text-base font-semibold mb-1" style={{ color: 'var(--acm-fg-2)' }}>
                No MCP servers yet
              </h3>
              <p className="text-sm max-w-xs mx-auto" style={{ color: 'var(--acm-fg-4)' }}>
                Paste the URL of a remote server or configure a local one with a command.
              </p>
            </div>
            <button onClick={() => setShowAdd(true)} className="btn-primary mt-2">
              <Plus size={15} />
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
