'use client';

import { useState, useEffect, useRef, useCallback } from 'react';
import {
  Mail, ChevronDown, ChevronUp, ChevronRight,
  CornerUpLeft, ExternalLink,
  Paperclip, Download, FileText, Image as ImageIcon, File,
} from 'lucide-react';
import type { Thread } from './EmailList';

// ─── Types ────────────────────────────────────────────────────────────────────

interface Attachment {
  attachment_id: string;
  filename: string;
  mime_type: string;
  size: number;
}

interface Message {
  id: number;
  gmail_id: string;
  thread_id: string | null;
  subject: string;
  sender_name: string;
  sender_email: string;
  snippet: string;
  body_text: string;
  body_html: string;
  category_id: number;
  is_read: number;
  is_replied: number;
  received_at: string;
}

interface Category {
  id: number;
  name: string;
  color: string;
}

interface EmailDetailProps {
  thread: Thread | null;
  categories: Category[];
  onRecategorizeThread: (threadId: string, categoryId: number) => void;
  onReply: (emailId: number, body: string) => Promise<boolean>;
  autoReplyCategoryIds?: number[];
  token?: string;
  suggestionTimeoutMs?: number;
  authEmail?: string;
  onThreadRead?: (threadId: string) => void;
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function formatBytes(n: number): string {
  if (!n) return '';
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

function attachmentIcon(mime: string) {
  if (mime.startsWith('image/')) return ImageIcon;
  if (mime === 'application/pdf' || mime.startsWith('text/')) return FileText;
  return File;
}

function formatDate(iso: string): string {
  try {
    return new Date(iso).toLocaleString('es-CO', {
      day: '2-digit', month: 'long', year: 'numeric',
      hour: '2-digit', minute: '2-digit',
    });
  } catch { return ''; }
}

function senderInitial(name: string, email: string): string {
  return (name || email || '?')[0].toUpperCase();
}

const HTML_BASE_STYLES = `
  <style>
    * { box-sizing: border-box; }
    html, body { max-width: 100%; }
    body {
      font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
      font-size: 14px; line-height: 1.6; color: #1a1a1a;
      background: #ffffff; margin: 0; padding: 16px;
      word-break: break-word; overflow-wrap: anywhere;
    }
    img { max-width: 100% !important; height: auto !important; }
    a { color: #2563eb; }
    p { margin: 0 0 10px; }
    h1, h2, h3 { line-height: 1.3; }
    pre, code { font-size: 12px; white-space: pre-wrap; overflow-x: auto; }
    table { max-width: 100% !important; border-collapse: collapse; }
    td, th { word-break: break-word; }
    blockquote { margin: 0 0 10px; padding: 4px 0 4px 12px; border-left: 3px solid #d1d5db; color: #4b5563; }
    hr { border: none; border-top: 1px solid #e5e7eb; margin: 16px 0; }
  </style>
`;

function HtmlEmail({ html }: { html: string }) {
  const src = `<!DOCTYPE html><html><head><meta charset="utf-8">${HTML_BASE_STYLES}</head><body>${html}</body></html>`;
  return (
    <iframe
      srcDoc={src}
      sandbox="allow-same-origin"
      className="w-full border-0 rounded-[var(--acm-radius)] bg-white"
      style={{ minHeight: '200px', height: '100%' }}
      onLoad={e => {
        const frame = e.currentTarget;
        try {
          const h = frame.contentDocument?.body?.scrollHeight;
          if (h) frame.style.height = `${h + 32}px`;
        } catch { /* cross-origin */ }
      }}
    />
  );
}

function PlainTextBody({ text }: { text: string }) {
  const paragraphs = text.split(/\n{2,}/).map(p => p.trim()).filter(Boolean);
  return (
    <div className="space-y-3">
      {paragraphs.map((para, i) => (
        <p key={i} className="text-[13px] text-[var(--acm-fg-2)] leading-[1.7] break-words">
          {para.split('\n').map((line, j) => (
            <span key={j}>{line}{j < para.split('\n').length - 1 && <br />}</span>
          ))}
        </p>
      ))}
    </div>
  );
}

// ─── MessageCard ──────────────────────────────────────────────────────────────

function MessageCard({
  msg, isExpanded, onToggle,
  attachments, onDownload, onPreview, downloadingId, previewingId,
  resolvedHtml,
}: {
  msg: Message;
  isExpanded: boolean;
  onToggle: () => void;
  attachments: Attachment[];
  onDownload: (att: Attachment) => void;
  onPreview: (att: Attachment) => void;
  downloadingId: string | null;
  previewingId: string | null;
  resolvedHtml: string | null;
}) {
  const looksLikeHtml = (s: string) =>
    /<!DOCTYPE|<html|<body|<div|<table|<td|<span|<p\s|<br|@media|\.u-row/i.test(s.slice(0, 500));
  const storedHtml = msg.body_html || (looksLikeHtml(msg.body_text || '') ? msg.body_text : '');
  const htmlToRender = resolvedHtml ?? storedHtml;
  const hasHtml = !!htmlToRender;
  const bodyContent = msg.body_text || msg.snippet;

  return (
    <div className={`border border-[var(--acm-border)] rounded-[var(--acm-radius)] overflow-hidden transition-colors ${
      isExpanded ? 'bg-[var(--acm-base)]' : 'bg-[var(--acm-elev)] hover:bg-[var(--acm-card)]'
    }`}>
      {/* Header — always visible, click to toggle */}
      <button
        onClick={onToggle}
        className="w-full flex items-center gap-3 px-4 py-3 text-left"
      >
        <div className="w-7 h-7 rounded-full bg-[var(--acm-accent)] text-[oklch(0.18_0.015_80)] text-[11px] font-bold flex items-center justify-center flex-shrink-0 select-none">
          {senderInitial(msg.sender_name, msg.sender_email)}
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-[12px] font-medium text-[var(--acm-fg)] truncate">
              {msg.sender_name || msg.sender_email}
            </span>
            {msg.sender_name && (
              <span className="text-[11px] text-[var(--acm-fg-4)] truncate hidden md:block">
                &lt;{msg.sender_email}&gt;
              </span>
            )}
          </div>
          {!isExpanded && (
            <p className="text-[11px] text-[var(--acm-fg-4)] truncate mt-0.5">{msg.snippet}</p>
          )}
        </div>
        <div className="flex items-center gap-2 flex-shrink-0">
          <span className="text-[10px] text-[var(--acm-fg-4)] mono hidden sm:block">{formatDate(msg.received_at)}</span>
          {isExpanded
            ? <ChevronDown size={13} className="text-[var(--acm-fg-4)]" />
            : <ChevronRight size={13} className="text-[var(--acm-fg-4)]" />}
        </div>
      </button>

      {/* Body — only when expanded */}
      {isExpanded && (
        <div className="px-4 pb-4 pt-1">
          <p className="text-[10px] text-[var(--acm-fg-4)] mono mb-3 sm:hidden">{formatDate(msg.received_at)}</p>
          {hasHtml ? (
            <HtmlEmail html={htmlToRender} />
          ) : bodyContent ? (
            <PlainTextBody text={bodyContent} />
          ) : (
            <p className="text-[12px] text-[var(--acm-fg-4)] italic">
              Sin contenido — reprocesa para cargar el cuerpo del correo.
            </p>
          )}

          {attachments.length > 0 && (
            <div className="mt-4 pt-3 border-t border-[var(--acm-border)]">
              <div className="flex items-center gap-1.5 mb-2">
                <Paperclip size={12} className="text-[var(--acm-fg-4)]" />
                <span className="text-[11px] text-[var(--acm-fg-4)]">
                  {attachments.length} adjunto{attachments.length === 1 ? '' : 's'}
                </span>
              </div>
              <div className="flex flex-wrap gap-2">
                {attachments.map(att => {
                  const Icon = attachmentIcon(att.mime_type);
                  const isDownloading = downloadingId === att.attachment_id;
                  const isPreviewing = previewingId === att.attachment_id;
                  const isBusy = isDownloading || isPreviewing;
                  const isPreviewable = att.mime_type.startsWith('image/') || att.mime_type === 'application/pdf';
                  return (
                    <div
                      key={att.attachment_id}
                      className="flex items-center gap-2 max-w-[260px] bg-[var(--acm-card)] border border-[var(--acm-border)] rounded-[var(--acm-radius)] px-2.5 py-1.5 hover:border-[var(--acm-accent)] transition-colors"
                    >
                      <Icon size={15} className="text-[var(--acm-accent)] flex-shrink-0" />
                      <span className="flex flex-col min-w-0 flex-1">
                        <span className="text-[12px] text-[var(--acm-fg-2)] truncate">{att.filename}</span>
                        {att.size > 0 && (
                          <span className="text-[10px] text-[var(--acm-fg-4)]">{formatBytes(att.size)}</span>
                        )}
                      </span>
                      {isPreviewable && (
                        <button
                          onClick={() => onPreview(att)}
                          disabled={isBusy}
                          title="Abrir en el navegador"
                          className="p-0.5 rounded hover:text-[var(--acm-accent)] text-[var(--acm-fg-4)] transition-colors disabled:opacity-40"
                        >
                          {isPreviewing
                            ? <div className="h-3 w-3 rounded-full border-2 border-[var(--acm-fg-4)] border-t-transparent animate-spin" />
                            : <ExternalLink size={13} />}
                        </button>
                      )}
                      <button
                        onClick={() => onDownload(att)}
                        disabled={isBusy}
                        title="Descargar"
                        className="p-0.5 rounded hover:text-[var(--acm-accent)] text-[var(--acm-fg-4)] transition-colors disabled:opacity-40"
                      >
                        {isDownloading
                          ? <div className="h-3 w-3 rounded-full border-2 border-[var(--acm-fg-4)] border-t-transparent animate-spin" />
                          : <Download size={13} />}
                      </button>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          <div className="mt-3 flex justify-end">
            <a
              href={`https://mail.google.com/mail/u/0/#all/${msg.gmail_id}`}
              target="_blank"
              rel="noopener noreferrer"
              className="btn-secondary text-[11px] py-[5px] px-2.5"
            >
              <ExternalLink size={12} /> Ver en Gmail
            </a>
          </div>
        </div>
      )}
    </div>
  );
}

// ─── Main component ───────────────────────────────────────────────────────────

export function EmailDetail({
  thread, categories, onRecategorizeThread, onReply,
  autoReplyCategoryIds, token, suggestionTimeoutMs,
  authEmail, onThreadRead,
}: EmailDetailProps) {

  // ── State ──────────────────────────────────────────────────────────────────
  const [messages, setMessages] = useState<Message[]>([]);
  const [loadingMessages, setLoadingMessages] = useState(false);
  const [expandedIds, setExpandedIds] = useState<Set<number>>(new Set());
  const [replyOpen, setReplyOpen] = useState(false);
  const [replyText, setReplyText] = useState('');
  const [sending, setSending] = useState(false);
  const [replySuccess, setReplySuccess] = useState(false);
  const [replyError, setReplyError] = useState('');
  const [suggestionLoading, setSuggestionLoading] = useState(false);
  const [suggestionError, setSuggestionError] = useState<string | null>(null);
  const [savingDraft, setSavingDraft] = useState(false);
  const [draftSaved, setDraftSaved] = useState(false);
  const [msgAttachments, setMsgAttachments] = useState<Map<number, Attachment[]>>(new Map());
  const [msgResolvedHtml, setMsgResolvedHtml] = useState<Map<number, string>>(new Map());
  const [downloadingId, setDownloadingId] = useState<string | null>(null);
  const [previewingId, setPreviewingId] = useState<string | null>(null);

  // ── Refs ───────────────────────────────────────────────────────────────────
  const suggestionCache = useRef<Map<number, string>>(new Map());
  const loadedAttachments = useRef<Set<number>>(new Set());
  const loadedHtml = useRef<Set<number>>(new Set());

  // ── loadAssets — MUST be declared before effects and callbacks that use it ─
  const loadAssets = useCallback((msg: Message, tok: string) => {
    if (!loadedAttachments.current.has(msg.id)) {
      loadedAttachments.current.add(msg.id);
      fetch(`/api/gmail-classifier/emails/${msg.id}/attachments`, {
        headers: { Authorization: `Bearer ${tok}` },
      })
        .then(r => r.ok ? r.json() : { items: [] })
        .then(d => setMsgAttachments(prev => new Map(prev).set(msg.id, d.items ?? [])))
        .catch(() => { /* ignore */ });
    }
    const stored = `${msg.body_html || ''}${msg.body_text || ''}`;
    if (!loadedHtml.current.has(msg.id) && stored.includes('cid:')) {
      loadedHtml.current.add(msg.id);
      fetch(`/api/gmail-classifier/emails/${msg.id}/html`, {
        headers: { Authorization: `Bearer ${tok}` },
      })
        .then(r => r.ok ? r.json() : null)
        .then(d => { if (d?.resolved && d.html) setMsgResolvedHtml(prev => new Map(prev).set(msg.id, d.html)); })
        .catch(() => { /* ignore */ });
    }
  }, []); // stable — only refs and stable setters

  // ── toggleExpanded — depends on loadAssets ─────────────────────────────────
  const toggleExpanded = useCallback((msg: Message) => {
    setExpandedIds(prev => {
      const next = new Set(prev);
      if (next.has(msg.id)) {
        next.delete(msg.id);
      } else {
        next.add(msg.id);
        if (token) loadAssets(msg, token);
      }
      return next;
    });
  }, [token, loadAssets]);

  // ── Load messages when thread changes ──────────────────────────────────────
  useEffect(() => {
    if (!thread || !token) {
      setMessages([]);
      setExpandedIds(new Set());
      return;
    }
    let cancelled = false;
    setLoadingMessages(true);
    setMessages([]);
    setExpandedIds(new Set());
    setMsgAttachments(new Map());
    setMsgResolvedHtml(new Map());
    loadedAttachments.current = new Set();
    loadedHtml.current = new Set();
    setReplyText('');
    setDraftSaved(false);
    setSuggestionError(null);
    setReplyOpen(false);

    fetch(`/api/gmail-classifier/threads/${thread.thread_id}/messages`, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then(r => r.json())
      .then((data: { items: Message[] }) => {
        if (cancelled) return;
        const items = data.items ?? [];
        setMessages(items);
        if (items.length > 0) {
          const last = items[items.length - 1];
          setExpandedIds(new Set([last.id]));
          loadAssets(last, token);
        }
        // Mark unread messages as read silently
        const hasUnread = items.some(m => !m.is_read);
        for (const msg of items) {
          if (!msg.is_read) {
            fetch(`/api/gmail-classifier/emails/${msg.id}/read`, {
              method: 'PATCH',
              headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
              body: JSON.stringify({ is_read: true }),
            }).catch(() => { /* best-effort */ });
          }
        }
        if (hasUnread) onThreadRead?.(thread.thread_id);
      })
      .catch(() => { /* ignore */ })
      .finally(() => { if (!cancelled) setLoadingMessages(false); });

    return () => { cancelled = true; };
  }, [thread?.thread_id, token, loadAssets]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Auto-reply suggestion for last incoming message ────────────────────────
  const lastMessage = messages[messages.length - 1] ?? null;
  const isLastFromUser = !!(authEmail && lastMessage &&
    lastMessage.sender_email.toLowerCase() === authEmail.toLowerCase());
  const categoryEnabled = !!(thread && autoReplyCategoryIds?.includes(thread.category_id));
  const shouldSuggest = categoryEnabled && !isLastFromUser && !!lastMessage;

  useEffect(() => {
    setReplyText('');
    setDraftSaved(false);
    setSuggestionError(null);
    if (!shouldSuggest || !token || !lastMessage) return;

    const cached = suggestionCache.current.get(lastMessage.id);
    if (cached !== undefined) { setReplyText(cached); return; }

    let timedOut = false;
    const controller = new AbortController();
    const timeoutId = setTimeout(() => { timedOut = true; controller.abort(); }, suggestionTimeoutMs ?? 60000);
    setSuggestionLoading(true);

    fetch(`/api/gmail-classifier/emails/${lastMessage.id}/suggest-reply`, {
      headers: { Authorization: `Bearer ${token}` },
      signal: controller.signal,
    })
      .then(r => r.json())
      .then(d => {
        if (d.eligible && d.body) {
          suggestionCache.current.set(lastMessage.id, d.body);
          setReplyText(d.body);
          setDraftSaved(d.from_draft ?? false);
        }
      })
      .catch(err => {
        if (err.name === 'AbortError' && !timedOut) return;
        const secs = Math.round((suggestionTimeoutMs ?? 60000) / 1000);
        setSuggestionError(timedOut
          ? `Tiempo de espera agotado (${secs}s)`
          : `Error: ${err?.message || 'desconocido'}`);
      })
      .finally(() => { setSuggestionLoading(false); clearTimeout(timeoutId); });

    return () => { controller.abort(); clearTimeout(timeoutId); };
  }, [lastMessage?.id, shouldSuggest, token]); // eslint-disable-line react-hooks/exhaustive-deps

  // Reply target: last message NOT sent by the user
  const replyTarget = [...messages].reverse().find(m =>
    m.sender_email.toLowerCase() !== (authEmail || '').toLowerCase()
  ) ?? lastMessage;

  // ── Action handlers ────────────────────────────────────────────────────────
  const handleSendReply = async () => {
    if (!replyText.trim() || !replyTarget) return;
    setSending(true);
    setReplyError('');
    const ok = await onReply(replyTarget.id, replyText.trim());
    setSending(false);
    if (ok) {
      setReplyText('');
      setReplySuccess(true);
      setReplyOpen(false);
      setTimeout(() => setReplySuccess(false), 4000);
    } else {
      setReplyError('Error al enviar. Verifica la conexión con Gmail.');
    }
  };

  const downloadAttachment = useCallback(async (msgId: number, att: Attachment) => {
    if (!token) return;
    setDownloadingId(att.attachment_id);
    try {
      const res = await fetch(`/api/gmail-classifier/emails/${msgId}/attachments/${att.attachment_id}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) throw new Error();
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url; a.download = att.filename;
      document.body.appendChild(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 60_000);
    } catch { /* ignore */ }
    finally { setDownloadingId(null); }
  }, [token]);

  const previewAttachment = useCallback(async (msgId: number, att: Attachment) => {
    if (!token) return;
    setPreviewingId(att.attachment_id);
    try {
      const res = await fetch(`/api/gmail-classifier/emails/${msgId}/attachments/${att.attachment_id}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) throw new Error();
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      window.open(url, '_blank', 'noopener');
      setTimeout(() => URL.revokeObjectURL(url), 60_000);
    } catch { /* ignore */ }
    finally { setPreviewingId(null); }
  }, [token]);

  // ── Empty state ────────────────────────────────────────────────────────────
  if (!thread) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center gap-3 text-[var(--acm-fg-4)]">
        <Mail size={32} className="opacity-30" />
        <p className="text-[13px]">Selecciona un correo</p>
      </div>
    );
  }

  const isReplied = !!(authEmail && thread.latest_sender_email &&
    thread.latest_sender_email.toLowerCase() === authEmail.toLowerCase());

  // ── Render ─────────────────────────────────────────────────────────────────
  return (
    <div className="flex-1 flex flex-col min-h-0 overflow-hidden">

      {/* ── Thread header ─────────────────────────────────────────────────────── */}
      <div className="px-6 pt-4 pb-3 border-b border-[var(--acm-border)] flex-shrink-0">
        <h2 className="text-[15px] font-semibold text-[var(--acm-fg)] leading-snug mb-3">
          {thread.subject}
        </h2>
        <div className="flex items-center gap-2 flex-wrap">
          {/* Category */}
          <div className="relative">
            <select
              value={thread.category_id}
              onChange={e => onRecategorizeThread(thread.thread_id, Number(e.target.value))}
              className="bg-[var(--acm-card)] border border-[var(--acm-border)] text-[var(--acm-fg-2)] text-[12px] rounded-[var(--acm-radius)] px-3 py-1.5 pr-7 appearance-none outline-none focus:border-[var(--acm-accent)] transition-colors cursor-pointer"
            >
              {categories.map(c => (
                <option key={c.id} value={c.id}>{c.name}</option>
              ))}
            </select>
            <ChevronDown size={11} className="absolute right-2 top-2 text-[var(--acm-fg-4)] pointer-events-none" />
          </div>

          {/* Respondido badge — cuando el user autenticado es el último en escribir */}
          {isReplied && (
            <span className="text-[11px] text-[var(--acm-ok)] flex items-center gap-1">
              <span className="dot dot-ok" /> Respondido
            </span>
          )}

          {replySuccess && (
            <span className="text-[11px] text-[var(--acm-ok)]">✓ Respuesta enviada</span>
          )}

          {/* Reply button */}
          <button
            onClick={() => setReplyOpen(o => !o)}
            className="btn-secondary text-[11px] py-[5px] px-2.5 ml-auto"
          >
            <CornerUpLeft size={12} />
            {replyOpen ? 'Cerrar' : 'Responder'}
            {replyOpen ? <ChevronUp size={11} /> : null}
          </button>
        </div>
      </div>

      {/* ── Auto-reply feedback ────────────────────────────────────────────────── */}
      {suggestionLoading && (
        <div className="flex items-center gap-2 text-sm text-gray-500 dark:text-gray-400 px-6 py-2 flex-shrink-0">
          <div className="h-3 w-3 rounded-full border-2 border-current border-t-transparent animate-spin" />
          Generando respuesta…
        </div>
      )}
      {!suggestionLoading && replyText && shouldSuggest && (
        <div className="px-6 pt-2 flex-shrink-0">
          <span className="text-xs font-medium text-purple-600 dark:text-purple-400">Sugerencia IA ✦</span>
        </div>
      )}
      {suggestionError && (
        <p className="text-xs text-gray-400 dark:text-gray-500 px-6 pt-2 flex-shrink-0">{suggestionError}</p>
      )}

      {/* ── Conversation ──────────────────────────────────────────────────────── */}
      <div className="flex-1 overflow-y-auto acm-scroll min-h-0 px-4 py-4">
        {loadingMessages ? (
          <div className="flex items-center justify-center gap-2 py-8 text-[var(--acm-fg-4)] text-[12px]">
            <div className="h-3 w-3 rounded-full border-2 border-current border-t-transparent animate-spin" />
            Cargando conversación…
          </div>
        ) : messages.length === 0 ? (
          <p className="text-[12px] text-[var(--acm-fg-4)] text-center py-8">Sin mensajes en este hilo</p>
        ) : (
          <div className="space-y-2">
            {messages.map(msg => (
              <MessageCard
                key={msg.id}
                msg={msg}
                isExpanded={expandedIds.has(msg.id)}
                onToggle={() => toggleExpanded(msg)}
                attachments={msgAttachments.get(msg.id) ?? []}
                onDownload={att => downloadAttachment(msg.id, att)}
                onPreview={att => previewAttachment(msg.id, att)}
                downloadingId={downloadingId}
                previewingId={previewingId}
                resolvedHtml={msgResolvedHtml.get(msg.id) ?? null}
              />
            ))}
          </div>
        )}
      </div>

      {/* ── Reply composer ─────────────────────────────────────────────────────── */}
      {replyOpen && (
        <div className="px-6 py-4 border-t border-[var(--acm-border)] flex-shrink-0 bg-[var(--acm-base)]">
          <p className="text-[11px] text-[var(--acm-fg-4)] mb-2">
            <CornerUpLeft size={11} className="inline mr-1" />
            Responder a <span className="text-[var(--acm-fg-3)]">{replyTarget?.sender_email ?? ''}</span>
          </p>
          <textarea
            value={replyText}
            onChange={e => setReplyText(e.target.value)}
            placeholder="Escribe tu respuesta…"
            rows={5}
            autoFocus
            className="w-full bg-[var(--acm-elev)] border border-[var(--acm-border)] text-[var(--acm-fg)] text-[13px] rounded-[var(--acm-radius)] px-3 py-2.5 resize-y outline-none focus:border-[var(--acm-accent)] transition-colors placeholder:text-[var(--acm-fg-4)] leading-relaxed"
          />
          <div className="flex items-center justify-between mt-2">
            <span className="text-[11px] text-[var(--acm-err)]">{replyError}</span>
            <div className="flex gap-2">
              <button onClick={() => setReplyOpen(false)} className="btn-secondary text-[12px] py-[6px] px-3">
                Cancelar
              </button>
              {replyTarget && (
                <button
                  onClick={async () => {
                    if (!token) return;
                    setSavingDraft(true);
                    try {
                      const res = await fetch(`/api/gmail-classifier/emails/${replyTarget.id}/draft`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
                        body: JSON.stringify({ body: replyText }),
                      });
                      if (res.ok) setDraftSaved(true);
                    } finally { setSavingDraft(false); }
                  }}
                  disabled={savingDraft || !replyText.trim()}
                  className="btn-secondary text-[12px] py-[6px] px-3"
                >
                  {savingDraft ? 'Guardando...' : draftSaved ? 'Borrador guardado ✓' : 'Guardar como borrador'}
                </button>
              )}
              <button
                onClick={handleSendReply}
                disabled={sending || !replyText.trim()}
                className="btn-primary text-[12px] py-[6px] px-3"
              >
                {sending ? 'Enviando…' : 'Enviar'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
