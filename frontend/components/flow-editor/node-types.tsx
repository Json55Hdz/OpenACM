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

// Classifies a given (nodeType, handleId, handleKind) as a "flow" pin
// (FlowExecutor.run()'s flow-walk steps through it — see flow_executor.py's
// edges_by_source) or a "data" pin (a template-substitutable value, wired
// through data_edges_by_target and never walked). Needed because, before
// this, only the TARGET side of a connection was ever checked (via
// `targetHandle !== 'default'`) — nothing distinguished a flow-out pin
// from a data-out pin on the SOURCE side, which let a data-output pin (e.g.
// WooCommerce's `result`) get wired as if it were a flow-out pin.
//
// The handle-id shape, cross-checked directly against this file for every
// node type (not assumed):
//   start:        source "default"                                  -> flow
//   end:          target "default"                                  -> flow
//   http:         target "default" -> flow; target "url"/"body" -> data;
//                 source "default"                                  -> flow
//   conditional:  target "default" -> flow; target "field"/"value" -> data;
//                 source "true"/"false"                             -> flow
//   woocommerce:  target "default" -> flow; target "search_term"  -> data;
//                 source "default" -> flow; source "result"/"count" -> data
//   set:          target "default" -> flow; target "value"        -> data;
//                 source "default"                                  -> flow
//   get:          ONE handle only — source, id="default" — but Get is a
//                 pure node (no flow-in/flow-out concept at all, see
//                 GetNode's comment below) and that "default" id carries
//                 its data output ("salida: value"), not a flow-walk step.
//                 This is the one place id="default" does NOT mean "flow
//                 pin" — every other node's source "default" genuinely is
//                 its flow-out pin.
//
// For every target handle, "default" is the flow-in pin and every other
// named target handle is a data pin. For every source handle (except
// Get's, per above), "default" and Conditional's "true"/"false" are flow
// pins and every other named source handle is a data pin.
export function classifyPin(nodeType: string | undefined, handleId: string | null | undefined, handleKind: 'source' | 'target'): 'flow' | 'data' {
  const id = handleId || 'default';
  if (nodeType === 'get') return 'data';
  if (handleKind === 'target') {
    return id === 'default' ? 'flow' : 'data';
  }
  if (nodeType === 'conditional' && (id === 'true' || id === 'false')) return 'flow';
  return id === 'default' ? 'flow' : 'data';
}

// Unreal-style pin shapes: flow pins render as a small diamond in the
// "flow" category color, data pins as a small circle in the "data"
// category color — reusing CATEGORY_COLORS rather than introducing a
// separate palette, so a pin's color always matches the same flow/data
// meaning as the edge it connects to.
const FLOW_PIN_STYLE: React.CSSProperties = {
  width: 10, height: 10, background: CATEGORY_COLORS.flow,
  border: '1px solid var(--acm-base)', borderRadius: 2,
  clipPath: 'polygon(50% 0%, 100% 50%, 50% 100%, 0% 50%)',
};

const DATA_PIN_STYLE: React.CSSProperties = {
  width: 9, height: 9, background: CATEGORY_COLORS.data,
  border: '1px solid var(--acm-base)', borderRadius: '50%',
};

// Style + native-tooltip props for a <Handle>, derived from the same
// classifyPin() used for connection validation — a pin's look and its
// connection rules can never drift apart. `label` is the human-readable
// field/branch name shown in the tooltip (e.g. "search_term", "true").
export function pinProps(nodeType: string, handleId: string | null | undefined, handleKind: 'source' | 'target', label: string): { style: React.CSSProperties; title: string } {
  const kind = classifyPin(nodeType, handleId, handleKind);
  if (kind === 'flow') {
    return { style: FLOW_PIN_STYLE, title: `Flujo: ${label} — define el orden de ejecución` };
  }
  return {
    style: DATA_PIN_STYLE,
    title: handleKind === 'target'
      ? `Dato: ${label} — arrastra un pin de salida aquí para conectar un valor`
      : `Dato: ${label} — arrastra hacia otro nodo para usar este valor`,
  };
}

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
  const out = pinProps('start', 'default', 'source', 'inicio → siguiente nodo');
  return (
    <div style={baseStyleFor('start')}>
      <div style={{ fontWeight: 600, marginBottom: 4, color: CATEGORY_COLORS.flow }}>▶ Inicio</div>
      <div style={{ color: 'var(--acm-fg-4)' }}>{(data.parameters as any[] || []).length} parámetro(s)</div>
      <Handle type="source" position={Position.Bottom} id="default" style={out.style} title={out.title} />
    </div>
  );
}

