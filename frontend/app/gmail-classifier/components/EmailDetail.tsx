'use client';

import { useState } from 'react';
import { Mail, MailOpen, ChevronDown, CornerUpLeft, ExternalLink, ChevronUp } from 'lucide-react';

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
}

// Inject base styles into HTML emails so they render cleanly in the iframe
const HTML_BASE_STYLES = `
  <style>
    * { box-sizing: border-box; }
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
    img { max-width: 100%; height: auto; }
    a { color: #2563eb; }
    p { margin: 0 0 10px; }
    pre, code { font-size: 12px; overflow-x: auto; }
    table { max-width: 100%; border-collapse: collapse; }
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

export function EmailDetail({ email, categories, onReadToggle, onRecategorize, onReply }: EmailDetailProps) {
  const [replyOpen, setReplyOpen] = useState(false);
  const [replyText, setReplyText] = useState('');
  const [sending, setSending] = useState(false);
  const [replySuccess, setReplySuccess] = useState(false);
  const [replyError, setReplyError] = useState('');

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

  const htmlToRender = email.body_html || (looksLikeHtml(email.body_text) ? email.body_text : '');
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
