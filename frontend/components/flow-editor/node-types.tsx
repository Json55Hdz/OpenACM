'use client';

import { Handle, Position, useNodeConnections, type NodeProps } from '@xyflow/react';

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
  set: 'data',
  get: 'data',
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

const pinLabelStyle: React.CSSProperties = {
  fontSize: 9, color: 'var(--acm-fg-4)', marginTop: 2,
};

const mergeBadgeStyle: React.CSSProperties = {
  position: 'absolute', top: -6, right: -6, width: 14, height: 14, borderRadius: '50%',
  background: 'var(--acm-accent)', color: 'var(--acm-base)', fontSize: 9, fontWeight: 700,
  display: 'flex', alignItems: 'center', justifyContent: 'center',
};

function MergeBadge({ id }: { id: string }) {
  const incoming = useNodeConnections({ id, handleType: 'target' });
  // Only count edges into the flow-in "default" handle — a named data
  // handle (url/body/value/search_term/...) feeding this node is an
  // unrelated data wire, not a merging flow branch, and must not trip the
  // "merge point" badge. Without this filter, any node that has both a
  // flow-in edge AND a data edge wired to one of its field pins (e.g. an
  // HTTP node with a plain flow-in plus its `url` field wired from another
  // node) would incorrectly show as a 2-branch merge point.
  const flowIncoming = incoming.filter(c => c.targetHandle === 'default');
  if (flowIncoming.length < 2) return null;
  return <div style={mergeBadgeStyle} title="Punto de unión (varias ramas llegan aquí)">{flowIncoming.length}</div>;
}

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
  const targetConnections = useNodeConnections({ id, handleType: 'target' });
  const urlWired = targetConnections.some(c => c.targetHandle === 'url');
  const bodyWired = targetConnections.some(c => c.targetHandle === 'body');
  return (
    <div style={{ ...baseStyleFor('http'), position: 'relative' }}>
      <MergeBadge id={id} />
      <div style={{ fontWeight: 600, marginBottom: 4, color: CATEGORY_COLORS.integration }}>🌐 HTTP Request</div>
      <div style={{ color: 'var(--acm-fg-4)' }}>
        {String(data.method || 'GET')} {urlWired ? '🔌 url conectada' : String(data.url || '')}
      </div>
      {bodyWired && <div style={{ color: 'var(--acm-fg-4)' }}>🔌 body conectado</div>}
      <div style={idStyle}>{'{{'}{id}{'}}'}</div>
      <div style={pinLabelStyle}>salida: response</div>
      <Handle type="target" position={Position.Top} id="default" />
      {/* Data-input pins for HTTP's wire-or-literal "url"/"body" fields —
          independent of the flow-in "default" handle above. method/headers
          stay literal-only, no pin, per the spec's explicit
          dropdown/template boundary. */}
      <Handle type="target" position={Position.Left} id="url" style={{ top: '55%' }} />
      <Handle type="target" position={Position.Left} id="body" style={{ top: '75%' }} />
      <Handle type="source" position={Position.Bottom} id="default" />
    </div>
  );
}

export function ConditionalNode({ id, data }: NodeProps) {
  return (
    <div style={{ ...baseStyleFor('conditional'), position: 'relative' }}>
      <MergeBadge id={id} />
      <div style={{ fontWeight: 600, marginBottom: 4, color: CATEGORY_COLORS.logic }}>◆ Condicional</div>
      <div style={{ color: 'var(--acm-fg-4)' }}>{String(data.field || '')} {String(data.operator || '')} {String(data.value || '')}</div>
      <div style={idStyle}>{'{{'}{id}{'}}'}</div>
      <div style={pinLabelStyle}>salida: result</div>
      <Handle type="target" position={Position.Top} id="default" />
      {/* Data-input pins for Conditional's wire-or-literal "field"/"value"
          fields — independent of the flow-in "default" handle above.
          operator stays dropdown-only, no pin, per the spec's explicit
          boundary. */}
      <Handle type="target" position={Position.Left} id="field" style={{ top: '55%' }} />
      <Handle type="target" position={Position.Left} id="value" style={{ top: '75%' }} />
      <Handle type="source" position={Position.Bottom} id="true" style={{ left: '30%' }} />
      <Handle type="source" position={Position.Bottom} id="false" style={{ left: '70%' }} />
    </div>
  );
}

