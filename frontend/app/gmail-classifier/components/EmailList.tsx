'use client';

export interface Thread {
  thread_id: string;
  subject: string;
  category_id: number;
  category_name: string;
  category_color: string;
  category_icon: string;
  message_count: number;
  unread_count: number;
  latest_at: string;
  latest_snippet: string;
  latest_sender_email: string;
  latest_sender_name: string;
  participants: { name: string; email: string }[];
}

interface ThreadListProps {
  threads: Thread[];
  selectedId: string | null;
  onSelect: (thread: Thread) => void;
  authEmail?: string;
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

export function EmailList({ threads, selectedId, onSelect, authEmail }: ThreadListProps) {
  if (threads.length === 0) {
    return (
      <div className="flex-1 flex items-center justify-center text-[var(--acm-fg-4)] text-[12px]">
        Sin correos
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-y-auto acm-scroll">
      {threads.map(thread => {
        const unread = thread.unread_count > 0;
        const isSelected = selectedId === thread.thread_id;
        const isReplied = !!(authEmail && thread.latest_sender_email &&
          thread.latest_sender_email.toLowerCase() === authEmail.toLowerCase());

        const names = thread.participants
          .map(p => p.name || p.email.split('@')[0])
          .filter(Boolean);
        const displayNames = names.length === 0
          ? (thread.latest_sender_name || thread.latest_sender_email || '—')
          : names.length <= 2
            ? names.join(', ')
            : `${names.slice(0, 2).join(', ')} +${names.length - 2}`;

        return (
          <button
            key={thread.thread_id}
            onClick={() => onSelect(thread)}
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
                    {displayNames}
                  </p>
                  <div className="flex items-center gap-1.5 flex-shrink-0">
                    {thread.message_count > 1 && (
                      <span className="text-[10px] text-[var(--acm-fg-4)] mono bg-[var(--acm-elev)] px-1 py-0.5 rounded">
                        {thread.message_count}
                      </span>
                    )}
                    <span className="text-[10px] text-[var(--acm-fg-4)] mono">
                      {timeAgo(thread.latest_at)}
                    </span>
                  </div>
                </div>
                <p className={`text-[12px] truncate mb-0.5 ${unread ? 'text-[var(--acm-fg-2)] font-medium' : 'text-[var(--acm-fg-3)]'}`}>
                  {thread.subject}
                </p>
                <p className="text-[11px] text-[var(--acm-fg-4)] truncate">{thread.latest_snippet}</p>
                <div className="flex items-center gap-2 mt-1.5">
                  <span
                    className="text-[10px] px-1.5 py-0.5 rounded-full"
                    style={{ background: `${thread.category_color}22`, color: thread.category_color }}
                  >
                    {thread.category_name}
                  </span>
                  {isReplied && (
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
