'use client';
import type { StatsData } from '../page';

export function KpiCards({ stats }: { stats: StatsData }) {
  const cards = [
    { label: 'Total emails', value: stats.period.total_emails },
    { label: 'No leídos', value: stats.read_status.unread },
    { label: 'Tasa de lectura', value: `${(stats.read_status.rate * 100).toFixed(1)}%` },
    { label: 'Tasa de respuesta', value: `${(stats.reply_rate.rate * 100).toFixed(1)}%` },
    { label: 'Sugerencias IA', value: stats.autoreply.suggestions_generated },
    { label: 'Borradores', value: stats.autoreply.drafts_saved },
  ];
  return (
    <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
      {cards.map(c => (
        <div key={c.label} className="bg-[var(--acm-elev)] border border-[var(--acm-border)] rounded-[var(--acm-radius)] p-4 text-center">
          <div className="text-2xl font-bold text-[var(--acm-fg)]">{c.value}</div>
          <div className="text-xs text-[var(--acm-fg-3)] mt-1">{c.label}</div>
        </div>
      ))}
    </div>
  );
}
