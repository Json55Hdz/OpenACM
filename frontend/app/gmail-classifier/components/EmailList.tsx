"use client";

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

interface EmailListProps {
  emails: Email[];
  selectedId: number | null;
  onSelect: (email: Email) => void;
}

function timeAgo(dateStr: string): string {
  if (!dateStr) return "";
  try {
    const diff = Date.now() - new Date(dateStr).getTime();
    const mins = Math.floor(diff / 60000);
    if (mins < 60) return `hace ${mins}m`;
    const hrs = Math.floor(mins / 60);
    if (hrs < 24) return `hace ${hrs}h`;
    const days = Math.floor(hrs / 24);
    if (days < 7) return `hace ${days}d`;
    return new Date(dateStr).toLocaleDateString("es-CO", { day: "2-digit", month: "short" });
  } catch {
    return "";
  }
}

export function EmailList({ emails, selectedId, onSelect }: EmailListProps) {
  if (emails.length === 0) {
    return (
      <div className="w-80 flex-shrink-0 border-r flex items-center justify-center text-gray-400 text-sm">
        No hay correos
      </div>
    );
  }

  return (
    <div className="w-80 flex-shrink-0 border-r overflow-y-auto">
      {emails.map(email => (
        <button
          key={email.id}
          onClick={() => onSelect(email)}
          className={`w-full text-left px-4 py-3 border-b hover:bg-gray-50 transition-colors ${
            selectedId === email.id ? "bg-blue-50 border-l-2 border-l-blue-500" : ""
          }`}
        >
          <div className="flex items-start gap-2">
            {/* Unread dot */}
            <div className={`w-2 h-2 rounded-full flex-shrink-0 mt-1.5 ${email.is_read ? "opacity-0" : "bg-blue-500"}`} />
            <div className="min-w-0 flex-1">
              <div className="flex items-center justify-between gap-1">
                <p className={`text-sm truncate ${email.is_read ? "text-gray-600" : "text-gray-900 font-semibold"}`}>
                  {email.sender_name || email.sender_email}
                </p>
                <span className="text-xs text-gray-400 flex-shrink-0">{timeAgo(email.received_at)}</span>
              </div>
              <p className={`text-sm truncate ${email.is_read ? "text-gray-500" : "text-gray-800 font-medium"}`}>
                {email.subject}
              </p>
              <p className="text-xs text-gray-400 truncate mt-0.5">{email.snippet}</p>
              <div className="flex items-center gap-2 mt-1">
                <span
                  className="text-xs px-2 py-0.5 rounded-full"
                  style={{ backgroundColor: `${email.category_color}22`, color: email.category_color }}
                >
                  {email.category_name}
                </span>
                {email.is_replied === 1 && (
                  <span className="text-xs text-green-600">↩ Respondido</span>
                )}
              </div>
            </div>
          </div>
        </button>
      ))}
    </div>
  );
}
