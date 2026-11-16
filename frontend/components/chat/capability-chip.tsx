'use client';

import { useQuery } from '@tanstack/react-query';
import { Ear, Eye } from 'lucide-react';
import { useAPI, useIsAuthenticated } from '@/hooks/use-api';

type Cap = { mode: 'native' | 'delegated' | 'none' | 'unknown'; provider: string | null; model: string | null };

const LABEL: Record<string, { name: string; Icon: typeof Eye }> = {
  vision: { name: 'Imágenes', Icon: Eye },
  audio: { name: 'Audio', Icon: Ear },
};

/** Small status line above the chat input: who handles images and audio right now. */
export function CapabilityChips({ model }: { model?: string }) {
  const { fetchAPI } = useAPI();
  const isAuthenticated = useIsAuthenticated();
  const { data } = useQuery<Record<string, Cap>>({
    queryKey: ['llm-capabilities', model],
    queryFn: () => fetchAPI('/api/llm/capabilities'),
    enabled: isAuthenticated,
    refetchInterval: 20_000,
  });
  if (!data) return null;

  return (
    <div className="flex flex-wrap gap-x-3 gap-y-1 mb-2 px-1" aria-label="Capacidades del modelo">
      {Object.entries(LABEL).map(([key, { name, Icon }]) => {
        const c = data[key];
        if (!c) return null;
        const text =
          c.mode === 'native' ? 'lo hace el modelo'
          : c.mode === 'delegated' ? `lo hace ${c.model}`
          : c.mode === 'unknown' ? 'midiendo…'
          : 'ningún modelo puede';
        const color =
          c.mode === 'native' ? 'var(--acm-ok)'
          : c.mode === 'delegated' ? 'var(--acm-accent)'
          : c.mode === 'none' ? 'var(--acm-err)'
          : 'var(--acm-fg-4)';
        const hint =
          c.mode === 'none'
            ? `${name}: ningún modelo configurado lo admite. Conecta uno que sí (Config → Modelos) o los ${name.toLowerCase()} se ignorarán.`
            : c.mode === 'delegated'
              ? `${name}: el modelo del chat no lo admite, así que lo procesa ${c.provider}/${c.model} y le pasa el resultado.`
              : `${name}: ${text}`;
        return (
          <span key={key} title={hint} className="mono inline-flex items-center gap-1" style={{ fontSize: 10.5, color }}>
            <Icon size={11} /> {name}: {text}
          </span>
        );
      })}
    </div>
  );
}
