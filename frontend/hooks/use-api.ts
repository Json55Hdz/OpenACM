'use client';

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { authStore, useAuthStore } from '@/stores/auth-store';
import { toast } from 'sonner';

interface FetchOptions extends RequestInit {
  requiresAuth?: boolean;
}

export function useAPI() {
  const fetchAPI = async (url: string, options: FetchOptions = {}) => {
    const { requiresAuth = true, ...fetchOptions } = options;
    
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      ...((fetchOptions.headers as Record<string, string>) || {}),
    };
    
    // Get fresh token from store on each call
    if (requiresAuth) {
      const token = authStore.getState().token;
      if (token) {
        headers['Authorization'] = `Bearer ${token}`;
      }
    }
    
    try {
      const response = await fetch(url, {
        ...fetchOptions,
        headers,
      });
      
      if (!response.ok) {
        if (response.status === 401) {
          // Don't clear auth here to avoid loops - let the component handle it
          console.error('401 Unauthorized - token invalid');
        }
        throw new Error(`HTTP ${response.status}`);
      }
      
      return await response.json();
    } catch (error) {
      console.error(`API error (${url}):`, error);
      throw error;
    }
  };
  
  return { fetchAPI };
}

// Hook to check if user is authenticated
export function useIsAuthenticated() {
  return useAuthStore((state) => state.isAuthenticated);
}

export function useStats() {
  const { fetchAPI } = useAPI();
  const isAuthenticated = useIsAuthenticated();
  
  return useQuery({
    queryKey: ['stats'],
    queryFn: async () => {
      const data = await fetchAPI('/api/stats');
      return data;
    },
    enabled: isAuthenticated,
    refetchInterval: 15000,
  });
}

export function useDetailedStats(dateFrom?: string, dateTo?: string) {
  const { fetchAPI } = useAPI();
  const isAuthenticated = useIsAuthenticated();

  return useQuery({
    queryKey: ['detailed-stats', dateFrom, dateTo],
    queryFn: async () => {
      const params = new URLSearchParams();
      if (dateFrom) params.set('date_from', dateFrom);
      if (dateTo) params.set('date_to', dateTo);
      const qs = params.toString();
      const data = await fetchAPI(`/api/stats/detailed${qs ? `?${qs}` : ''}`);
      return data;
    },
    enabled: isAuthenticated,
    refetchInterval: 30000,
  });
}

export function useActivityHistory() {
  const { fetchAPI } = useAPI();
  const isAuthenticated = useIsAuthenticated();

  return useQuery({
    queryKey: ['activity-history'],
    queryFn: async () => {
      const data = await fetchAPI('/api/stats/history?days=14');
      return data || [];
    },
    enabled: isAuthenticated,
  });
}

export function useConfig() {
  const { fetchAPI } = useAPI();
  const queryClient = useQueryClient();
  const isAuthenticated = useIsAuthenticated();

  const configQuery = useQuery({
    queryKey: ['config'],
    queryFn: async () => fetchAPI('/api/config'),
    enabled: isAuthenticated,
  });

  const modelQuery = useQuery({
    queryKey: ['config-model'],
    queryFn: async () => fetchAPI('/api/config/model'),
    enabled: isAuthenticated,
  });
  
  const updateModelMutation = useMutation({
    mutationFn: async (model: string) => {
      return fetchAPI('/api/config/model', {
        method: 'POST',
        body: JSON.stringify({ model }),
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['config-model'] });
      queryClient.invalidateQueries({ queryKey: ['stats'] });
      toast.success('Model updated successfully');
    },
    onError: () => {
      toast.error('Failed to update model');
    },
  });
  
  return {
    config: configQuery.data,
    model: modelQuery.data,
    isLoading: configQuery.isLoading || modelQuery.isLoading,
    updateModel: updateModelMutation.mutate,
  };
}

export function useTools() {
  const { fetchAPI } = useAPI();
  const isAuthenticated = useIsAuthenticated();

  return useQuery({
    queryKey: ['tools'],
    queryFn: async () => fetchAPI('/api/tools'),
    enabled: isAuthenticated,
  });
}

