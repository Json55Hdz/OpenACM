'use client';

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useAPI, useIsAuthenticated } from '@/hooks/use-api';
import { toast } from 'sonner';

export interface PluginInfo {
  name: string;
  version: string;
  description: string;
  author: string;
  enabled: boolean;
  has_config_schema: boolean;
  has_custom_ui: boolean;
}

export interface PluginNavItem {
  path: string;
  label: string;
  icon: string;
  section?: string;
  plugin: string;
}

export interface PluginConfigField {
  key: string;
  label: string;
  type: 'text' | 'password' | 'number' | 'boolean';
  required: boolean;
  help: string;
}

export interface PluginConfigResponse {
  schema: PluginConfigField[];
  values: Record<string, string>;
}

export function usePlugins() {
  const { fetchAPI } = useAPI();
  const isAuthenticated = useIsAuthenticated();

  return useQuery<PluginInfo[]>({
    queryKey: ['plugins'],
    queryFn: () => fetchAPI('/api/plugins'),
    enabled: isAuthenticated,
    staleTime: 0,
    refetchOnMount: 'always',
  });
}

export function useTogglePlugin() {
  const { fetchAPI } = useAPI();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ name, enabled }: { name: string; enabled: boolean }) =>
      fetchAPI(`/api/plugins/${name}/toggle`, {
        method: 'POST',
        body: JSON.stringify({ enabled }),
      }),
    // Patch the cached list directly instead of invalidating: toggling only
    // writes plugin_state in the DB, the running process's in-memory enabled
    // state doesn't change until restart, so a refetch of GET /api/plugins
    // would report the OLD value and silently revert the checkbox.
    onSuccess: (_data, { name, enabled }) => {
      queryClient.setQueryData<PluginInfo[]>(['plugins'], (old) =>
        old?.map((p) => (p.name === name ? { ...p, enabled } : p))
      );
    },
    onError: () => toast.error('Failed to toggle plugin'),
  });
}

export function useRestartSystem() {
  const { fetchAPI } = useAPI();

  return useMutation({
    mutationFn: () => fetchAPI('/api/system/restart', { method: 'POST' }),
    onSuccess: () => toast.success('Reiniciando... el dashboard volverá en unos segundos'),
    onError: () => toast.error('Failed to restart'),
  });
}

export function usePluginConfig(name: string) {
  const { fetchAPI } = useAPI();
  const isAuthenticated = useIsAuthenticated();

  return useQuery<PluginConfigResponse>({
    queryKey: ['plugin-config', name],
    queryFn: () => fetchAPI(`/api/plugins/${name}/config`),
    enabled: isAuthenticated && !!name,
    staleTime: 0,
  });
}

export function useSavePluginConfig(name: string) {
  const { fetchAPI } = useAPI();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (values: Record<string, string>) =>
      fetchAPI(`/api/plugins/${name}/config`, {
        method: 'POST',
        body: JSON.stringify(values),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['plugin-config', name] });
      toast.success('Configuración guardada');
    },
    onError: (err: Error) => toast.error(err.message || 'Failed to save config'),
  });
}

export function usePluginNav() {
  const { fetchAPI } = useAPI();
  const isAuthenticated = useIsAuthenticated();

  return useQuery<PluginNavItem[]>({
    queryKey: ['plugin-nav'],
    queryFn: () => fetchAPI('/api/plugins/nav'),
    enabled: isAuthenticated,
    staleTime: 60_000,
  });
}

export function usePluginDocs() {
  const { fetchAPI } = useAPI();
  const isAuthenticated = useIsAuthenticated();

  return useQuery<string>({
    queryKey: ['plugin-docs'],
    queryFn: () => fetchAPI('/api/plugins/docs', { raw: true }),
    enabled: isAuthenticated,
    staleTime: Infinity,
  });
}
