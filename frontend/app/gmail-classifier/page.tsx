'use client';

import { useState, useEffect, useCallback } from 'react';
import { Mail, RefreshCw, Settings, AlertTriangle, ExternalLink, Square, Sparkles, BarChart3 } from 'lucide-react';
import Link from 'next/link';
import { AppLayout } from '@/components/layout/app-layout';
import { useAuthStore } from '@/stores/auth-store';
import { CategoryTabs } from './components/CategoryTabs';
import { EmailList } from './components/EmailList';
import { EmailDetail } from './components/EmailDetail';
import { CategoryManager } from './components/CategoryManager';
import { ProcessingProgress } from './components/ProcessingProgress';
import { PluginSettings } from './components/PluginSettings';

const API = '/api/gmail-classifier';

function timeAgoShort(iso: string): string {
  try {
    const diff = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
    if (diff < 60) return 'hace un momento';
    if (diff < 3600) return `hace ${Math.floor(diff / 60)} min`;
    if (diff < 86400) return `hace ${Math.floor(diff / 3600)}h`;
    return `hace ${Math.floor(diff / 86400)}d`;
  } catch { return ''; }
}

interface Category {
  id: number;
  name: string;
  description: string;
  color: string;
  icon: string;
  email_count: number;
}

interface Email {
  id: number;
  gmail_id: string;
  thread_id: string;
  subject: string;
  sender_name: string;
  sender_email: string;
  snippet: string;
  body_text: string;
  body_html: string;
  category_id: number;
  category_name: string;
  category_color: string;
  category_icon: string;
  is_read: number;
  is_replied: number;
  received_at: string;
}

interface ProcessStatus {
  running: boolean;
  processed: number;
  total: number;
  errors: number;
  started_at: string | null;
  last_completed_at: string | null;
  cron_active: boolean;
}

interface AuthStatus {
  configured: boolean;
  has_token: boolean;
  ready: boolean;
}

// ─── Gmail Setup Screen ───────────────────────────────────────────────────────

function GmailSetupScreen({ status }: { status: AuthStatus }) {
  return (
    <div className="flex flex-col items-center justify-center h-full gap-6 p-8">
      <div className="acm-card p-8 max-w-md w-full flex flex-col items-center gap-5 text-center">
        <div className="w-14 h-14 rounded-full bg-[var(--acm-elev)] border border-[var(--acm-border)] flex items-center justify-center">
          <Mail size={24} className="text-[var(--acm-accent)]" />
        </div>

        <div>
          <h2 className="text-[18px] font-semibold text-[var(--acm-fg)] mb-1">
            Gmail no está configurado
          </h2>
          <p className="text-[13px] text-[var(--acm-fg-3)]">
            Para usar el clasificador necesitas conectar tu cuenta de Gmail con OAuth2.
          </p>
        </div>

        {!status.configured && (
          <div className="w-full bg-[var(--acm-elev)] border border-[var(--acm-border)] rounded-[var(--acm-radius)] p-4 text-left">
            <p className="label mb-3">Paso 1 — Credenciales de Google</p>
            <ol className="text-[12px] text-[var(--acm-fg-2)] space-y-2 list-decimal list-inside">
              <li>
                Ve a{' '}
                <a
                  href="https://console.cloud.google.com/apis/credentials"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-[var(--acm-accent)] hover:underline inline-flex items-center gap-1"
                >
                  Google Cloud Console <ExternalLink size={11} />
                </a>
              </li>
              <li>Crea credenciales OAuth 2.0 (tipo: Aplicación de escritorio)</li>
              <li>Descarga el JSON y guárdalo como <code className="mono text-[11px] bg-[var(--acm-base)] px-1.5 py-0.5 rounded">config/google_credentials.json</code></li>
            </ol>
          </div>
        )}

        {status.configured && !status.has_token && (
          <div className="w-full bg-[var(--acm-elev)] border border-[var(--acm-border)] rounded-[var(--acm-radius)] p-4 text-left">
            <p className="label mb-2">Paso 2 — Autorizar acceso</p>
            <p className="text-[12px] text-[var(--acm-fg-2)]">
              Las credenciales están listas. Ejecuta una acción de Gmail desde el chat para que el sistema
              abra el flujo de autorización OAuth en el navegador.
            </p>
          </div>
        )}

        <div className="flex items-center gap-2 text-[12px] text-[var(--acm-fg-3)]">
          <AlertTriangle size={13} className="text-[var(--acm-warn)]" />
          <span>Reinicia el servidor después de guardar las credenciales</span>
        </div>
      </div>
    </div>
  );
}

