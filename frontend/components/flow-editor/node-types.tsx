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
  loop: 'logic',
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
//   loop:         target "default" -> flow; target "items"        -> data;
//                 source "loop"/"done"                              -> flow;
//                 source "item"/"index"                             -> data
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
// Get's, per above), "default", Conditional's "true"/"false", and Loop's
// "loop"/"done" are flow pins and every other named source handle is a
// data pin.
export function classifyPin(nodeType: string | undefined, handleId: string | null | undefined, handleKind: 'source' | 'target'): 'flow' | 'data' {
  const id = handleId || 'default';
  if (nodeType === 'get') return 'data';
  if (handleKind === 'target') {
    return id === 'default' ? 'flow' : 'data';
  }
  if (nodeType === 'conditional' && (id === 'true' || id === 'false')) return 'flow';
  if (nodeType === 'loop' && (id === 'loop' || id === 'done')) return 'flow';
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

function truncate(value: string, max = 40): string {
  return value.length > max ? `${value.slice(0, max)}…` : value;
}

// One sentence per node TYPE (not per instance) — "what does this kind of
// node do," shown via the header's (?) icon tooltip.
const NODE_DESCRIPTIONS: Record<string, string> = {
  start: 'Punto de entrada del flujo. Define los parámetros que recibe cuando se ejecuta.',
  http: 'Hace una petición web (GET/POST/...) a una URL y guarda la respuesta para usar en nodos siguientes.',
  conditional: 'Evalúa una condición sobre un valor y bifurca el flujo en dos ramas: true o false.',
  loop: 'Repite una cadena de nodos una vez por cada elemento de una lista. No hace falta conectar nada de vuelta: cuando la cadena del cuerpo llega a un punto muerto, sigue automáticamente con el próximo elemento.',
  woocommerce: 'Busca productos en una tienda WooCommerce conectada y devuelve los resultados.',
  set: 'Guarda un valor bajo un nombre para poder reutilizarlo más adelante en el flujo.',
  get: 'Recupera un valor guardado previamente por un nodo Guardar (Set), en cualquier punto del flujo.',
  end: 'Punto final del flujo. Arma la respuesta final combinando texto fijo y valores de nodos anteriores.',
};

function InfoIcon({ description }: { description: string }) {
  if (!description) return null;
  return (
    <span
      title={description}
      style={{
        display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
        width: 13, height: 13, borderRadius: '50%', fontSize: 9, fontWeight: 700,
        color: 'var(--acm-fg-3)', border: '1px solid var(--acm-fg-4)', cursor: 'help',
        flexShrink: 0,
      }}
    >
      ?
    </span>
  );
}

// Shared card wrapper every node type below renders into: a category-tinted
// header bar (icon + title + info tooltip) separated from the body, an
// accent-colored glow when `selected` (a prop React Flow passes to every
// custom node component — see NodeProps), and `position: relative` so
// MergeBadge's absolute top-right offset resolves against the whole card
// regardless of how deep inside `children` it's rendered.
function NodeCard({ type, icon, title, selected, children }: {
  type: string; icon: string; title: string; selected?: boolean; children: React.ReactNode;
}) {
  const color = CATEGORY_COLORS[NODE_CATEGORY[type]];
  return (
    <div
      style={{
        borderRadius: 8, fontSize: 11, background: 'var(--acm-elev)',
        border: `1px solid ${color}`, color: 'var(--acm-fg-2)', minWidth: 160,
        position: 'relative', overflow: 'visible',
        boxShadow: selected ? '0 0 0 2px var(--acm-accent), 0 0 12px oklch(0.84 0.16 82 / 0.5)' : 'none',
      }}
    >
      <div
        style={{
          display: 'flex', alignItems: 'center', gap: 6, padding: '5px 8px',
          borderRadius: '7px 7px 0 0', borderBottom: `1px solid ${color}`,
          background: `color-mix(in srgb, ${color} 18%, transparent)`,
          fontWeight: 600,
        }}
      >
        <span>{icon}</span>
        <span style={{ flex: 1 }}>{title}</span>
        <InfoIcon description={NODE_DESCRIPTIONS[type] || ''} />
      </div>
      <div style={{ padding: '6px 8px', display: 'flex', flexDirection: 'column', gap: 3 }}>
        {children}
      </div>
    </div>
  );
}

// One row per DATA pin (never a flow pin — those stay on the card's
// top/bottom edge, unchanged). The Handle renders with `position: 'static'`
// (overriding React Flow's own default `position: absolute` handle CSS via
// inline style, which always wins) so it sits in the row's normal flex flow
// instead of needing a manually-tuned percentage offset — React Flow
// measures each Handle's actual rendered DOM position for edge-anchoring,
// so this works regardless of nesting depth. Input rows read
// pin-then-label(-then-preview) left-aligned; output rows read
// label-then-pin right-aligned — matching an input's dot-on-the-left /
// output's dot-on-the-right convention.
function PinRow({ nodeType, handleId, handleKind, label, literalPreview }: {
  nodeType: string; handleId: string; handleKind: 'source' | 'target'; label: string; literalPreview?: string;
}) {
  const { style, title } = pinProps(nodeType, handleId, handleKind, label);
  const handleEl = (
    <Handle
      type={handleKind}
      position={handleKind === 'target' ? Position.Left : Position.Right}
      id={handleId}
      style={{ ...style, position: 'static' }}
      title={title}
    />
  );
  if (handleKind === 'target') {
    return (
      <div style={{ display: 'flex', alignItems: 'center', gap: 5, minHeight: 16 }}>
        {handleEl}
        <span style={{ color: 'var(--acm-fg-3)' }}>{label}</span>
        {literalPreview && <span className="mono" style={{ color: 'var(--acm-fg-4)', fontSize: 9 }}>{literalPreview}</span>}
      </div>
    );
  }
  return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: 5, minHeight: 16 }}>
      <span style={{ color: 'var(--acm-fg-3)' }}>{label}</span>
      {handleEl}
    </div>
  );
}

