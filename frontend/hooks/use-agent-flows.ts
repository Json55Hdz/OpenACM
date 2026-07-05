'use client';

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useAPI, useIsAuthenticated } from '@/hooks/use-api';

export interface AgentFlow {
  id: number;
  agent_id: number;
  name: string;
  description: string;
  graph_json: string;
  is_active: number;
  created_at: string;
  updated_at: string;
}

export function useAgentFlows(agentId: number) {
  const { fetchAPI } = useAPI();
  const isAuthenticated = useIsAuthenticated();

  return useQuery<AgentFlow[]>({
    queryKey: ['agent-flows', agentId],
    queryFn: () => fetchAPI(`/api/agents/${agentId}/flows`),
    enabled: isAuthenticated,
  });
}

export function useAgentFlow(agentId: number, flowId: number | null) {
  const { fetchAPI } = useAPI();
  const isAuthenticated = useIsAuthenticated();

  return useQuery<AgentFlow>({
    queryKey: ['agent-flow', flowId],
    queryFn: () => fetchAPI(`/api/agents/${agentId}/flows/${flowId}`),
    enabled: isAuthenticated && flowId !== null,
  });
}

export function useCreateFlow(agentId: number) {
  const { fetchAPI } = useAPI();
  const qc = useQueryClient();

  return useMutation({
    mutationFn: (data: { name: string; description?: string }) =>
      fetchAPI(`/api/agents/${agentId}/flows`, { method: 'POST', body: JSON.stringify(data) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['agent-flows', agentId] }),
  });
}

export function useUpdateFlow(agentId: number) {
  const { fetchAPI } = useAPI();
  const qc = useQueryClient();

  return useMutation({
    mutationFn: ({ id, data }: { id: number; data: Partial<Pick<AgentFlow, 'name' | 'description' | 'graph_json' | 'is_active'>> }) =>
      fetchAPI(`/api/agents/${agentId}/flows/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: ['agent-flows', agentId] });
      qc.invalidateQueries({ queryKey: ['agent-flow', vars.id] });
    },
  });
}

export function useDeleteFlow(agentId: number) {
  const { fetchAPI } = useAPI();
  const qc = useQueryClient();

  return useMutation({
    mutationFn: (id: number) => fetchAPI(`/api/agents/${agentId}/flows/${id}`, { method: 'DELETE' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['agent-flows', agentId] }),
  });
}
