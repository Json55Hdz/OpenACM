'use client';

import { useMutation, useQueryClient, useQuery } from '@tanstack/react-query';
import { useAPI, useIsAuthenticated } from './use-api';

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

export interface WorkerSkill {
  id: number;
  name: string;
  description: string;
  content: string;
  category: string;
  is_active: number;
  is_builtin: number;
  worker_id: number | null;
  enabled?: boolean; // present only on global_skills entries
}

export function useWorkerSkills(swarmId: number, workerId: number) {
  const { fetchAPI } = useAPI();
  const isAuthenticated = useIsAuthenticated();

  return useQuery<{ global_skills: WorkerSkill[]; private_skills: WorkerSkill[] }>({
    queryKey: ['worker-skills', swarmId, workerId],
    queryFn: () => fetchAPI(`/api/swarms/${swarmId}/workers/${workerId}/skills`),
    enabled: isAuthenticated,
  });
}

export function useToggleWorkerGlobalSkill(swarmId: number, workerId: number) {
  const { fetchAPI } = useAPI();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ skillId, enable }: { skillId: number; enable: boolean }) =>
      fetchAPI(`/api/swarms/${swarmId}/workers/${workerId}/skills/${skillId}`, {
        method: enable ? 'POST' : 'DELETE',
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['worker-skills', swarmId, workerId] }),
  });
}

export function useGenerateWorkerSkill(swarmId: number, workerId: number) {
  const { fetchAPI } = useAPI();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: { name: string; description: string; use_cases: string }) =>
      fetchAPI(`/api/swarms/${swarmId}/workers/${workerId}/skills/generate`, {
        method: 'POST',
        body: JSON.stringify(data),
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['worker-skills', swarmId, workerId] }),
  });
}

export function useToggleWorkerPrivateSkill(swarmId: number, workerId: number) {
  const { fetchAPI } = useAPI();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (skillId: number) => fetchAPI(`/api/skills/${skillId}/toggle`, { method: 'POST' }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['worker-skills', swarmId, workerId] }),
  });
}

export function useDeleteWorkerPrivateSkill(swarmId: number, workerId: number) {
  const { fetchAPI } = useAPI();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (skillId: number) => fetchAPI(`/api/skills/${skillId}`, { method: 'DELETE' }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['worker-skills', swarmId, workerId] }),
  });
}