export function StartNode({ data, selected }: NodeProps) {
  const out = pinProps('start', 'default', 'source', 'inicio → siguiente nodo');
  return (
    <NodeCard type="start" icon="▶" title="Inicio" selected={selected}>
      <div style={{ color: 'var(--acm-fg-4)' }}>{(data.parameters as any[] || []).length} parámetro(s)</div>
      <Handle type="source" position={Position.Bottom} id="default" style={out.style} title={out.title} />
    </NodeCard>
  );
}

export function HttpNode({ id, data, selected }: NodeProps) {
  const targetConnections = useNodeConnections({ id, handleType: 'target' });
  const urlWired = targetConnections.some(c => c.targetHandle === 'url');
  const bodyWired = targetConnections.some(c => c.targetHandle === 'body');
  const flowIn = pinProps('http', 'default', 'target', 'nodo anterior');
  const flowOut = pinProps('http', 'default', 'source', 'siguiente nodo');
  return (
    <NodeCard type="http" icon="🌐" title="HTTP Request" selected={selected}>
      <MergeBadge id={id} />
      <div style={{ color: 'var(--acm-fg-4)' }}>{String(data.method || 'GET')}</div>
      <PinRow nodeType="http" handleId="url" handleKind="target" label="url" literalPreview={urlWired || !data.url ? undefined : truncate(String(data.url))} />
      <PinRow nodeType="http" handleId="body" handleKind="target" label="body" literalPreview={bodyWired || !data.body ? undefined : truncate(String(data.body))} />
      <div style={idStyle}>{'{{'}{id}{'}}'}</div>
      <div style={pinLabelStyle}>salida: response</div>
      <Handle type="target" position={Position.Top} id="default" style={flowIn.style} title={flowIn.title} />
      <Handle type="source" position={Position.Bottom} id="default" style={flowOut.style} title={flowOut.title} />
    </NodeCard>
  );
}

