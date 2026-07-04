'use client';

import { useQuery, useMutation } from '@tanstack/react-query';
import { useAPI, useIsAuthenticated } from '@/hooks/use-api';
import { toast } from 'sonner';

export interface HAEntity {
  entity_id: string;
  state: string;
  attributes: Record<string, any>;
}

export function useHADevices() {
  const { fetchAPI } = useAPI();
  const isAuthenticated = useIsAuthenticated();

  return useQuery<{ devices: HAEntity[] }>({
    queryKey: ['ha-devices'],
    queryFn: () => fetchAPI('/api/home-assistant/devices'),
    enabled: isAuthenticated,
    staleTime: 30_000,
  });
}

export function useHAScenes() {
  const { fetchAPI } = useAPI();
  const isAuthenticated = useIsAuthenticated();

  return useQuery<{ scenes: HAEntity[] }>({
    queryKey: ['ha-scenes'],
    queryFn: () => fetchAPI('/api/home-assistant/scenes'),
    enabled: isAuthenticated,
    staleTime: 30_000,
  });
}

export function useHAControl() {
  const { fetchAPI } = useAPI();

  return useMutation({
    mutationFn: ({ entityId, action, ...params }: { entityId: string; action: string; [k: string]: any }) =>
      fetchAPI(`/api/home-assistant/devices/${entityId}/control`, {
        method: 'POST',
        body: JSON.stringify({ action, ...params }),
      }),
    onError: (err: Error) => toast.error(err.message || 'No se pudo controlar el dispositivo'),
  });
}

export function useHAActivateScene() {
  const { fetchAPI } = useAPI();

  return useMutation({
    mutationFn: (entityId: string) =>
      fetchAPI(`/api/home-assistant/scenes/${entityId}/activate`, { method: 'POST' }),
    onSuccess: () => toast.success('Escena activada'),
    onError: (err: Error) => toast.error(err.message || 'No se pudo activar la escena'),
  });
}
