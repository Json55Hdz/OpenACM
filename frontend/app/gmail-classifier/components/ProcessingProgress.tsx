"use client";

interface ProcessingProgressProps {
  processed: number;
  total: number;
  running: boolean;
}

export function ProcessingProgress({ processed, total, running }: ProcessingProgressProps) {
  if (!running && total === 0) return null;

  const pct = total > 0 ? Math.round((processed / total) * 100) : 0;

  return (
    <div className="bg-blue-50 border border-blue-200 rounded-lg px-4 py-2 flex items-center gap-3">
      <div className="flex-1">
        <div className="flex justify-between text-xs text-blue-700 mb-1">
          <span>{running ? "Clasificando correos..." : "Clasificación completada"}</span>
          <span>{processed} / {total} correos</span>
        </div>
        <div className="w-full bg-blue-200 rounded-full h-1.5">
          <div
            className="bg-blue-600 h-1.5 rounded-full transition-all duration-300"
            style={{ width: `${pct}%` }}
          />
        </div>
      </div>
      {!running && (
        <span className="text-green-600 text-sm font-medium">✓ Listo</span>
      )}
    </div>
  );
}
