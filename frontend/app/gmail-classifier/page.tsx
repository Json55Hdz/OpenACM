'use client';

import { useState, useEffect, useCallback } from 'react';
import { Mail, RefreshCw, Settings, AlertTriangle, ExternalLink } from 'lucide-react';
import { AppLayout } from '@/components/layout/app-layout';
import { useAuthStore } from '@/stores/auth-store';
import { CategoryTabs } from './components/CategoryTabs';
import { EmailList } from './components/EmailList';
import { EmailDetail } from './components/EmailDetail';
import { CategoryManager } from './components/CategoryManager';
import { ProcessingProgress } from './components/ProcessingProgress';
import { PluginSettings } from './components/PluginSettings';

const API = '/api/gmail-classifier';

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
  subject: string;
  sender_name: string;
  sender_email: string;
  snippet: string;
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
    running: false, processed: 0, total: 0, errors: 0, started_at: null,
  });
  const [sinceDate, setSinceDate] = useState('');
  const [showCategoryManager, setShowCategoryManager] = useState(false);
  const [showSettings, setShowSettings] = useState(false);

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
    fetchCategories();
    fetchEmails();
    pollStatus();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

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
      setProcessStatus({ running: true, processed: 0, total: 0, errors: 0, started_at: new Date().toISOString() });
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
              <p className="text-[12px] text-[var(--acm-fg-3)] mt-0.5">
                Clasifica correos con IA en categorías personalizadas
              </p>
            </div>

            {/* Toolbar */}
            {!notReady && (
              <div className="flex items-center gap-2 pb-1">
                <input
                  type="date"
                  value={sinceDate}
                  onChange={e => setSinceDate(e.target.value)}
                  className="bg-[var(--acm-elev)] border border-[var(--acm-border)] text-[var(--acm-fg)] text-[12px] rounded-[var(--acm-radius)] px-3 py-1.5 outline-none focus:border-[var(--acm-accent)] transition-colors"
                />
                <button
                  onClick={handleProcess}
                  disabled={processStatus.running}
                  className="btn-primary text-[12px] py-[7px] px-3"
                >
                  <RefreshCw size={13} className={processStatus.running ? 'animate-spin' : ''} />
                  {processStatus.running ? 'Procesando…' : 'Procesar'}
                </button>
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
          <PluginSettings token={token ?? ''} onClose={() => setShowSettings(false)} />
        )}
      </div>
    </AppLayout>
  );
}