export function ConditionalNode({ id, data, selected }: NodeProps) {
  const targetConnections = useNodeConnections({ id, handleType: 'target' });
  const fieldWired = targetConnections.some(c => c.targetHandle === 'field');
  const valueWired = targetConnections.some(c => c.targetHandle === 'value');
  const flowIn = pinProps('conditional', 'default', 'target', 'nodo anterior');
  const truePin = pinProps('conditional', 'true', 'source', 'true');
  const falsePin = pinProps('conditional', 'false', 'source', 'false');
  return (
    <NodeCard type="conditional" icon="◆" title="Condicional" selected={selected}>
      <MergeBadge id={id} />
      <div style={{ color: 'var(--acm-fg-4)' }}>{String(data.operator || '')}</div>
      <PinRow nodeType="conditional" handleId="field" handleKind="target" label="field" literalPreview={fieldWired || !data.field ? undefined : truncate(String(data.field))} />
      <PinRow nodeType="conditional" handleId="value" handleKind="target" label="value" literalPreview={valueWired || !data.value ? undefined : truncate(String(data.value))} />
      <div style={idStyle}>{'{{'}{id}{'}}'}</div>
      <div style={pinLabelStyle}>salida: result</div>
      <Handle type="target" position={Position.Top} id="default" style={flowIn.style} title={flowIn.title} />
      <Handle type="source" position={Position.Bottom} id="true" style={{ ...truePin.style, left: '30%' }} title={truePin.title} />
      <Handle type="source" position={Position.Bottom} id="false" style={{ ...falsePin.style, left: '70%' }} title={falsePin.title} />
      {/* Unreal shows a label on every exec pin that isn't a lone default
          in/out — Conditional's two flow-out branches are exactly that
          case, so (unlike every other node's single flow-in/flow-out,
          which stays unlabeled per the spec) these two get a persistent
          label instead of relying only on the Handle's hover title.
          pointerEvents: 'none' keeps these purely visual — without it, the
          label divs can sit on top of the diamond pins' hit-test area in
          paint order and intercept clicks/drags meant for the Handle. */}
      <div style={{ position: 'absolute', bottom: -14, left: '30%', transform: 'translateX(-50%)', fontSize: 8, color: 'var(--acm-fg-4)', pointerEvents: 'none' }}>true</div>
      <div style={{ position: 'absolute', bottom: -14, left: '70%', transform: 'translateX(-50%)', fontSize: 8, color: 'var(--acm-fg-4)', pointerEvents: 'none' }}>false</div>
    </NodeCard>
  );
}

export function LoopNode({ id, data, selected }: NodeProps) {
  const flowIn = pinProps('loop', 'default', 'target', 'nodo anterior');
  const loopPin = pinProps('loop', 'loop', 'source', 'loop');
  const donePin = pinProps('loop', 'done', 'source', 'done');
  return (
    <NodeCard type="loop" icon="🔁" title="Bucle (Por cada)" selected={selected}>
      <MergeBadge id={id} />
      <PinRow nodeType="loop" handleId="items" handleKind="target" label="items" />
      <div style={idStyle}>{'{{'}{id}{'}}'}</div>
      <PinRow nodeType="loop" handleId="item" handleKind="source" label="item" />
      <PinRow nodeType="loop" handleId="index" handleKind="source" label="index" />
      <Handle type="target" position={Position.Top} id="default" style={flowIn.style} title={flowIn.title} />
      <Handle type="source" position={Position.Bottom} id="loop" style={{ ...loopPin.style, left: '30%' }} title={loopPin.title} />
      <Handle type="source" position={Position.Bottom} id="done" style={{ ...donePin.style, left: '70%' }} title={donePin.title} />
      {/* Same reasoning as Conditional's true/false labels: two flow-out
          pins on one node need persistent labels, unlike every other
          node's single flow-in/flow-out pair. pointerEvents: 'none' keeps
          them from stealing clicks meant for the diamond pins underneath. */}
      <div style={{ position: 'absolute', bottom: -14, left: '30%', transform: 'translateX(-50%)', fontSize: 8, color: 'var(--acm-fg-4)', pointerEvents: 'none' }}>loop</div>
      <div style={{ position: 'absolute', bottom: -14, left: '70%', transform: 'translateX(-50%)', fontSize: 8, color: 'var(--acm-fg-4)', pointerEvents: 'none' }}>done</div>
    </NodeCard>
  );
}

