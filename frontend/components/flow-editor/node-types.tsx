'use client';

import { Handle, Position, type NodeProps } from '@xyflow/react';

const baseStyle: React.CSSProperties = {
  padding: '8px 12px', borderRadius: 8, fontSize: 11,
  background: 'var(--acm-elev)', border: '1px solid var(--acm-border)', color: 'var(--acm-fg-2)',
  minWidth: 140,
};

export function StartNode({ data }: NodeProps) {
  return (
    <div style={{ ...baseStyle, borderColor: 'var(--acm-accent)' }}>
      <div style={{ fontWeight: 600, marginBottom: 4 }}>▶ Inicio</div>
      <div style={{ color: 'var(--acm-fg-4)' }}>{(data.parameters as any[] || []).length} parámetro(s)</div>
      <Handle type="source" position={Position.Bottom} id="default" />
    </div>
  );
}

export function HttpNode({ data }: NodeProps) {
  return (
    <div style={baseStyle}>
      <div style={{ fontWeight: 600, marginBottom: 4 }}>🌐 HTTP Request</div>
      <div style={{ color: 'var(--acm-fg-4)' }}>{String(data.method || 'GET')} {String(data.url || '')}</div>
      <Handle type="target" position={Position.Top} id="default" />
      <Handle type="source" position={Position.Bottom} id="default" />
    </div>
  );
}

export function ConditionalNode({ data }: NodeProps) {
  return (
    <div style={baseStyle}>
      <div style={{ fontWeight: 600, marginBottom: 4 }}>◆ Condicional</div>
      <div style={{ color: 'var(--acm-fg-4)' }}>{String(data.field || '')} {String(data.operator || '')} {String(data.value || '')}</div>
      <Handle type="target" position={Position.Top} id="default" />
      <Handle type="source" position={Position.Bottom} id="true" style={{ left: '30%' }} />
      <Handle type="source" position={Position.Bottom} id="false" style={{ left: '70%' }} />
    </div>
  );
}

export function WooCommerceNode({ data }: NodeProps) {
  return (
    <div style={baseStyle}>
      <div style={{ fontWeight: 600, marginBottom: 4 }}>🛒 WooCommerce</div>
      <div style={{ color: 'var(--acm-fg-4)' }}>{String(data.search_term || '')}</div>
      <Handle type="target" position={Position.Top} id="default" />
      <Handle type="source" position={Position.Bottom} id="default" />
    </div>
  );
}

export function EndNode({ data }: NodeProps) {
  return (
    <div style={{ ...baseStyle, borderColor: 'var(--acm-accent)' }}>
      <div style={{ fontWeight: 600, marginBottom: 4 }}>■ Final</div>
      <div style={{ color: 'var(--acm-fg-4)' }}>{String(data.template || '')}</div>
      <Handle type="target" position={Position.Top} id="default" />
    </div>
  );
}

export const NODE_TYPES = {
  start: StartNode,
  http: HttpNode,
  conditional: ConditionalNode,
  woocommerce: WooCommerceNode,
  end: EndNode,
};