export function useToolExecutions() {
  const { fetchAPI } = useAPI();
  const isAuthenticated = useIsAuthenticated();

  return useQuery({
    queryKey: ['tool-executions'],
    queryFn: async () => fetchAPI('/api/tools/executions?limit=20'),
    enabled: isAuthenticated,
  });
}

export function useSkills() {
  const { fetchAPI } = useAPI();
  const queryClient = useQueryClient();
  const isAuthenticated = useIsAuthenticated();

  const skillsQuery = useQuery({
    queryKey: ['skills'],
    queryFn: async () => fetchAPI('/api/skills'),
    enabled: isAuthenticated,
  });
  
  const toggleMutation = useMutation({
    mutationFn: async ({ id, activate }: { id: number; activate: boolean }) => {
      return fetchAPI(`/api/skills/${id}/toggle`, { method: 'POST' });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['skills'] });
    },
  });
  
  const deleteMutation = useMutation({
    mutationFn: async (id: number) => {
      return fetchAPI(`/api/skills/${id}`, { method: 'DELETE' });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['skills'] });
      toast.success('Skill deleted successfully');
    },
  });
  
  const createMutation = useMutation({
    mutationFn: async (data: unknown) => {
      return fetchAPI('/api/skills', {
        method: 'POST',
        body: JSON.stringify(data),
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['skills'] });
      toast.success('Skill created successfully');
    },
  });
  
  const updateMutation = useMutation({
    mutationFn: async ({ id, data }: { id: number; data: unknown }) => {
      return fetchAPI(`/api/skills/${id}`, {
        method: 'PUT',
        body: JSON.stringify(data),
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['skills'] });
      toast.success('Skill updated successfully');
    },
  });
  
  const generateMutation = useMutation({
    mutationFn: async (data: unknown) => {
      return fetchAPI('/api/skills/generate', {
        method: 'POST',
        body: JSON.stringify(data),
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['skills'] });
      toast.success('Skill generated with AI');
    },
  });
  
  return {
    skills: skillsQuery.data,
    isLoading: skillsQuery.isLoading,
    toggleSkill: toggleMutation.mutate,
    deleteSkill: deleteMutation.mutate,
    createSkill: createMutation.mutate,
    updateSkill: updateMutation.mutate,
    generateSkill: generateMutation.mutate,
  };
}

export function useMCPServers() {
  const { fetchAPI } = useAPI();
  const queryClient = useQueryClient();
  const isAuthenticated = useIsAuthenticated();

  const serversQuery = useQuery({
    queryKey: ['mcp-servers'],
    queryFn: async () => fetchAPI('/api/mcp/servers'),
    enabled: isAuthenticated,
    refetchInterval: 10000,
  });

  const addMutation = useMutation({
    mutationFn: async (data: unknown) =>
      fetchAPI('/api/mcp/servers', { method: 'POST', body: JSON.stringify(data) }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['mcp-servers'] });
      toast.success('Server added');
    },
    onError: () => toast.error('Failed to add server'),
  });

  const updateMutation = useMutation({
    mutationFn: async ({ name, data }: { name: string; data: unknown }) =>
      fetchAPI(`/api/mcp/servers/${encodeURIComponent(name)}`, {
        method: 'PUT',
        body: JSON.stringify(data),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['mcp-servers'] });
      toast.success('Server updated');
    },
    onError: () => toast.error('Failed to update server'),
  });

  const removeMutation = useMutation({
    mutationFn: async (name: string) =>
      fetchAPI(`/api/mcp/servers/${encodeURIComponent(name)}`, { method: 'DELETE' }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['mcp-servers'] });
      toast.success('Server removed');
    },
    onError: () => toast.error('Failed to remove server'),
  });

  const connectMutation = useMutation({
    mutationFn: async (name: string) =>
      fetchAPI(`/api/mcp/servers/${encodeURIComponent(name)}/connect`, { method: 'POST' }),
    onSuccess: (_data, name) => {
      queryClient.invalidateQueries({ queryKey: ['mcp-servers'] });
      queryClient.invalidateQueries({ queryKey: ['tools'] });
      toast.success(`Connected to ${name}`);
    },
    onError: (_err, name) => toast.error(`Failed to connect to ${name}`),
  });

  const disconnectMutation = useMutation({
    mutationFn: async (name: string) =>
      fetchAPI(`/api/mcp/servers/${encodeURIComponent(name)}/disconnect`, { method: 'POST' }),
    onSuccess: (_data, name) => {
      queryClient.invalidateQueries({ queryKey: ['mcp-servers'] });
      queryClient.invalidateQueries({ queryKey: ['tools'] });
      toast.success(`Disconnected from ${name}`);
    },
    onError: () => toast.error('Failed to disconnect'),
  });

  return {
    servers: (serversQuery.data || []) as MCPServer[],
    isLoading: serversQuery.isLoading,
    addServer: addMutation.mutate,
    updateServer: updateMutation.mutate,
    removeServer: removeMutation.mutate,
    connectServer: connectMutation.mutate,
    disconnectServer: disconnectMutation.mutate,
    isConnecting: connectMutation.isPending,
    isDisconnecting: disconnectMutation.isPending,
  };
}

