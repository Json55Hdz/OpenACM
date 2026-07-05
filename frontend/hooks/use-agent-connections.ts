'use client';

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useAPI, useIsAuthenticated } from '@/hooks/use-api';

export interface AgentConnection {
  id: number;
  agent_id: number;
  name: string;
  type: string;
  created_at: string;
}

export function useAgentConnections(agentId: number) {
  const { fetchAPI } = useAPI();
  const isAuthenticated = useIsAuthenticated();

  return useQuery<AgentConnection[]>({
    queryKey: ['agent-connections', agentId],
    queryFn: () => fetchAPI(`/api/agents/${agentId}/connections`),
    enabled: isAuthenticated,
  });
}

export function useCreateConnection(agentId: number) {
  const { fetchAPI } = useAPI();
  const qc = useQueryClient();

  return useMutation({
    mutationFn: (data: { name: string; type: string; url: string; consumer_key: string; consumer_secret: string }) =>
      fetchAPI(`/api/agents/${agentId}/connections`, { method: 'POST', body: JSON.stringify(data) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['agent-connections', agentId] }),
  });
}

export function useDeleteConnection(agentId: number) {
  const { fetchAPI } = useAPI();
  const qc = useQueryClient();

  return useMutation({
    mutationFn: (id: number) => fetchAPI(`/api/agents/${agentId}/connections/${id}`, { method: 'DELETE' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['agent-connections', agentId] }),
  });
}
