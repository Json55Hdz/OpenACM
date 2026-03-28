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
    staleTime: 0,
    refetchOnMount: 'always',
  });
}

export function useProviderStatus() {
  const { fetchAPI } = useAPI();
  const isAuthenticated = useIsAuthenticated();

  return useQuery<ProviderStatus>({
    queryKey: ['provider-status'],
    queryFn: () => fetchAPI('/api/config/providers'),
    enabled: isAuthenticated,
    staleTime: 0,
    refetchOnMount: 'always',
  });
}

interface GoogleStatus {
  credentials_exist: boolean;
  token_exist: boolean;
}

export function useGoogleStatus() {
  const { fetchAPI } = useAPI();
  const isAuthenticated = useIsAuthenticated();

  return useQuery<GoogleStatus>({
    queryKey: ['google-status'],
    queryFn: () => fetchAPI('/api/config/google'),
    enabled: isAuthenticated,
    staleTime: 0,
    refetchOnMount: 'always',
  });
}

export function useSaveGoogleCredentials() {
  const { fetchAPI } = useAPI();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (credentials_json: string) =>
      fetchAPI('/api/config/google', {
        method: 'POST',
        body: JSON.stringify({ credentials_json }),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['google-status'] });
      toast.success('Credentials saved — now click "Connect with Google" to authorize');
    },
    onError: () => {
      toast.error('Invalid credentials JSON');
    },
  });
}

export function useStartGoogleAuth() {
  const { fetchAPI } = useAPI();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: () => fetchAPI('/api/config/google/start_auth', { method: 'POST' }),
    onSuccess: (data: { url: string }) => {
      // Open the Google authorization URL in a new tab
      window.open(data.url, '_blank', 'noopener,noreferrer');
      // Poll for the token every 2s for up to 3 minutes
      let attempts = 0;
      const interval = setInterval(async () => {
        attempts++;
        queryClient.invalidateQueries({ queryKey: ['google-status'] });
        const status = await fetchAPI('/api/config/google');
        if (status?.token_exist) {
          clearInterval(interval);
          toast.success('Google connected! Gmail, Calendar, Drive and YouTube are ready.');
          queryClient.invalidateQueries({ queryKey: ['google-status'] });
        } else if (attempts >= 90) {
          clearInterval(interval);
        }
      }, 2000);
    },
    onError: (err: Error) => {
      toast.error(err.message || 'Could not start Google authorization');
    },
  });
}

export function useDeleteGoogleCredentials() {
  const { fetchAPI } = useAPI();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: () => fetchAPI('/api/config/google', { method: 'DELETE' }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['google-status'] });
      toast.success('Google disconnected');
    },
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
    mutationFn: async ({ model, provider }: { model: string; provider?: string }) => {
      return fetchAPI('/api/config/model', {
        method: 'POST',
        body: JSON.stringify({ model, provider }),
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
