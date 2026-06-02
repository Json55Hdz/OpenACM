'use client';

import { useState } from 'react';
import { Mail, MailOpen, ChevronDown, CornerUpLeft } from 'lucide-react';

interface Email {
  id: number;
  subject: string;
  sender_name: string;
  sender_email: string;
  snippet: string;
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

export function EmailDetail({ email, categories, onReadToggle, onRecategorize, onReply }: EmailDetailProps) {
  const [replyText, setReplyText] = useState('');
  const [sending, setSending] = useState(false);
  const [replySuccess, setReplySuccess] = useState(false);
  const [replyError, setReplyError] = useState('');

  if (!email) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center gap-3 text-[var(--acm-fg-4)]">
        <Mail size={32} className="opacity-30" />
        <p className="text-[13px]">Selecciona un correo</p>
      </div>
    );
  }

  const handleSendReply = async () => {
    if (!replyText.trim()) return;
    setSending(true);
    setReplyError('');
    const ok = await onReply(email.id, replyText.trim());
    setSending(false);
    if (ok) {
      setReplyText('');
      setReplySuccess(true);
      setTimeout(() => setReplySuccess(false), 3000);
    } else {
      setReplyError('Error al enviar. Verifica la conexión con Gmail.');
    }
  };

  const formattedDate = email.received_at
    ? new Date(email.received_at).toLocaleString('es-CO', {
        day: '2-digit', month: 'long', year: 'numeric',
        hour: '2-digit', minute: '2-digit',
      })
    : '';

  return (
    <div className="flex-1 flex flex-col min-h-0 overflow-hidden">
      {/* Header */}
      <div className="px-6 py-4 border-b border-[var(--acm-border)] flex-shrink-0">
        <h2 className="text-[15px] font-semibold text-[var(--acm-fg)] leading-snug mb-2">
          {email.subject}
        </h2>
        <div className="flex items-center gap-3 text-[12px] text-[var(--acm-fg-3)] flex-wrap">
          <span>
            De:{' '}
            <span className="text-[var(--acm-fg-2)] font-medium">
              {email.sender_name || email.sender_email}
            </span>
          </span>
          <span className="text-[var(--acm-fg-4)]">&lt;{email.sender_email}&gt;</span>
          <span className="ml-auto mono text-[11px] text-[var(--acm-fg-4)]">{formattedDate}</span>
        </div>
      </div>

      {/* Body */}
      <div className="flex-1 overflow-y-auto acm-scroll px-6 py-4">
        <p className="text-[13px] text-[var(--acm-fg-2)] leading-relaxed whitespace-pre-wrap">
          {email.snippet}
        </p>
        <p className="text-[11px] text-[var(--acm-fg-4)] mt-4 italic">
          Vista previa — abre Gmail para ver el mensaje completo
        </p>
      </div>

      {/* Controls bar */}
      <div className="px-6 py-3 border-t border-[var(--acm-border)] bg-[var(--acm-elev)] flex items-center gap-2 flex-wrap flex-shrink-0">
        {/* Category dropdown */}
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
          <button
            onClick={() => onReadToggle(email.id, false)}
            className="btn-secondary text-[11px] py-[5px] px-2.5"
          >
            <Mail size={12} /> No leído
          </button>
        ) : (
          <button
            onClick={() => onReadToggle(email.id, true)}
            className="btn-secondary text-[11px] py-[5px] px-2.5"
          >
            <MailOpen size={12} /> Leído
          </button>
        )}

        {email.is_replied === 1 && (
          <span className="text-[11px] text-[var(--acm-ok)] flex items-center gap-1">
            <span className="dot dot-ok" />
            Respondido
          </span>
        )}
      </div>

      {/* Reply composer */}
      <div className="px-6 py-4 border-t border-[var(--acm-border)] flex-shrink-0">
        <div className="flex items-center gap-2 mb-2">
          <CornerUpLeft size={12} className="text-[var(--acm-fg-4)]" />
          <p className="text-[11px] text-[var(--acm-fg-4)]">
            Responder a <span className="text-[var(--acm-fg-3)]">{email.sender_email}</span>
          </p>
        </div>
        <textarea
          value={replyText}
          onChange={e => setReplyText(e.target.value)}
          placeholder="Escribe tu respuesta…"
          rows={4}
          className="w-full bg-[var(--acm-elev)] border border-[var(--acm-border)] text-[var(--acm-fg)] text-[13px] rounded-[var(--acm-radius)] px-3 py-2 resize-none outline-none focus:border-[var(--acm-accent)] transition-colors placeholder:text-[var(--acm-fg-4)]"
        />
        <div className="flex items-center justify-between mt-2">
          <div>
            {replySuccess && (
              <span className="text-[12px] text-[var(--acm-ok)]">✓ Respuesta enviada</span>
            )}
            {replyError && (
              <span className="text-[12px] text-[var(--acm-err)]">{replyError}</span>
            )}
          </div>
          <button
            onClick={handleSendReply}
            disabled={sending || !replyText.trim()}
            className="btn-primary text-[12px] py-[7px] px-3"
          >
            {sending ? 'Enviando…' : 'Enviar'}
          </button>
        </div>
      </div>
    </div>
  );
}
