'use client';

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useAPI, useIsAuthenticated } from '@/hooks/use-api';
import { authStore } from '@/stores/auth-store';

export interface Agent {
  id: number;
  name: string;
  description: string;
  system_prompt: string;
  allowed_tools: string;
  is_active: boolean;
  telegram_token: string;
  created_at: string;
  updated_at: string;
  // only returned on create
  webhook_secret?: string;
}

export interface AgentFormData {
  name: string;
  description: string;
  system_prompt: string;
  allowed_tools: string;
  telegram_token: string;
}

export function useAgents() {
  const { fetchAPI } = useAPI();
  const isAuthenticated = useIsAuthenticated();

  return useQuery<Agent[]>({
    queryKey: ['agents'],
    queryFn: () => fetchAPI('/api/agents'),
    enabled: isAuthenticated,
    staleTime: 0,
    refetchOnMount: 'always',
  });
}

export function useAgentMutations() {
  const { fetchAPI } = useAPI();
  const qc = useQueryClient();

  const create = useMutation({
    mutationFn: (data: AgentFormData) =>
      fetchAPI('/api/agents', { method: 'POST', body: JSON.stringify(data) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['agents'] }),
  });

  const update = useMutation({
    mutationFn: ({ id, data }: { id: number; data: Partial<AgentFormData & { is_active: boolean }> }) =>
      fetchAPI(`/api/agents/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['agents'] }),
  });

  const remove = useMutation({
    mutationFn: (id: number) => fetchAPI(`/api/agents/${id}`, { method: 'DELETE' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['agents'] }),
  });

  const test = useMutation({
    mutationFn: ({ id, message }: { id: number; message: string }) =>
      fetchAPI(`/api/agents/${id}/test`, { method: 'POST', body: JSON.stringify({ message }) }),
  });

  const getSecret = useMutation({
    mutationFn: (id: number) => fetchAPI(`/api/agents/${id}/secret`),
  });

  const generate = useMutation({
    mutationFn: ({ description, files }: { description: string; files?: File[] }) => {
      const token = authStore.getState().token ?? '';
      const form = new FormData();
      form.append('description', description);
      if (files) {
        for (const f of files) form.append('file', f);
      }
      return fetch('/api/agents/generate', {
        method: 'POST',
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        body: form,
      }).then(async (r) => {
        if (!r.ok) throw new Error(await r.text());
        return r.json();
      });
    },
  });

  return { create, update, remove, test, getSecret, generate };
}
