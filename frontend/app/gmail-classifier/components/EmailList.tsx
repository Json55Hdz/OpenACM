'use client';

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

interface EmailListProps {
  emails: Email[];
  selectedId: number | null;
  onSelect: (email: Email) => void;
}

function timeAgo(dateStr: string): string {
  if (!dateStr) return '';
  try {
    const diff = Date.now() - new Date(dateStr).getTime();
    const mins = Math.floor(diff / 60000);
    if (mins < 60) return `${mins}m`;
    const hrs = Math.floor(mins / 60);
    if (hrs < 24) return `${hrs}h`;
    const days = Math.floor(hrs / 24);
    if (days < 7) return `${days}d`;
    return new Date(dateStr).toLocaleDateString('es-CO', { day: '2-digit', month: 'short' });
  } catch {
    return '';
  }
}

export function EmailList({ emails, selectedId, onSelect }: EmailListProps) {
  if (emails.length === 0) {
    return (
      <div className="w-72 flex-shrink-0 border-r border-[var(--acm-border)] flex items-center justify-center text-[var(--acm-fg-4)] text-[12px]">
        Sin correos
      </div>
    );
  }

  return (
    <div className="w-72 flex-shrink-0 border-r border-[var(--acm-border)] overflow-y-auto acm-scroll">
      {emails.map(email => {
        const unread = !email.is_read;
        const isSelected = selectedId === email.id;
        return (
          <button
            key={email.id}
            onClick={() => onSelect(email)}
            className={`w-full text-left px-4 py-3 border-b border-[var(--acm-border)] transition-colors ${
              isSelected
                ? 'bg-[var(--acm-accent-tint)] border-l-2 border-l-[var(--acm-accent)]'
                : 'hover:bg-[var(--acm-elev)]'
            }`}
          >
            <div className="flex items-start gap-2">
              {/* Unread dot */}
              <div className={`w-1.5 h-1.5 rounded-full flex-shrink-0 mt-1.5 dot ${unread ? 'dot-accent' : 'bg-transparent'}`} />
              <div className="min-w-0 flex-1">
                <div className="flex items-center justify-between gap-1 mb-0.5">
                  <p className={`text-[12px] truncate ${unread ? 'text-[var(--acm-fg)] font-semibold' : 'text-[var(--acm-fg-2)]'}`}>
                    {email.sender_name || email.sender_email}
                  </p>
                  <span className="text-[10px] text-[var(--acm-fg-4)] flex-shrink-0 mono">
                    {timeAgo(email.received_at)}
                  </span>
                </div>
                <p className={`text-[12px] truncate mb-0.5 ${unread ? 'text-[var(--acm-fg-2)] font-medium' : 'text-[var(--acm-fg-3)]'}`}>
                  {email.subject}
                </p>
                <p className="text-[11px] text-[var(--acm-fg-4)] truncate">{email.snippet}</p>
                <div className="flex items-center gap-2 mt-1.5">
                  <span
                    className="text-[10px] px-1.5 py-0.5 rounded-full"
                    style={{ background: `${email.category_color}22`, color: email.category_color }}
                  >
                    {email.category_name}
                  </span>
                  {email.is_replied === 1 && (
                    <span className="text-[10px] text-[var(--acm-ok)]">↩ respondido</span>
                  )}
                </div>
              </div>
            </div>
          </button>
        );
      })}
    </div>
  );
}
