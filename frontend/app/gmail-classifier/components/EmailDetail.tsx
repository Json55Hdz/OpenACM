'use client';

import { useState, useEffect, useRef, useCallback } from 'react';
import { Mail, MailOpen, ChevronDown, CornerUpLeft, ExternalLink, ChevronUp, Paperclip, Download, FileText, Image as ImageIcon, File } from 'lucide-react';

interface Attachment {
  attachment_id: string;
  filename: string;
  mime_type: string;
  size: number;
}

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
  email: Email | null;
  categories: Category[];
  onReadToggle: (emailId: number, isRead: boolean) => void;
  onRecategorize: (emailId: number, categoryId: number) => void;
  onReply: (emailId: number, body: string) => Promise<boolean>;
  autoReplyCategoryIds?: number[]
  token?: string
  suggestionTimeoutMs?: number
}

// Inject base styles into HTML emails so they render cleanly in the iframe
const HTML_BASE_STYLES = `
  <style>
    * { box-sizing: border-box; }
    html, body { max-width: 100%; }
    body {
      font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
      font-size: 14px;
      line-height: 1.6;
      color: #1a1a1a;
      background: #ffffff;
      margin: 0;
      padding: 16px;
      word-break: break-word;
      overflow-wrap: anywhere;
    }
    img { max-width: 100% !important; height: auto !important; }
    a { color: #2563eb; }
    p { margin: 0 0 10px; }
    h1, h2, h3 { line-height: 1.3; }
    pre, code { font-size: 12px; white-space: pre-wrap; overflow-x: auto; }
    /* Marketing emails set huge fixed table widths — clamp so nothing overflows */
    table { max-width: 100% !important; border-collapse: collapse; }
    td, th { word-break: break-word; }
    blockquote {
      margin: 0 0 10px; padding: 4px 0 4px 12px;
      border-left: 3px solid #d1d5db; color: #4b5563;
    }
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
      style={{ minHeight: '300px', height: '100%' }}
      onLoad={e => {
        // Auto-resize iframe to content height
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

export function EmailDetail({ email, categories, onReadToggle, onRecategorize, onReply, autoReplyCategoryIds, token, suggestionTimeoutMs }: EmailDetailProps) {
  const [replyOpen, setReplyOpen] = useState(false);
  const [replyText, setReplyText] = useState('');
  const [sending, setSending] = useState(false);
  const [replySuccess, setReplySuccess] = useState(false);
  const [replyError, setReplyError] = useState('');
  const [suggestionLoading, setSuggestionLoading] = useState(false)
  const [suggestionError, setSuggestionError] = useState<string | null>(null)
  const [savingDraft, setSavingDraft] = useState(false)
  const [draftSaved, setDraftSaved] = useState(false)
  // Session cache: keeps generated suggestions in RAM so switching emails
  // and coming back doesn't cost another LLM call.
  const suggestionCache = useRef<Map<number, string>>(new Map())
  const [attachments, setAttachments] = useState<Attachment[]>([])
  const [downloadingId, setDownloadingId] = useState<string | null>(null)
  // Resolved HTML (inline cid: images turned into data URIs). null while loading
  // or when no resolution is needed; falls back to the stored body_html.
  const [resolvedHtml, setResolvedHtml] = useState<string | null>(null)

  // Fetch the attachment list whenever the open email changes.
  useEffect(() => {
    setAttachments([])
    if (!email || !token) return
    let cancelled = false
    fetch(`/api/gmail-classifier/emails/${email.id}/attachments`, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then(r => (r.ok ? r.json() : { items: [] }))
      .then(data => { if (!cancelled) setAttachments(data.items ?? []) })
      .catch(() => { /* attachments are best-effort */ })
    return () => { cancelled = true }
  }, [email?.id, token])

  // Resolve inline cid: images (the usual reason images "don't load"). Only hit
  // the API when the stored body actually references cid: — otherwise it renders fine.
  useEffect(() => {
    setResolvedHtml(null)
    if (!email || !token) return
    const stored = `${email.body_html || ''}${email.body_text || ''}`
    if (!stored.includes('cid:')) return
    let cancelled = false
    fetch(`/api/gmail-classifier/emails/${email.id}/html`, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then(r => (r.ok ? r.json() : null))
      .then(data => { if (!cancelled && data?.resolved && data.html) setResolvedHtml(data.html) })
      .catch(() => { /* fall back to stored html */ })
    return () => { cancelled = true }
  }, [email?.id, token])

  const downloadAttachment = useCallback(async (att: Attachment) => {
    if (!email || !token) return
    setDownloadingId(att.attachment_id)
    try {
      const res = await fetch(
        `/api/gmail-classifier/emails/${email.id}/attachments/${att.attachment_id}`,
        { headers: { Authorization: `Bearer ${token}` } },
      )
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const blob = await res.blob()
      const url = URL.createObjectURL(blob)
      const previewable = att.mime_type.startsWith('image/') || att.mime_type === 'application/pdf'
      if (previewable) {
        window.open(url, '_blank', 'noopener')
      } else {
        const a = document.createElement('a')
        a.href = url
        a.download = att.filename
        document.body.appendChild(a)
        a.click()
        a.remove()
      }
      setTimeout(() => URL.revokeObjectURL(url), 60_000)
    } catch (err) {
      console.error('[attachment] download failed:', err)
    } finally {
      setDownloadingId(null)
    }
  }, [email?.id, token])

  useEffect(() => {
    // Load from cache immediately to avoid flash of empty state
    const cached = email ? suggestionCache.current.get(email.id) : undefined
    setReplyText(cached ?? '')
    setDraftSaved(false)
    setSuggestionError(null)

    if (!email || !autoReplyCategoryIds || !token) return
    const categoryEnabled = autoReplyCategoryIds.includes(email.category_id)
    if (!categoryEnabled) return
    // Cache hit — no LLM call needed
    if (cached !== undefined) return

    let timedOut = false
    const controller = new AbortController()
    const timeoutId = setTimeout(() => {
      timedOut = true
      controller.abort()
    }, suggestionTimeoutMs ?? 60000)
    setSuggestionLoading(true)
    setSuggestionError(null)

    fetch(`/api/gmail-classifier/emails/${email.id}/suggest-reply`, {
      headers: { Authorization: `Bearer ${token}` },
      signal: controller.signal,
    })
      .then(r => r.json())
      .then(data => {
        if (data.eligible && data.body) {
          suggestionCache.current.set(email.id, data.body)
          setReplyText(data.body)
          setDraftSaved(data.from_draft ?? false)
        }
      })
      .catch(err => {
        if (err.name === 'AbortError' && !timedOut) return  // cleanup abort — ignore
        const timeoutSecs = Math.round((suggestionTimeoutMs ?? 60000) / 1000)
        const msg = timedOut
          ? `Tiempo de espera agotado (${timeoutSecs}s)`
          : `Error: ${err?.message || 'desconocido'}`
        console.error('[autoreply] suggest-reply error:', err)
        setSuggestionError(msg)
      })
      .finally(() => {
        setSuggestionLoading(false)
        clearTimeout(timeoutId)
      })

    return () => {
      controller.abort()
      clearTimeout(timeoutId)
    }
  }, [email?.id, autoReplyCategoryIds, token])

  const handleSendReply = async () => {
    if (!replyText.trim()) return;
    setSending(true);
    setReplyError('');
    const ok = await onReply(email!.id, replyText.trim());
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

  if (!email) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center gap-3 text-[var(--acm-fg-4)]">
        <Mail size={32} className="opacity-30" />
        <p className="text-[13px]">Selecciona un correo</p>
      </div>
    );
  }

  const formattedDate = email.received_at
    ? new Date(email.received_at).toLocaleString('es-CO', {
        day: '2-digit', month: 'long', year: 'numeric',
        hour: '2-digit', minute: '2-digit',
      })
    : '';

  // Use HTML renderer if we have stored HTML, OR if body_text looks like HTML/CSS
  const looksLikeHtml = (s: string) =>
    /<!DOCTYPE|<html|<body|<div|<table|<td|<span|<p\s|<br|@media|\.u-row/i.test(s.slice(0, 500));

  const storedHtml = email.body_html || (looksLikeHtml(email.body_text) ? email.body_text : '');
  const htmlToRender = resolvedHtml ?? storedHtml;
  const hasHtml = !!htmlToRender;
  const bodyContent = email.body_text || email.snippet;

  return (
    <div className="flex-1 flex flex-col min-h-0 overflow-hidden">

      {/* ── Header ────────────────────────────────────────── */}
      <div className="px-6 pt-4 pb-3 border-b border-[var(--acm-border)] flex-shrink-0">
        <h2 className="text-[15px] font-semibold text-[var(--acm-fg)] leading-snug mb-3">
          {email.subject}
        </h2>

        <div className="flex items-start justify-between gap-3">
          <div className="text-[12px] space-y-0.5">
            <div className="flex items-center gap-2">
              <span className="text-[var(--acm-fg-4)]">De:</span>
              <span className="text-[var(--acm-fg)] font-medium">
                {email.sender_name || email.sender_email}
              </span>
              {email.sender_name && (
                <span className="text-[var(--acm-fg-4)]">&lt;{email.sender_email}&gt;</span>
              )}
            </div>
            <div className="flex items-center gap-2">
              <span className="text-[var(--acm-fg-4)]">Fecha:</span>
              <span className="text-[var(--acm-fg-3)] mono text-[11px]">{formattedDate}</span>
            </div>
          </div>

          <a
            href={`https://mail.google.com/mail/u/0/#all/${email.gmail_id}`}
            target="_blank"
            rel="noopener noreferrer"
            className="btn-secondary text-[11px] py-[5px] px-2.5 flex-shrink-0"
          >
            <ExternalLink size={12} /> Ver en Gmail
          </a>
        </div>
      </div>

      {/* ── Attachments ───────────────────────────────────── */}
      {attachments.length > 0 && (
        <div className="px-6 py-2.5 border-b border-[var(--acm-border)] flex-shrink-0">
          <div className="flex items-center gap-1.5 mb-1.5">
            <Paperclip size={12} className="text-[var(--acm-fg-4)]" />
            <span className="text-[11px] text-[var(--acm-fg-4)]">
              {attachments.length} adjunto{attachments.length === 1 ? '' : 's'}
            </span>
          </div>
          <div className="flex flex-wrap gap-2">
            {attachments.map(att => {
              const Icon = attachmentIcon(att.mime_type);
              const isDownloading = downloadingId === att.attachment_id;
              return (
                <button
                  key={att.attachment_id}
                  onClick={() => downloadAttachment(att)}
                  disabled={isDownloading}
                  title={`${att.filename} — abrir / descargar`}
                  className="group flex items-center gap-2 max-w-[240px] bg-[var(--acm-card)] border border-[var(--acm-border)] rounded-[var(--acm-radius)] px-2.5 py-1.5 hover:border-[var(--acm-accent)] transition-colors text-left"
                >
                  <Icon size={15} className="text-[var(--acm-accent)] flex-shrink-0" />
                  <span className="flex flex-col min-w-0">
                    <span className="text-[12px] text-[var(--acm-fg-2)] truncate">{att.filename}</span>
                    {att.size > 0 && (
                      <span className="text-[10px] text-[var(--acm-fg-4)]">{formatBytes(att.size)}</span>
                    )}
                  </span>
                  {isDownloading ? (
                    <div className="h-3 w-3 rounded-full border-2 border-[var(--acm-fg-4)] border-t-transparent animate-spin flex-shrink-0" />
                  ) : (
                    <Download size={13} className="text-[var(--acm-fg-4)] group-hover:text-[var(--acm-accent)] flex-shrink-0" />
                  )}
                </button>
              );
            })}
          </div>
        </div>
      )}

      {/* ── Body ──────────────────────────────────────────── */}
      <div className="flex-1 overflow-y-auto acm-scroll min-h-0 px-4 py-4">
        {hasHtml ? (
          <HtmlEmail html={htmlToRender} />
        ) : bodyContent ? (
          <PlainTextBody text={bodyContent} />
        ) : (
          <p className="text-[12px] text-[var(--acm-fg-4)] italic px-2">
            Sin contenido — reprocesa para cargar el cuerpo del correo.
          </p>
        )}
      </div>

      {/* ── Controls bar ──────────────────────────────────── */}
      <div className="px-6 py-2.5 border-t border-[var(--acm-border)] bg-[var(--acm-elev)] flex items-center gap-2 flex-wrap flex-shrink-0">
        {/* Category */}
        <div className="relative">
          <select
            value={email.category_id}
            onChange={e => onRecategorize(email.id, Number(e.target.value))}
            className="bg-[var(--acm-card)] border border-[var(--acm-border)] text-[var(--acm-fg-2)] text-[12px] rounded-[var(--acm-radius)] px-3 py-1.5 pr-7 appearance-none outline-none focus:border-[var(--acm-accent)] transition-colors cursor-pointer"
          >
            {categories.map(c => (
              <option key={c.id} value={c.id}>{c.name}</option>
            ))}
          </select>
          <ChevronDown size={11} className="absolute right-2 top-2 text-[var(--acm-fg-4)] pointer-events-none" />
        </div>

        {/* Read toggle */}
        {email.is_read ? (
          <button onClick={() => onReadToggle(email.id, false)} className="btn-secondary text-[11px] py-[5px] px-2.5">
            <Mail size={12} /> No leído
          </button>
        ) : (
          <button onClick={() => onReadToggle(email.id, true)} className="btn-secondary text-[11px] py-[5px] px-2.5">
            <MailOpen size={12} /> Leído
          </button>
        )}

        {email.is_replied === 1 && (
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

      {/* Auto-reply feedback — visible immediately when email opens */}
      {suggestionLoading && (
        <div className="flex items-center gap-2 text-sm text-gray-500 dark:text-gray-400 px-6 pt-2">
          <div className="h-3 w-3 rounded-full border-2 border-current border-t-transparent animate-spin" />
          Generando respuesta...
        </div>
      )}
      {!suggestionLoading && replyText && autoReplyCategoryIds?.includes(email.category_id) && (
        <div className="px-6 pt-2">
          <span className="text-xs font-medium text-purple-600 dark:text-purple-400">Sugerencia IA ✦</span>
        </div>
      )}
      {suggestionError && (
        <p className="text-xs text-gray-400 dark:text-gray-500 px-6 pt-2">{suggestionError}</p>
      )}

      {/* ── Reply composer (collapsible) ───────────────────── */}
      {replyOpen && (
        <div className="px-6 py-4 border-t border-[var(--acm-border)] flex-shrink-0 bg-[var(--acm-base)]">
          <p className="text-[11px] text-[var(--acm-fg-4)] mb-2">
            <CornerUpLeft size={11} className="inline mr-1" />
            Responder a <span className="text-[var(--acm-fg-3)]">{email.sender_email}</span>
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
              <button
                onClick={async () => {
                  if (!token) return
                  setSavingDraft(true)
                  try {
                    const res = await fetch(`/api/gmail-classifier/emails/${email.id}/draft`, {
                      method: 'POST',
                      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
                      body: JSON.stringify({ body: replyText }),
                    })
                    if (res.ok) {
                      setDraftSaved(true)
                    }
                  } finally {
                    setSavingDraft(false)
                  }
                }}
                disabled={savingDraft || !replyText.trim()}
                className="btn-secondary text-[12px] py-[6px] px-3"
              >
                {savingDraft ? 'Guardando...' : draftSaved ? 'Borrador guardado ✓' : 'Guardar como borrador'}
              </button>
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
