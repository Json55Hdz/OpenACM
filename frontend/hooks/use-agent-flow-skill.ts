'use client';

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useAPI, useIsAuthenticated } from '@/hooks/use-api';

export interface FlowSkill {
  id: number;
  flow_id: number;
  name: string;
  description: string;
  content: string;
}

export function useAgentFlowSkill(agentId: number, flowId: number) {
  const { fetchAPI } = useAPI();
  const isAuthenticated = useIsAuthenticated();

  return useQuery<FlowSkill | null>({
    queryKey: ['agent-flow-skill', flowId],
    queryFn: () => fetchAPI(`/api/agents/${agentId}/flows/${flowId}/skill`),
    enabled: isAuthenticated,
  });
}

export function useSaveFlowSkill(agentId: number, flowId: number) {
  const { fetchAPI } = useAPI();
  const qc = useQueryClient();

  return useMutation({
    mutationFn: ({ exists, data }: { exists: boolean; data: { name: string; description?: string; content: string } }) =>
      fetchAPI(`/api/agents/${agentId}/flows/${flowId}/skill`, {
        method: exists ? 'PUT' : 'POST',
        body: JSON.stringify(data),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['agent-flow-skill', flowId] }),
  });
}

export function useGenerateFlowSkill(agentId: number, flowId: number) {
  const { fetchAPI } = useAPI();
  const qc = useQueryClient();

  return useMutation({
    mutationFn: (data: { name: string; description?: string }) =>
      fetchAPI(`/api/agents/${agentId}/flows/${flowId}/skill/generate`, {
        method: 'POST',
        body: JSON.stringify(data),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['agent-flow-skill', flowId] }),
  });
}