export function HttpNode({ id, data }: NodeProps) {
  const targetConnections = useNodeConnections({ id, handleType: 'target' });
  const urlWired = targetConnections.some(c => c.targetHandle === 'url');
  const bodyWired = targetConnections.some(c => c.targetHandle === 'body');
  const flowIn = pinProps('http', 'default', 'target', 'nodo anterior');
  const urlPin = pinProps('http', 'url', 'target', 'url');
  const bodyPin = pinProps('http', 'body', 'target', 'body');
  const flowOut = pinProps('http', 'default', 'source', 'siguiente nodo');
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
      <Handle type="target" position={Position.Top} id="default" style={flowIn.style} title={flowIn.title} />
      {/* Data-input pins for HTTP's wire-or-literal "url"/"body" fields —
          independent of the flow-in "default" handle above. method/headers
          stay literal-only, no pin, per the spec's explicit
          dropdown/template boundary. */}
      <Handle type="target" position={Position.Left} id="url" style={{ ...urlPin.style, top: '55%' }} title={urlPin.title} />
      <Handle type="target" position={Position.Left} id="body" style={{ ...bodyPin.style, top: '75%' }} title={bodyPin.title} />
      <Handle type="source" position={Position.Bottom} id="default" style={flowOut.style} title={flowOut.title} />
    </div>
  );
}

export function ConditionalNode({ id, data }: NodeProps) {
  const flowIn = pinProps('conditional', 'default', 'target', 'nodo anterior');
  const fieldPin = pinProps('conditional', 'field', 'target', 'field');
  const valuePin = pinProps('conditional', 'value', 'target', 'value');
  const truePin = pinProps('conditional', 'true', 'source', 'true');
  const falsePin = pinProps('conditional', 'false', 'source', 'false');
  return (
    <div style={{ ...baseStyleFor('conditional'), position: 'relative' }}>
      <MergeBadge id={id} />
      <div style={{ fontWeight: 600, marginBottom: 4, color: CATEGORY_COLORS.logic }}>◆ Condicional</div>
      <div style={{ color: 'var(--acm-fg-4)' }}>{String(data.field || '')} {String(data.operator || '')} {String(data.value || '')}</div>
      <div style={idStyle}>{'{{'}{id}{'}}'}</div>
      <div style={pinLabelStyle}>salida: result</div>
      <Handle type="target" position={Position.Top} id="default" style={flowIn.style} title={flowIn.title} />
      {/* Data-input pins for Conditional's wire-or-literal "field"/"value"
          fields — independent of the flow-in "default" handle above.
          operator stays dropdown-only, no pin, per the spec's explicit
          boundary. */}
      <Handle type="target" position={Position.Left} id="field" style={{ ...fieldPin.style, top: '55%' }} title={fieldPin.title} />
      <Handle type="target" position={Position.Left} id="value" style={{ ...valuePin.style, top: '75%' }} title={valuePin.title} />
      <Handle type="source" position={Position.Bottom} id="true" style={{ ...truePin.style, left: '30%' }} title={truePin.title} />
      <Handle type="source" position={Position.Bottom} id="false" style={{ ...falsePin.style, left: '70%' }} title={falsePin.title} />
    </div>
  );
}