export function WooCommerceNode({ id, data }: NodeProps) {
  return (
    <div style={{ ...baseStyleFor('woocommerce'), position: 'relative' }}>
      <MergeBadge id={id} />
      <div style={{ fontWeight: 600, marginBottom: 4, color: CATEGORY_COLORS.integration }}>🛒 WooCommerce</div>
      <div style={{ color: 'var(--acm-fg-4)' }}>{String(data.search_term || '')}</div>
      <div style={idStyle}>{'{{'}{id}{'}}'}</div>
      <div style={pinLabelStyle}>salida: result</div>
      <div style={pinLabelStyle}>salida: count</div>
      <Handle type="target" position={Position.Top} id="default" />
      <Handle type="source" position={Position.Bottom} id="default" />
      {/* Named data-output pins (Task 4's backend {"result": ..., "count":
          ...} shape) — independent of the flow-out "default" handle above,
          which keeps its old id/position unchanged so every flow saved
          before this shipped still renders its existing flow edge
          correctly. */}
      <Handle type="source" position={Position.Right} id="result" style={{ top: '40%' }} />
      <Handle type="source" position={Position.Right} id="count" style={{ top: '65%' }} />
    </div>
  );
}

export function SetNode({ id, data }: NodeProps) {
  return (
    <div style={{ ...baseStyleFor('set'), position: 'relative' }}>
      <MergeBadge id={id} />
      <div style={{ fontWeight: 600, marginBottom: 4, color: CATEGORY_COLORS.data }}>💾 Guardar (Set)</div>
      <div style={{ color: 'var(--acm-fg-4)' }}>{String(data.name || '(sin nombre)')}</div>
      <div style={idStyle}>{'{{'}{id}{'}}'}</div>
      <div style={pinLabelStyle}>entrada: valor (opcional — sin conexión usa el nodo anterior)</div>
      <div style={pinLabelStyle}>salida: value</div>
      <Handle type="target" position={Position.Top} id="default" />
      {/* Second, independent target handle for Set's data-input pin
          (toHandle="value", matching flow_executor.py's Set-node branch) —
          can be wired from ANY node's output, not just the flow-immediate
          predecessor. Falls back to the old previous_id behavior when
          nothing is wired here. */}
      <Handle type="target" position={Position.Left} id="value" />
      <Handle type="source" position={Position.Bottom} id="default" />
    </div>
  );
}

// Get is a pure data node — no flow-in/flow-out handles, matching Unreal
// Blueprint's pure (non-exec) nodes. It's referenced directly by whatever
// needs its value, wherever that node sits in the graph, via a data edge
// (or the existing {{name}}/{{get_id}} template syntax) — never walked by
// FlowExecutor.run()'s flow-edge traversal. See resolve_field's Get
// special case in flow_executor.py (_resolve_pin_value) for how a
// never-walked Get node's value still gets computed on demand.
export function GetNode({ id, data }: NodeProps) {
  return (
    <div style={baseStyleFor('get')}>
      <div style={{ fontWeight: 600, marginBottom: 4, color: CATEGORY_COLORS.data }}>📤 Obtener (Get)</div>
      <div style={{ color: 'var(--acm-fg-4)' }}>{String(data.name || '(sin nombre)')}</div>
      <div style={idStyle}>{'{{'}{id}{'}}'}</div>
      <div style={pinLabelStyle}>salida: value</div>
      <Handle type="source" position={Position.Bottom} id="default" />
    </div>
  );
}

export function EndNode({ id, data }: NodeProps) {
  return (
    <div style={{ ...baseStyleFor('end'), position: 'relative' }}>
      <MergeBadge id={id} />
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
  set: SetNode,
  get: GetNode,
  end: EndNode,
};
