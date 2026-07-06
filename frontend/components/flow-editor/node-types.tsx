'use client';

import { Handle, Position, type NodeProps } from '@xyflow/react';

export type NodeCategory = 'flow' | 'logic' | 'integration' | 'data';

export const CATEGORY_COLORS: Record<NodeCategory, string> = {
  flow: 'var(--acm-accent)',
  logic: 'var(--acm-node-logic)',
  integration: 'var(--acm-info)',
  data: 'var(--acm-node-data)',
};

export const NODE_CATEGORY: Record<string, NodeCategory> = {
  start: 'flow',
  end: 'flow',
  conditional: 'logic',
  http: 'integration',
  woocommerce: 'integration',
  variable: 'data',
};

function baseStyleFor(type: string): React.CSSProperties {
  return {
    padding: '8px 12px', borderRadius: 8, fontSize: 11,
    background: 'var(--acm-elev)', border: `1px solid ${CATEGORY_COLORS[NODE_CATEGORY[type]]}`,
    color: 'var(--acm-fg-2)', minWidth: 140,
  };
}

const idStyle: React.CSSProperties = {
  fontFamily: 'monospace', fontSize: 10, color: 'var(--acm-accent)', marginTop: 4,
  userSelect: 'all', cursor: 'text',
};

export function StartNode({ data }: NodeProps) {
  return (
    <div style={baseStyleFor('start')}>
      <div style={{ fontWeight: 600, marginBottom: 4, color: CATEGORY_COLORS.flow }}>▶ Inicio</div>
      <div style={{ color: 'var(--acm-fg-4)' }}>{(data.parameters as any[] || []).length} parámetro(s)</div>
      <Handle type="source" position={Position.Bottom} id="default" />
    </div>
  );
}

export function HttpNode({ id, data }: NodeProps) {
  return (
    <div style={baseStyleFor('http')}>
      <div style={{ fontWeight: 600, marginBottom: 4, color: CATEGORY_COLORS.integration }}>🌐 HTTP Request</div>
      <div style={{ color: 'var(--acm-fg-4)' }}>{String(data.method || 'GET')} {String(data.url || '')}</div>
      <div style={idStyle}>{'{{'}{id}{'}}'}</div>
      <Handle type="target" position={Position.Top} id="default" />
      <Handle type="source" position={Position.Bottom} id="default" />
    </div>
  );
}

export function ConditionalNode({ id, data }: NodeProps) {
  return (
    <div style={baseStyleFor('conditional')}>
      <div style={{ fontWeight: 600, marginBottom: 4, color: CATEGORY_COLORS.logic }}>◆ Condicional</div>
      <div style={{ color: 'var(--acm-fg-4)' }}>{String(data.field || '')} {String(data.operator || '')} {String(data.value || '')}</div>
      <div style={idStyle}>{'{{'}{id}{'}}'}</div>
      <Handle type="target" position={Position.Top} id="default" />
      <Handle type="source" position={Position.Bottom} id="true" style={{ left: '30%' }} />
      <Handle type="source" position={Position.Bottom} id="false" style={{ left: '70%' }} />
    </div>
  );
}

export function WooCommerceNode({ id, data }: NodeProps) {
  return (
    <div style={baseStyleFor('woocommerce')}>
      <div style={{ fontWeight: 600, marginBottom: 4, color: CATEGORY_COLORS.integration }}>🛒 WooCommerce</div>
      <div style={{ color: 'var(--acm-fg-4)' }}>{String(data.search_term || '')}</div>
      <div style={idStyle}>{'{{'}{id}{'}}'}</div>
      <Handle type="target" position={Position.Top} id="default" />
      <Handle type="source" position={Position.Bottom} id="default" />
    </div>
  );
}

export function VariableNode({ id, data }: NodeProps) {
  return (
    <div style={baseStyleFor('variable')}>
      <div style={{ fontWeight: 600, marginBottom: 4, color: CATEGORY_COLORS.data }}>📦 Variable</div>
      <div style={{ color: 'var(--acm-fg-4)' }}>{String(data.name || '(sin nombre)')}</div>
      <div style={idStyle}>{'{{'}{id}{'}}'}</div>
      <Handle type="target" position={Position.Top} id="default" />
      <Handle type="source" position={Position.Bottom} id="default" />
    </div>
  );
}

export function EndNode({ data }: NodeProps) {
  return (
    <div style={baseStyleFor('end')}>
      <div style={{ fontWeight: 600, marginBottom: 4, color: CATEGORY_COLORS.flow }}>■ Final</div>
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
  variable: VariableNode,
  end: EndNode,
};