export function WooCommerceNode({ id, data, selected }: NodeProps) {
  const targetConnections = useNodeConnections({ id, handleType: 'target' });
  const searchTermWired = targetConnections.some(c => c.targetHandle === 'search_term');
  const flowIn = pinProps('woocommerce', 'default', 'target', 'nodo anterior');
  const flowOut = pinProps('woocommerce', 'default', 'source', 'siguiente nodo');
  return (
    <NodeCard type="woocommerce" icon="🛒" title="WooCommerce" selected={selected}>
      <MergeBadge id={id} />
      <PinRow nodeType="woocommerce" handleId="search_term" handleKind="target" label="search_term" literalPreview={searchTermWired || !data.search_term ? undefined : truncate(String(data.search_term))} />
      <div style={idStyle}>{'{{'}{id}{'}}'}</div>
      <PinRow nodeType="woocommerce" handleId="result" handleKind="source" label="result" />
      <PinRow nodeType="woocommerce" handleId="count" handleKind="source" label="count" />
      <Handle type="target" position={Position.Top} id="default" style={flowIn.style} title={flowIn.title} />
      <Handle type="source" position={Position.Bottom} id="default" style={flowOut.style} title={flowOut.title} />
    </NodeCard>
  );
}

export function SetNode({ id, data, selected }: NodeProps) {
  const flowIn = pinProps('set', 'default', 'target', 'nodo anterior');
  const flowOut = pinProps('set', 'default', 'source', 'siguiente nodo');
  return (
    <NodeCard type="set" icon="💾" title="Guardar (Set)" selected={selected}>
      <MergeBadge id={id} />
      <div style={{ color: 'var(--acm-fg-4)' }}>{String(data.name || '(sin nombre)')}</div>
      <PinRow nodeType="set" handleId="value" handleKind="target" label="valor (opcional)" />
      <div style={idStyle}>{'{{'}{id}{'}}'}</div>
      <div style={pinLabelStyle}>salida: value</div>
      <Handle type="target" position={Position.Top} id="default" style={flowIn.style} title={flowIn.title} />
      <Handle type="source" position={Position.Bottom} id="default" style={flowOut.style} title={flowOut.title} />
    </NodeCard>
  );
}

// Get is a pure data node — no flow-in/flow-out handles, matching Unreal
// Blueprint's pure (non-exec) nodes. It's referenced directly by whatever
// needs its value, wherever that node sits in the graph, via a data edge
// (or the existing {{name}}/{{get_id}} template syntax) — never walked by
// FlowExecutor.run()'s flow-edge traversal. See resolve_field's Get
// special case in flow_executor.py (_resolve_pin_value) for how a
// never-walked Get node's value still gets computed on demand.
export function GetNode({ id, data, selected }: NodeProps) {
  return (
    <NodeCard type="get" icon="📤" title="Obtener (Get)" selected={selected}>
      <div style={{ color: 'var(--acm-fg-4)' }}>{String(data.name || '(sin nombre)')}</div>
      <div style={idStyle}>{'{{'}{id}{'}}'}</div>
      <PinRow nodeType="get" handleId="default" handleKind="source" label="value" />
    </NodeCard>
  );
}

export function EndNode({ id, data, selected }: NodeProps) {
  const flowIn = pinProps('end', 'default', 'target', 'nodo anterior');
  return (
    <NodeCard type="end" icon="■" title="Final" selected={selected}>
      <MergeBadge id={id} />
      <div style={{ color: 'var(--acm-fg-4)' }}>{String(data.template || '')}</div>
      <Handle type="target" position={Position.Top} id="default" style={flowIn.style} title={flowIn.title} />
    </NodeCard>
  );
}

export const NODE_TYPES = {
  start: StartNode,
  http: HttpNode,
  conditional: ConditionalNode,
  loop: LoopNode,
  woocommerce: WooCommerceNode,
  set: SetNode,
  get: GetNode,
  end: EndNode,
};