export function WooCommerceNode({ id, data }: NodeProps) {
  const flowIn = pinProps('woocommerce', 'default', 'target', 'nodo anterior');
  const searchTermPin = pinProps('woocommerce', 'search_term', 'target', 'search_term');
  const flowOut = pinProps('woocommerce', 'default', 'source', 'siguiente nodo');
  const resultPin = pinProps('woocommerce', 'result', 'source', 'result');
  const countPin = pinProps('woocommerce', 'count', 'source', 'count');
  return (
    <div style={{ ...baseStyleFor('woocommerce'), position: 'relative' }}>
      <MergeBadge id={id} />
      <div style={{ fontWeight: 600, marginBottom: 4, color: CATEGORY_COLORS.integration }}>🛒 WooCommerce</div>
      <div style={{ color: 'var(--acm-fg-4)' }}>{String(data.search_term || '')}</div>
      <div style={idStyle}>{'{{'}{id}{'}}'}</div>
      <div style={pinLabelStyle}>salida: result</div>
      <div style={pinLabelStyle}>salida: count</div>
      <Handle type="target" position={Position.Top} id="default" style={flowIn.style} title={flowIn.title} />
      {/* Data-input pin for WooCommerce's wire-or-literal "search_term"
          field — independent of the flow-in "default" handle above. The
          Connection selector stays dropdown-only, no pin, per the spec's
          explicit boundary. */}
      <Handle type="target" position={Position.Left} id="search_term" style={{ ...searchTermPin.style, top: '55%' }} title={searchTermPin.title} />
      <Handle type="source" position={Position.Bottom} id="default" style={flowOut.style} title={flowOut.title} />
      {/* Named data-output pins (Task 4's backend {"result": ..., "count":
          ...} shape) — independent of the flow-out "default" handle above,
          which keeps its old id/position unchanged so every flow saved
          before this shipped still renders its existing flow edge
          correctly. */}
      <Handle type="source" position={Position.Right} id="result" style={{ ...resultPin.style, top: '40%' }} title={resultPin.title} />
      <Handle type="source" position={Position.Right} id="count" style={{ ...countPin.style, top: '65%' }} title={countPin.title} />
    </div>
  );
}

export function SetNode({ id, data }: NodeProps) {
  const flowIn = pinProps('set', 'default', 'target', 'nodo anterior');
  const valuePin = pinProps('set', 'value', 'target', 'value');
  const flowOut = pinProps('set', 'default', 'source', 'siguiente nodo');
  return (
    <div style={{ ...baseStyleFor('set'), position: 'relative' }}>
      <MergeBadge id={id} />
      <div style={{ fontWeight: 600, marginBottom: 4, color: CATEGORY_COLORS.data }}>💾 Guardar (Set)</div>
      <div style={{ color: 'var(--acm-fg-4)' }}>{String(data.name || '(sin nombre)')}</div>
      <div style={idStyle}>{'{{'}{id}{'}}'}</div>
      <div style={pinLabelStyle}>entrada: valor (opcional — sin conexión usa el nodo anterior)</div>
      <div style={pinLabelStyle}>salida: value</div>
      <Handle type="target" position={Position.Top} id="default" style={flowIn.style} title={flowIn.title} />
      {/* Second, independent target handle for Set's data-input pin
          (toHandle="value", matching flow_executor.py's Set-node branch) —
          can be wired from ANY node's output, not just the flow-immediate
          predecessor. Falls back to the old previous_id behavior when
          nothing is wired here. */}
      <Handle type="target" position={Position.Left} id="value" style={valuePin.style} title={valuePin.title} />
      <Handle type="source" position={Position.Bottom} id="default" style={flowOut.style} title={flowOut.title} />
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
  const out = pinProps('get', 'default', 'source', 'value');
  return (
    <div style={baseStyleFor('get')}>
      <div style={{ fontWeight: 600, marginBottom: 4, color: CATEGORY_COLORS.data }}>📤 Obtener (Get)</div>
      <div style={{ color: 'var(--acm-fg-4)' }}>{String(data.name || '(sin nombre)')}</div>
      <div style={idStyle}>{'{{'}{id}{'}}'}</div>
      <div style={pinLabelStyle}>salida: value</div>
      <Handle type="source" position={Position.Bottom} id="default" style={out.style} title={out.title} />
    </div>
  );
}

export function EndNode({ id, data }: NodeProps) {
  const flowIn = pinProps('end', 'default', 'target', 'nodo anterior');
  return (
    <div style={{ ...baseStyleFor('end'), position: 'relative' }}>
      <MergeBadge id={id} />
      <div style={{ fontWeight: 600, marginBottom: 4, color: CATEGORY_COLORS.flow }}>■ Final</div>
      <div style={{ color: 'var(--acm-fg-4)' }}>{String(data.template || '')}</div>
      <Handle type="target" position={Position.Top} id="default" style={flowIn.style} title={flowIn.title} />
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
