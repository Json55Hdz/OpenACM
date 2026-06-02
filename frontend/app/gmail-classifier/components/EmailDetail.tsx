"use client";

import { useState } from "react";
import { Mail, MailOpen, ChevronDown } from "lucide-react";

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
  const [replyText, setReplyText] = useState("");
  const [sending, setSending] = useState(false);
  const [replySuccess, setReplySuccess] = useState(false);

  if (!email) {
    return (
      <div className="flex-1 flex items-center justify-center text-gray-400 text-sm">
        Selecciona un correo para ver el detalle
      </div>
    );
  }

  const handleSendReply = async () => {
    if (!replyText.trim()) return;
    setSending(true);
    const ok = await onReply(email.id, replyText.trim());
    setSending(false);
    if (ok) {
      setReplyText("");
      setReplySuccess(true);
      setTimeout(() => setReplySuccess(false), 3000);
    }
  };

  const formattedDate = email.received_at
    ? new Date(email.received_at).toLocaleString("es-CO", {
        day: "2-digit", month: "long", year: "numeric",
        hour: "2-digit", minute: "2-digit",
      })
    : "";

  return (
    <div className="flex-1 flex flex-col min-h-0 overflow-hidden">
      {/* Header */}
      <div className="px-6 py-4 border-b bg-white flex-shrink-0">
        <h2 className="font-semibold text-gray-900 text-lg leading-tight">{email.subject}</h2>
        <div className="flex items-center gap-2 mt-2 text-sm text-gray-500 flex-wrap">
          <span>
            De: <span className="text-gray-700 font-medium">{email.sender_name || email.sender_email}</span>
          </span>
          <span className="text-gray-400">&lt;{email.sender_email}&gt;</span>
          <span className="ml-auto text-xs">{formattedDate}</span>
        </div>
      </div>

      {/* Body / snippet */}
      <div className="flex-1 overflow-y-auto px-6 py-4">
        <p className="text-gray-700 text-sm leading-relaxed whitespace-pre-wrap">{email.snippet}</p>
        <p className="text-xs text-gray-400 mt-4 italic">
          (Vista previa del correo — abre Gmail para ver el mensaje completo)
        </p>
      </div>

      {/* Controls */}
      <div className="px-6 py-3 border-t bg-gray-50 flex items-center gap-3 flex-wrap flex-shrink-0">
        {/* Category selector */}
        <div className="relative">
          <select
            value={email.category_id}
            onChange={e => onRecategorize(email.id, Number(e.target.value))}
            className="text-sm border rounded px-3 py-1.5 pr-7 text-gray-700 bg-white appearance-none cursor-pointer"
          >
            {categories.map(c => (
              <option key={c.id} value={c.id}>{c.name}</option>
            ))}
          </select>
          <ChevronDown size={12} className="absolute right-2 top-2.5 text-gray-400 pointer-events-none" />
        </div>

        {/* Read toggle */}
        {email.is_read ? (
          <button
            onClick={() => onReadToggle(email.id, false)}
            className="flex items-center gap-1.5 text-sm text-gray-600 hover:text-blue-600 px-2 py-1.5 rounded hover:bg-blue-50 transition-colors"
          >
            <Mail size={14} /> Marcar no leído
          </button>
        ) : (
          <button
            onClick={() => onReadToggle(email.id, true)}
            className="flex items-center gap-1.5 text-sm text-gray-600 hover:text-green-600 px-2 py-1.5 rounded hover:bg-green-50 transition-colors"
          >
            <MailOpen size={14} /> Marcar leído
          </button>
        )}

        {email.is_replied === 1 && (
          <span className="text-xs text-green-600 bg-green-50 px-2 py-1 rounded border border-green-200">
            ↩ Respondido
          </span>
        )}
      </div>

      {/* Reply composer */}
      <div className="px-6 py-4 border-t bg-white flex-shrink-0">
        <p className="text-xs text-gray-500 mb-2">
          Responder a: <span className="font-medium">{email.sender_email}</span>
        </p>
        <textarea
          value={replyText}
          onChange={e => setReplyText(e.target.value)}
          placeholder="Escribe tu respuesta..."
          rows={4}
          className="w-full border rounded px-3 py-2 text-sm text-gray-700 resize-none focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
        <div className="flex items-center justify-between mt-2">
          {replySuccess ? (
            <span className="text-sm text-green-600 font-medium">✓ Respuesta enviada</span>
          ) : (
            <span />
          )}
          <button
            onClick={handleSendReply}
            disabled={sending || !replyText.trim()}
            className="bg-blue-600 text-white text-sm px-4 py-2 rounded hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {sending ? "Enviando..." : "Enviar respuesta"}
          </button>
        </div>
      </div>
    </div>
  );
}
