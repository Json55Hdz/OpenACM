'use client';

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useAPI, useIsAuthenticated } from '@/hooks/use-api';
import { toast } from 'sonner';

interface ConfigStatus {
  needs_setup: boolean;
  provider?: string;
}

interface ProviderStatus {
  providers: Record<string, boolean>;
  telegram_configured: boolean;
}

export function useConfigStatus() {
  const { fetchAPI } = useAPI();
  const isAuthenticated = useIsAuthenticated();

  return useQuery<ConfigStatus>({
    queryKey: ['config-status'],
    queryFn: () => fetchAPI('/api/config/status'),
    enabled: isAuthenticated,
  });
}

export function useProviderStatus() {
  const { fetchAPI } = useAPI();
  const isAuthenticated = useIsAuthenticated();

  return useQuery<ProviderStatus>({
    queryKey: ['provider-status'],
    queryFn: () => fetchAPI('/api/config/providers'),
    enabled: isAuthenticated,
  });
}

export function useSaveSetup() {
  const { fetchAPI } = useAPI();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (keys: Record<string, string>) => {
      return fetchAPI('/api/config/setup', {
        method: 'POST',
        body: JSON.stringify(keys),
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['config-status'] });
      queryClient.invalidateQueries({ queryKey: ['provider-status'] });
      queryClient.invalidateQueries({ queryKey: ['config'] });
    },
    onError: () => {
      toast.error('Failed to save configuration');
    },
  });
}

export function useSetModel() {
  const { fetchAPI } = useAPI();
  const queryClient = useQueryClient();

  return useMutation({
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
}