export interface MCPServer {
  name: string;
  transport: 'stdio' | 'sse';
  command: string;
  args: string[];
  url: string;
  api_key?: string;
  auto_connect: boolean;
  connected: boolean;
  error: string | null;
  tools: Array<{ name: string; description: string; inputSchema: Record<string, unknown> }>;
}

export function useConversations() {
  const { fetchAPI } = useAPI();
  const isAuthenticated = useIsAuthenticated();

  return useQuery({
    queryKey: ['conversations'],
    queryFn: async () => fetchAPI('/api/conversations'),
    enabled: isAuthenticated,
    refetchInterval: 10000,
  });
}

export function useConversationHistory(channelId: string, userId: string) {
  const { fetchAPI } = useAPI();
  const isAuthenticated = useIsAuthenticated();

  return useQuery({
    queryKey: ['conversation-history', channelId, userId],
    queryFn: async () => fetchAPI(`/api/conversations/${channelId}/${userId}?limit=50`),
    enabled: isAuthenticated && !!channelId && !!userId,
  });
}

export function useChatCommand() {
  const { fetchAPI } = useAPI();

  return useMutation({
    mutationFn: async ({
      command,
      userId = 'web',
      channelId = 'web',
    }: {
      command: string;
      userId?: string;
      channelId?: string;
    }) => {
      return fetchAPI('/api/chat/command', {
        method: 'POST',
        body: JSON.stringify({ command, user_id: userId, channel_id: channelId }),
      });
    },
  });
}

export function useClearConversation() {
  const { fetchAPI } = useAPI();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async ({
      channelId,
      userId,
    }: {
      channelId: string;
      userId: string;
    }) => {
      return fetchAPI(`/api/conversations/${channelId}/${userId}`, {
        method: 'DELETE',
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['conversations'] });
      queryClient.invalidateQueries({ queryKey: ['conversation-history'] });
    },
  });
}

export function useSystemInfo() {
  const { fetchAPI } = useAPI();
  const isAuthenticated = useIsAuthenticated();

  return useQuery({
    queryKey: ['system-info'],
    queryFn: async () => fetchAPI('/api/system/info'),
    enabled: isAuthenticated,
    staleTime: Infinity, // encryption status doesn't change at runtime
  });
}

export function useCurrentModel() {
  const { fetchAPI } = useAPI();
  const isAuthenticated = useIsAuthenticated();

  return useQuery({
    queryKey: ['config-model'],
    queryFn: async () => fetchAPI('/api/config/model'),
    enabled: isAuthenticated,
    refetchInterval: 30000,
  });
}

export function useMediaFiles() {
  const { fetchAPI } = useAPI();
  const isAuthenticated = useIsAuthenticated();

  return useQuery({
    queryKey: ['media-files'],
    queryFn: async () => {
      const data = await fetchAPI('/api/media');
      return (data || []) as Array<{ name: string; size: number; modified: string; ext: string }>;
    },
    enabled: isAuthenticated,
    refetchInterval: 10000,
  });
}
