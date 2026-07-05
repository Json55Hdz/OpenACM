'use client';

import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useAPI } from './use-api';

export function useUpdateWorkerTools(swarmId: number, workerId: number) {
  const { fetchAPI } = useAPI();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (allowedTools: string) =>
      fetchAPI(`/api/swarms/${swarmId}/workers/${workerId}`, {
        method: 'PUT',
        body: JSON.stringify({ allowed_tools: allowedTools }),
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['swarm', swarmId] }),
  });
}

/** allowed_tools is stored as "all" | "none" | a JSON array string of tool names. */
export function parseAllowedTools(allowedTools: string, allToolNames: string[]): Set<string> {
  if (allowedTools === 'all') return new Set(allToolNames);
  if (allowedTools === 'none') return new Set();
  try {
    const parsed = JSON.parse(allowedTools);
    return new Set(Array.isArray(parsed) ? parsed : []);
  } catch {
    return new Set();
  }
}

/** Inverse of parseAllowedTools — collapses back to "all"/"none" when applicable. */
export function serializeAllowedTools(selected: Set<string>, allToolNames: string[]): string {
  if (selected.size === 0) return 'none';
  if (selected.size === allToolNames.length) return 'all';
  return JSON.stringify(Array.from(selected));
}
