'use client';

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useAPI, useIsAuthenticated } from '@/hooks/use-api';

export interface WebhookConnector {
  id: number;
  slug: string;
  name: string;
  auth_scheme: 'hmac_sha256' | 'bearer_token' | 'static_header_secret';
  auth_config: string; // JSON string, secret fields masked as "***" except right after create
  flow_id: number;
  dedupe_header: string | null;
  enabled: number;
  created_at: string;
}

export interface WebhookConnectorEvent {
  id: number;
  received_at: string;
  status: 'ok' | 'auth_failed' | 'bad_request' | 'flow_error';
  result: string | null;
  duration_ms: number;
}

export interface WebhookConnectorStats {
  total: number;
  by_status: Record<string, number>;
}

export function useWebhookConnectors() {
  const { fetchAPI } = useAPI();
  const isAuthenticated = useIsAuthenticated();
  return useQuery<WebhookConnector[]>({
    queryKey: ['webhook-connectors'],
    queryFn: () => fetchAPI('/api/webhook-connectors'),
    enabled: isAuthenticated,
  });
}

export function useWebhookConnectorEvents(connectorId: number | null) {
  const { fetchAPI } = useAPI();
  const isAuthenticated = useIsAuthenticated();
  return useQuery<{ events: WebhookConnectorEvent[]; stats: WebhookConnectorStats }>({
    queryKey: ['webhook-connector-events', connectorId],
    queryFn: () => fetchAPI(`/api/webhook-connectors/${connectorId}/events`),
    enabled: isAuthenticated && connectorId !== null,
  });
}

export function useWebhookConnectorMutations() {
  const { fetchAPI } = useAPI();
  const qc = useQueryClient();
  const invalidate = () => qc.invalidateQueries({ queryKey: ['webhook-connectors'] });

  const create = useMutation({
    mutationFn: (data: Omit<WebhookConnector, 'id' | 'created_at' | 'enabled'> & { auth_config: object }) =>
      fetchAPI('/api/webhook-connectors', { method: 'POST', body: JSON.stringify(data) }),
    onSuccess: invalidate,
  });

  const update = useMutation({
    mutationFn: ({ id, ...data }: { id: number; [key: string]: unknown }) =>
      fetchAPI(`/api/webhook-connectors/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
    onSuccess: invalidate,
  });

  const remove = useMutation({
    mutationFn: (id: number) => fetchAPI(`/api/webhook-connectors/${id}`, { method: 'DELETE' }),
    onSuccess: invalidate,
  });

  return { create, update, remove };
}