// ─── Main Page ────────────────────────────────────────────────────────────────

export default function GmailClassifierPage() {
  const token = useAuthStore(s => s.token);

  const [authStatus, setAuthStatus] = useState<AuthStatus | null>(null);
  const [categories, setCategories] = useState<Category[]>([]);
  const [emails, setEmails] = useState<Email[]>([]);
  const [selectedCategoryId, setSelectedCategoryId] = useState<number | null>(null);
  const [selectedEmail, setSelectedEmail] = useState<Email | null>(null);
  const [processStatus, setProcessStatus] = useState<ProcessStatus>({
    running: false, processed: 0, total: 0, errors: 0, started_at: null, last_completed_at: null, cron_active: false,
  });
  const [sinceDate, setSinceDate] = useState('');
  const [showCategoryManager, setShowCategoryManager] = useState(false);
  const [showSettings, setShowSettings] = useState(false);
  const [showSuggestions, setShowSuggestions] = useState(false);
  const [suggestions, setSuggestions] = useState<any[]>([]);
  const [suggesting, setSuggesting] = useState(false);
  const [autoReplyCategoryIds, setAutoReplyCategoryIds] = useState<number[]>([]);
  const [suggestionTimeoutMs, setSuggestionTimeoutMs] = useState<number>(60000);

  const headers = { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' };

  const apiFetch = useCallback(async (path: string, opts?: RequestInit) => {
    return fetch(`${API}${path}`, { ...opts, headers: { ...headers, ...(opts?.headers ?? {}) } });
  }, [token]); // eslint-disable-line react-hooks/exhaustive-deps

  const fetchAuthStatus = useCallback(async () => {
    try {
      const res = await apiFetch('/auth-status');
      if (res.ok) setAuthStatus(await res.json());
    } catch { /* ignore */ }
  }, [apiFetch]);

  const fetchSinceDate = useCallback(async () => {
    try {
      const res = await apiFetch('/settings');
      if (res.ok) {
        const s = await res.json();
        if (s.since_date_default) setSinceDate(s.since_date_default);
        const cats = s?.autoreply_enabled_categories;
        try {
          const parsed = cats ? JSON.parse(cats) : [];
          if (Array.isArray(parsed)) setAutoReplyCategoryIds(parsed);
        } catch { /* malformed setting — keep default [] */ }
        const timeoutSecs = parseInt(s?.autoreply_timeout_seconds ?? '60', 10);
        if (!isNaN(timeoutSecs) && timeoutSecs > 0) setSuggestionTimeoutMs(timeoutSecs * 1000);
      }
    } catch { /* ignore */ }
  }, [apiFetch]);

  const fetchCategories = useCallback(async () => {
    const res = await apiFetch('/categories');
    if (res.ok) setCategories(await res.json());
  }, [apiFetch]);

  const fetchEmails = useCallback(async () => {
    const params = new URLSearchParams({ page: '1', per_page: '50' });
    if (selectedCategoryId !== null) params.set('category_id', String(selectedCategoryId));
    const res = await apiFetch(`/emails?${params}`);
    if (res.ok) {
      const data = await res.json();
      setEmails(data.items);
    }
  }, [apiFetch, selectedCategoryId]);

  const pollStatus = useCallback(async () => {
    const res = await apiFetch('/process/status');
    if (!res.ok) return;
    const status: ProcessStatus = await res.json();
    setProcessStatus(status);
    if (status.running) {
      setTimeout(pollStatus, 1500);
    } else if (status.total > 0) {
      fetchEmails();
      fetchCategories();
    }
  }, [apiFetch, fetchEmails, fetchCategories]);

  useEffect(() => {
    fetchAuthStatus();
    fetchSinceDate();
    fetchCategories();
    fetchEmails();
    pollStatus();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Silent background poll every 30s to catch cron-triggered runs
  useEffect(() => {
    const interval = setInterval(async () => {
      try {
        const res = await apiFetch('/process/status');
        if (!res.ok) return;
        const next: ProcessStatus = await res.json();
        setProcessStatus(prev => {
          // If a background run just completed (new last_completed_at), refresh data
          if (!next.running && next.last_completed_at && next.last_completed_at !== prev.last_completed_at) {
            fetchEmails();
            fetchCategories();
          }
          return next;
        });
      } catch { /* ignore */ }
    }, 30_000);
    return () => clearInterval(interval);
  }, [apiFetch, fetchEmails, fetchCategories]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    fetchEmails();
  }, [fetchEmails]);

  const handleProcess = async () => {
    if (!sinceDate) {
      alert('Selecciona una fecha de inicio');
      return;
    }
    const formatted = sinceDate.replace(/-/g, '/');
    const res = await apiFetch('/process', {
      method: 'POST',
      body: JSON.stringify({ since_date: formatted }),
    });
    if (res.ok) {
      setProcessStatus(p => ({ ...p, running: true, processed: 0, total: 0, errors: 0, started_at: new Date().toISOString() }));
      setTimeout(pollStatus, 1000);
    } else {
      const err = await res.json().catch(() => ({}));
      alert((err as any).detail || 'Error al iniciar el proceso');
    }
  };

  const handleEmailSelect = (email: Email) => {
    setSelectedEmail(email);
    if (!email.is_read) void handleEmailRead(email.id, true);
  };

  const handleEmailRead = async (emailId: number, isRead: boolean) => {
    await apiFetch(`/emails/${emailId}/read`, {
      method: 'PATCH',
      body: JSON.stringify({ is_read: isRead }),
    });
    setEmails(prev => prev.map(e => e.id === emailId ? { ...e, is_read: isRead ? 1 : 0 } : e));
    setSelectedEmail(prev => prev?.id === emailId ? { ...prev, is_read: isRead ? 1 : 0 } : prev);
  };

  const handleRecategorize = async (emailId: number, categoryId: number) => {
    const res = await apiFetch(`/emails/${emailId}/category`, {
      method: 'PATCH',
      body: JSON.stringify({ category_id: categoryId }),
    });
    if (res.ok) {
      fetchEmails();
      fetchCategories();
      setSelectedEmail(prev => prev?.id === emailId ? { ...prev, category_id: categoryId } : prev);
    }
  };

  const handleReply = async (emailId: number, body: string): Promise<boolean> => {
    const res = await apiFetch(`/emails/${emailId}/reply`, {
      method: 'POST',
      body: JSON.stringify({ body }),
    });
    if (res.ok) {
      setEmails(prev => prev.map(e => e.id === emailId ? { ...e, is_replied: 1, is_read: 1 } : e));
      setSelectedEmail(prev => prev?.id === emailId ? { ...prev, is_replied: 1, is_read: 1 } : prev);
      return true;
    }
    return false;
  };

  const notReady = authStatus !== null && !authStatus.ready;

  return (
    <AppLayout>
      <div className="flex flex-col h-screen overflow-hidden">
        {/* Page header */}
        <div className="px-6 pt-6 pb-4 border-b border-[var(--acm-border)] flex-shrink-0">
          <span className="acm-breadcrumb">/ gmail</span>
          <div className="flex items-end justify-between gap-4">
            <div>
              <h1 className="text-[22px] font-semibold tracking-[-0.01em] text-[var(--acm-fg)]">
                Gmail Classifier
              </h1>
              <div className="flex items-center gap-2 mt-0.5">
                <p className="text-[12px] text-[var(--acm-fg-3)]">
                  Clasifica correos con IA en categorías personalizadas
                </p>
                {processStatus.last_completed_at && (
                  <>
                    <span className="text-[var(--acm-fg-4)] text-[11px]">·</span>
                    <span className="text-[11px] text-[var(--acm-fg-4)] flex items-center gap-1">
                      <span className="dot dot-ok" />
                      Actualizado {timeAgoShort(processStatus.last_completed_at)}
                    </span>
                  </>
                )}
                {processStatus.running && (
                  <>
                    <span className="text-[var(--acm-fg-4)] text-[11px]">·</span>
                    <span className="text-[11px] text-[var(--acm-accent)] acm-pulse">
                      Clasificando…
                    </span>
                  </>
                )}
                {!processStatus.running && processStatus.cron_active && (
                  <>
                    <span className="text-[var(--acm-fg-4)] text-[11px]">·</span>
                    <span className="text-[11px] text-[var(--acm-fg-4)] flex items-center gap-1">
                      <span className="dot dot-ok" /> Cron activo
                    </span>
                  </>
                )}
              </div>
            </div>

            {/* Toolbar */}
            {!notReady && (
              <div className="flex items-center gap-2 pb-1">
                <div className="flex items-center gap-2">
                  <span className="text-[11px] text-[var(--acm-fg-4)] whitespace-nowrap">
                    Clasificando correos desde:
                  </span>
                  <input
                    type="date"
                    value={sinceDate}
                    onChange={async e => {
                      setSinceDate(e.target.value);
                      await apiFetch('/settings', {
                        method: 'PUT',
                        body: JSON.stringify({ since_date_default: e.target.value }),
                      });
                    }}
                    className="bg-[var(--acm-elev)] border border-[var(--acm-border)] text-[var(--acm-fg)] text-[12px] rounded-[var(--acm-radius)] px-3 py-1.5 outline-none focus:border-[var(--acm-accent)] transition-colors"
                  />
                </div>
                {processStatus.running ? (
                  <button
                    onClick={async () => {
                      await apiFetch('/process/stop', { method: 'POST' });
                    }}
                    className="btn-secondary text-[12px] py-[7px] px-3 border-[var(--acm-err)] text-[var(--acm-err)] hover:border-[var(--acm-err)]"
                  >
                    <Square size={12} />
                    Detener
                  </button>
                ) : (
                  <button
                    onClick={handleProcess}
                    className="btn-primary text-[12px] py-[7px] px-3"
                  >
                    <RefreshCw size={13} />
                    Procesar
                  </button>
                )}
                <button
                  onClick={async () => {
                    setSuggesting(true);
                    try {
                      const res = await apiFetch('/suggest-categories', { method: 'POST' });
                      const data = await res.json();
                      if (res.ok) {
                        setSuggestions(data.suggestions ?? []);
                        setShowSuggestions(true);
                      } else {
                        alert(`Error al sugerir categorías: ${data.detail ?? 'Error desconocido'}`);
                      }
                    } catch (e) {
                      alert('Error de conexión al sugerir categorías');
                    } finally {
                      setSuggesting(false);
                    }
                  }}
                  disabled={suggesting}
                  className="btn-secondary text-[12px] py-[7px] px-3"
                  title="Sugerir categorías con IA"
                >
                  <Sparkles size={13} className={suggesting ? 'animate-pulse' : ''} />
                  {suggesting ? 'Analizando…' : 'Sugerir'}
                </button>
                <Link
                  href="/gmail-classifier/stats"
                  className="btn-secondary text-[12px] py-[7px] px-3 flex items-center gap-1"
                  title="Estadísticas"
                >
                  <BarChart3 size={13} />
                </Link>
                <button
                  onClick={() => setShowSettings(true)}
                  className="btn-secondary text-[12px] py-[7px] px-3"
                  title="Configuración"
                >
                  <Settings size={13} />
                </button>
              </div>
            )}
          </div>
        </div>

        {/* Gmail not configured */}
        {notReady ? (
          <GmailSetupScreen status={authStatus!} />
        ) : (
          <>
            {/* Progress */}
            {(processStatus.running || processStatus.total > 0) && (
              <div className="px-6 py-2 border-b border-[var(--acm-border)] flex-shrink-0">
                <ProcessingProgress
                  running={processStatus.running}
                  processed={processStatus.processed}
                  total={processStatus.total}
                />
              </div>
            )}

            {/* Category tabs */}
            <div className="flex-shrink-0 border-b border-[var(--acm-border)]">
              <CategoryTabs
                categories={categories}
                selectedId={selectedCategoryId}
                onSelect={id => { setSelectedCategoryId(id); setSelectedEmail(null); }}
                onManage={() => setShowCategoryManager(true)}
              />
            </div>

            {/* Split view */}
            <div className="flex flex-1 min-h-0">
              <EmailList
                emails={emails}
                selectedId={selectedEmail?.id ?? null}
                onSelect={handleEmailSelect}
              />
              <EmailDetail
                email={selectedEmail}
                categories={categories}
                onReadToggle={handleEmailRead}
                onRecategorize={handleRecategorize}
                onReply={handleReply}
                autoReplyCategoryIds={autoReplyCategoryIds}
                token={token ?? undefined}
                suggestionTimeoutMs={suggestionTimeoutMs}
              />
            </div>
          </>
        )}

        {/* Modals */}
        {showCategoryManager && (
          <CategoryManager
            categories={categories}
            token={token ?? ''}
            onClose={() => setShowCategoryManager(false)}
            onSaved={() => { fetchCategories(); fetchEmails(); }}
          />
        )}
        {showSettings && (
          <PluginSettings
            token={token ?? ''}
            onClose={() => setShowSettings(false)}
            onAutoReplyChange={setAutoReplyCategoryIds}
            onAutoReplyTimeoutChange={(secs) => setSuggestionTimeoutMs(secs * 1000)}
          />
        )}

        {showSuggestions && (
          <SuggestionsModal
            suggestions={suggestions}
            token={token ?? ''}
            sinceDate={sinceDate}
            onClose={() => setShowSuggestions(false)}
            onCreated={async () => {
              await fetchCategories();
              setShowSuggestions(false);
              // Auto-start classification if there's a date configured
              if (sinceDate) {
                await handleProcess();
              }
            }}
          />
        )}
      </div>
    </AppLayout>
  );
}

// ─── Suggestions Modal ────────────────────────────────────────────────────────

function SuggestionsModal({ suggestions, token, sinceDate, onClose, onCreated }: {
  suggestions: any[];
  token: string;
  sinceDate: string;
  onClose: () => void;
  onCreated: () => void;
}) {
  const [selected, setSelected] = useState<Set<number>>(new Set(suggestions.map((_, i) => i)));
  const [saving, setSaving] = useState(false);

  const toggle = (i: number) => setSelected(prev => {
    const next = new Set(prev);
    next.has(i) ? next.delete(i) : next.add(i);
    return next;
  });

  const handleCreate = async () => {
    setSaving(true);
    const headers = { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' };
    try {
      for (const i of selected) {
        await fetch('/api/gmail-classifier/categories', {
          method: 'POST', headers,
          body: JSON.stringify(suggestions[i]),
        });
      }
      onCreated();
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50">
      <div className="bg-[var(--acm-base)] border border-[var(--acm-border)] rounded-[var(--acm-radius)] w-full max-w-md shadow-2xl">
        <div className="px-5 py-4 border-b border-[var(--acm-border)]">
          <span className="acm-breadcrumb">/ gmail / sugerencias IA</span>
          <h2 className="text-[15px] font-semibold text-[var(--acm-fg)]">Categorías sugeridas</h2>
          <p className="text-[11px] text-[var(--acm-fg-4)] mt-0.5">
            Basadas en tus correos más recientes. Selecciona las que quieras crear.
          </p>
        </div>

        <div className="px-5 py-3 space-y-2">
          {suggestions.map((s, i) => (
            <button
              key={i}
              onClick={() => toggle(i)}
              className={`w-full flex items-start gap-3 p-3 rounded-[var(--acm-radius)] border text-left transition-colors ${
                selected.has(i)
                  ? 'border-[var(--acm-accent)] bg-[var(--acm-accent-tint)]'
                  : 'border-[var(--acm-border)] hover:border-[var(--acm-border-strong)]'
              }`}
            >
              <div className="w-3 h-3 rounded-full flex-shrink-0 mt-0.5" style={{ backgroundColor: s.color }} />
              <div className="flex-1 min-w-0">
                <p className="text-[13px] font-medium text-[var(--acm-fg)]">{s.name}</p>
                <p className="text-[11px] text-[var(--acm-fg-4)] mt-0.5 leading-snug">{s.description}</p>
              </div>
              <div className={`w-4 h-4 rounded border flex-shrink-0 mt-0.5 flex items-center justify-center transition-colors ${
                selected.has(i) ? 'bg-[var(--acm-accent)] border-[var(--acm-accent)]' : 'border-[var(--acm-border-strong)]'
              }`}>
                {selected.has(i) && <span className="text-[oklch(0.18_0.015_80)] text-[10px] font-bold">✓</span>}
              </div>
            </button>
          ))}
        </div>

        <div className="px-5 py-4 border-t border-[var(--acm-border)] flex items-center justify-between">
          <span className="text-[11px] text-[var(--acm-fg-4)]">{selected.size} seleccionadas</span>
          <div className="flex gap-2">
            <button onClick={onClose} className="btn-secondary text-[12px] py-[7px] px-3">Cancelar</button>
            <button
              onClick={handleCreate}
              disabled={saving || selected.size === 0}
              className="btn-primary text-[12px] py-[7px] px-3"
            >
              {saving ? 'Creando y clasificando…' : sinceDate ? `Crear y clasificar` : `Crear ${selected.size}`}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
