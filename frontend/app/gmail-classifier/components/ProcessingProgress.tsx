'use client';

interface ProcessingProgressProps {
  processed: number;
  total: number;
  running: boolean;
}

export function ProcessingProgress({ processed, total, running }: ProcessingProgressProps) {
  if (!running && total === 0) return null;

  const pct = total > 0 ? Math.round((processed / total) * 100) : 0;

  return (
    <div className="flex items-center gap-3">
      <div className="flex-1">
        <div className="flex justify-between text-[11px] text-[var(--acm-fg-3)] mb-1">
          <span className="text-[var(--acm-fg-2)]">
            {running ? 'Clasificando correos…' : 'Clasificación completada'}
          </span>
          <span className="mono">{processed} / {total}</span>
        </div>
        <div className="w-full bg-[var(--acm-elev)] rounded-full h-1">
          <div
            className="h-1 rounded-full transition-all duration-300"
            style={{ width: `${pct}%`, background: 'var(--acm-accent)' }}
          />
        </div>
      </div>
      {!running && (
        <span className="text-[11px] text-[var(--acm-ok)] font-medium flex-shrink-0">✓ Listo</span>
      )}
    </div>
  );
}
