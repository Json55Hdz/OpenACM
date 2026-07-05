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

export interface KnowledgeItem {
  id: number;
  agent_id: number;
  type: 'file' | 'text';
  title: string;
  filename: string | null;
  char_count: number;
  created_at: string;
}

export interface ChannelItem {
  id: number;
  agent_id: number;
  type: 'telegram' | 'whatsapp' | 'whatsapp_web';
  config: Record<string, string>;
  is_active: boolean;
  is_connected: boolean;
  created_at: string;
}

export type ChannelConfig =
  | { type: 'telegram'; token: string }
  | { type: 'whatsapp'; access_token: string; phone_number_id: string; verify_token?: string; app_secret?: string }
  | { type: 'whatsapp_web'; bridge_url: string };

export function useAgentKnowledge(agentId: number | null) {
  const { fetchAPI } = useAPI();
  const isAuthenticated = useIsAuthenticated();

  return useQuery<KnowledgeItem[]>({
    queryKey: ['agent-knowledge', agentId],
    queryFn: () => fetchAPI(`/api/agents/${agentId}/knowledge`),
    enabled: isAuthenticated && agentId !== null,
    staleTime: 0,
  });
}

export function useAgentKnowledgeMutations(agentId: number) {
  const { fetchAPI } = useAPI();
  const qc = useQueryClient();
  const invalidate = () => qc.invalidateQueries({ queryKey: ['agent-knowledge', agentId] });

  const addText = useMutation({
    mutationFn: ({ title, content }: { title: string; content: string }) =>
      fetchAPI(`/api/agents/${agentId}/knowledge/text`, {
        method: 'POST',
        body: JSON.stringify({ title, content }),
      }),
    onSuccess: invalidate,
  });

  const addFile = useMutation({
    mutationFn: ({ file, title }: { file: File; title?: string }) => {
      const token = authStore.getState().token ?? '';
      const form = new FormData();
      form.append('file', file);
      if (title) form.append('title', title);
      return fetch(`/api/agents/${agentId}/knowledge/file`, {
        method: 'POST',
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        body: form,
      }).then(async (r) => {
        if (!r.ok) throw new Error(await r.text());
        return r.json();
      });
    },
    onSuccess: invalidate,
  });

  const updateItem = useMutation({
    mutationFn: ({ kid, title, content }: { kid: number; title?: string; content?: string }) =>
      fetchAPI(`/api/agents/${agentId}/knowledge/${kid}`, {
        method: 'PATCH',
        body: JSON.stringify({ title, content }),
      }),
    onSuccess: invalidate,
  });

  const removeItem = useMutation({
    mutationFn: (kid: number) =>
      fetchAPI(`/api/agents/${agentId}/knowledge/${kid}`, { method: 'DELETE' }),
    onSuccess: invalidate,
  });

  return { addText, addFile, updateItem, removeItem };
}

export function useAgentChannels(agentId: number | null) {
  const { fetchAPI } = useAPI();
  const isAuthenticated = useIsAuthenticated();

  return useQuery<ChannelItem[]>({
    queryKey: ['agent-channels', agentId],
    queryFn: () => fetchAPI(`/api/agents/${agentId}/channels`),
    enabled: isAuthenticated && agentId !== null,
    staleTime: 0,
  });
}

export function useAgentChannelMutations(agentId: number) {
  const { fetchAPI } = useAPI();
  const qc = useQueryClient();
  const invalidate = () => qc.invalidateQueries({ queryKey: ['agent-channels', agentId] });

  const addChannel = useMutation({
    mutationFn: ({ type, config }: { type: string; config: Record<string, string> }) =>
      fetchAPI(`/api/agents/${agentId}/channels`, {
        method: 'POST',
        body: JSON.stringify({ type, config }),
      }),
    onSuccess: invalidate,
  });

  const removeChannel = useMutation({
    mutationFn: (channelId: number) =>
      fetchAPI(`/api/agents/${agentId}/channels/${channelId}`, { method: 'DELETE' }),
    onSuccess: invalidate,
  });

  const restartChannel = useMutation({
    mutationFn: (channelId: number) =>
      fetchAPI(`/api/agents/${agentId}/channels/${channelId}/restart`, { method: 'POST' }),
    onSuccess: invalidate,
  });

  return { addChannel, removeChannel, restartChannel };
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

export interface AgentSkill {
  id: number;
  name: string;
  description: string;
  content: string;
  category: string;
  is_active: number;
  is_builtin: number;
  agent_id: number | null;
  enabled?: boolean; // present only on global_skills entries
}

export function useAgentSkills(agentId: number) {
  const { fetchAPI } = useAPI();
  const isAuthenticated = useIsAuthenticated();

  return useQuery<{ global_skills: AgentSkill[]; private_skills: AgentSkill[] }>({
    queryKey: ['agent-skills', agentId],
    queryFn: () => fetchAPI(`/api/agents/${agentId}/skills`),
    enabled: isAuthenticated,
  });
}

export function useToggleAgentGlobalSkill(agentId: number) {
  const { fetchAPI } = useAPI();
  const qc = useQueryClient();

  return useMutation({
    mutationFn: ({ skillId, enable }: { skillId: number; enable: boolean }) =>
      fetchAPI(`/api/agents/${agentId}/skills/${skillId}`, { method: enable ? 'POST' : 'DELETE' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['agent-skills', agentId] }),
  });
}

export function useGenerateAgentSkill(agentId: number) {
  const { fetchAPI } = useAPI();
  const qc = useQueryClient();

  return useMutation({
    mutationFn: (data: { name: string; description: string; use_cases: string }) =>
      fetchAPI(`/api/agents/${agentId}/skills/generate`, { method: 'POST', body: JSON.stringify(data) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['agent-skills', agentId] }),
  });
}

export function useToggleAgentPrivateSkill(agentId: number) {
  const { fetchAPI } = useAPI();
  const qc = useQueryClient();

  return useMutation({
    mutationFn: (skillId: number) => fetchAPI(`/api/skills/${skillId}/toggle`, { method: 'POST' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['agent-skills', agentId] }),
  });
}

export function useDeleteAgentPrivateSkill(agentId: number) {
  const { fetchAPI } = useAPI();
  const qc = useQueryClient();

  return useMutation({
    mutationFn: (skillId: number) => fetchAPI(`/api/skills/${skillId}`, { method: 'DELETE' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['agent-skills', agentId] }),
  });
}
