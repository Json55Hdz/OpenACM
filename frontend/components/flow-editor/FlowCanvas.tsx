'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  ReactFlow, ReactFlowProvider, useReactFlow, Background, Controls, MiniMap, Panel, addEdge, applyNodeChanges, applyEdgeChanges,
  type Node, type Edge, type Connection, type NodeChange, type EdgeChange,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { NODE_TYPES, NODE_CATEGORY, CATEGORY_COLORS, classifyPin } from './node-types';
import type { AgentFlow } from '@/hooks/use-agent-flows';
import { useAgentConnections, useCreateConnection } from '@/hooks/use-agent-connections';
import { useAgentFlowSkill, useSaveFlowSkill, useGenerateFlowSkill } from '@/hooks/use-agent-flow-skill';
import { useAPI } from '@/hooks/use-api';
import { Trash2 } from 'lucide-react';
import { InspectorSection } from './InspectorSection';
import { FlowChatPanel } from './FlowChatPanel';
import { FlowTestPanel } from './FlowTestPanel';

interface StartParam {
  name: string;
  type: 'string' | 'number' | 'boolean';
  description: string;
  required: boolean;
}

interface GraphJson {
  nodes: Array<{ id: string; type: string; config: Record<string, unknown>; position: { x: number; y: number } }>;
  edges: Array<{ from: string; to: string; fromHandle: string; toHandle: string; kind: 'flow' | 'data' }>;
}

function toReactFlow(graph: GraphJson): { nodes: Node[]; edges: Edge[] } {
  return {
    nodes: graph.nodes.map(n => ({ id: n.id, type: n.type, position: n.position, data: n.config || {} })),
    edges: graph.edges.map(e => ({
      id: `${e.from}-${e.to}-${e.fromHandle}-${e.toHandle || 'default'}`,
      source: e.from,
      target: e.to,
      sourceHandle: e.fromHandle,
      // `targetHandle` must be a real DOM Handle id that exists on the
      // target node. Every node's flow-in target handle is `id="default"`
      // (see node-types.tsx — Start/HTTP/Conditional/WooCommerce/End/Set
      // all use "default" for their flow-in pin; none has an id="flow"
      // handle anywhere). An edge saved before this task shipped has no
      // `toHandle` key at all, so it must fall back to "default" here, not
      // to the string "flow" — "flow" is only a `kind` value (this
      // graph_json shape's edge-category label), never a handle id. Getting
      // this wrong makes React Flow's handle-position lookup fail and the
      // edge silently render as nothing, even though the underlying
      // to/from data is intact.
      targetHandle: e.toHandle || 'default',
      // React Flow's Edge type has no first-class "kind" field — stash it
      // in `data` so it survives every state update (applyEdgeChanges,
      // copy/paste, etc.) and toGraphJson can read it back out on save.
      // An edge with no kind saved before this shipped defaults to "flow",
      // matching flow_executor.py's `edge.get("kind", "flow") == "data"`
      // check. (Backend has no equivalent default for toHandle on flow
      // edges — it never reads `toHandle` at all for a non-data edge, see
      // flow_executor.py's `run()`, so there is nothing to "match" there;
      // "default" above is purely a frontend concern, driven by React
      // Flow's own Handle ids.)
      data: { kind: (e.kind || 'flow') as 'flow' | 'data' },
    })),
  };
}

function toGraphJson(nodes: Node[], edges: Edge[]): GraphJson {
  return {
    nodes: nodes.map(n => ({ id: n.id, type: n.type || 'http', config: n.data as Record<string, unknown>, position: n.position })),
    edges: edges.map(e => ({
      from: e.source,
      to: e.target,
      fromHandle: e.sourceHandle || 'default',
      // Mirrors toReactFlow's fallback: "default" is the real DOM handle
      // id every node's flow-in pin uses, so that's what gets written back
      // out when `targetHandle` is somehow unset. The backend ignores
      // `toHandle` entirely for flow-kind edges either way (flow_executor.py
      // only reads it when kind == "data"), so this value is inert to
      // execution — it just needs to stay truthful to what's on screen.
      toHandle: e.targetHandle || 'default',
      kind: ((e.data as { kind?: 'flow' | 'data' } | undefined)?.kind) || 'flow',
    })),
  };
}

// Mirrors flow_executor.py's _stringify_whole_value: a dict-shaped value
// that exposes a "result" key (today, only WooCommerce's structured
// output) stringifies to that key's value specifically, instead of
// "[object Object]" — a narrow, explicit special case, not a general
// change to whole-value stringification for every dict-shaped value.
function stringifyWholeValue(value: unknown): string {
  if (value && typeof value === 'object' && 'result' in (value as Record<string, unknown>)) {
    return String((value as Record<string, unknown>).result);
  }
  return String(value);
}

// Walks a dotted/bracketed path (e.g. ".current_condition[0].temp_C") into
// `value`, one segment at a time — mirrors flow_executor.py's
// _walk_template_path exactly: a ".field" segment must land on a plain
// object with that key (arrays excluded, matching Python's isinstance(...,
// dict)); a "[N]" segment must land on an array with that index.
function walkTemplatePath(value: unknown, path: string): { found: boolean; value: unknown } {
  const segments = path.match(/\.[a-zA-Z0-9_]+|\[\d+\]/g) || [];
  for (const seg of segments) {
    if (seg.startsWith('.')) {
      const field = seg.slice(1);
      if (value === null || typeof value !== 'object' || Array.isArray(value) || !(field in (value as Record<string, unknown>))) {
        return { found: false, value: undefined };
      }
      value = (value as Record<string, unknown>)[field];
    } else {
      const idx = Number(seg.slice(1, -1));
      if (!Array.isArray(value) || idx < 0 || idx >= value.length) {
        return { found: false, value: undefined };
      }
      value = value[idx];
    }
  }
  return { found: true, value };
}

interface PathEntry { path: string; preview: string }

function truncatePreview(value: unknown, max = 40): string {
  const s = typeof value === 'string' ? value : JSON.stringify(value);
  return s.length > max ? `${s.slice(0, max)}…` : s;
}

// Walks a real testOutputs[ancestorId] value and enumerates every LEAF
// reachable via a dotted/bracketed path — mirroring exactly the path shape
// flow_executor.py's substitute_templates resolves (".field" for a dict
// key, "[N]" for a list index), so every entry this produces is guaranteed
// to resolve correctly once inserted as {{ancestorId<path>}}. `path` is
// empty string for a non-nested (scalar) value at the top level; every
// nested entry's `path` starts with "." or "[" ready to concatenate
// directly after the ancestor id. Capped at depth 6 / 60 total entries (a
// real API response can nest arbitrarily) — the cap appends one final
// "…" entry rather than silently dropping the rest.
function enumeratePaths(value: unknown, basePath: string, depth = 0, budget = { count: 0 }): PathEntry[] {
  const MAX_DEPTH = 6;
  const MAX_ENTRIES = 60;
  if (depth >= MAX_DEPTH || value === null || typeof value !== 'object') {
    budget.count += 1;
    return [{ path: basePath, preview: truncatePreview(value) }];
  }
  const entries: PathEntry[] = [];
  if (Array.isArray(value)) {
    for (let i = 0; i < value.length; i++) {
      if (budget.count >= MAX_ENTRIES) { entries.push({ path: `${basePath}[…]`, preview: '' }); break; }
      entries.push(...enumeratePaths(value[i], `${basePath}[${i}]`, depth + 1, budget));
    }
  } else {
    for (const key of Object.keys(value as Record<string, unknown>)) {
      if (budget.count >= MAX_ENTRIES) { entries.push({ path: `${basePath}.…`, preview: '' }); break; }
      entries.push(...enumeratePaths((value as Record<string, unknown>)[key], `${basePath}.${key}`, depth + 1, budget));
    }
  }
  return entries;
}

// Local re-implementation of flow_executor.py's substitute_templates rule
// (bare {{name}} whole-value — params checked BEFORE outputs, matching
// substitute_templates(template, params, outputs) in flow_executor.py,
// since Start parameters are never written into the outputs dict returned
// by /test — it's keyed by node id and Set-node names only;
// {{node_id<path>}} walks any number of ".field"/"[N]" hops against
// outputs via walkTemplatePath; "[missing: ...]" marker) so the Inspector
// can preview a resolved value without a network round-trip per keystroke.
function previewTemplate(template: string, params: Record<string, string>, outputs: Record<string, unknown>): string {
  return template.replace(/\{\{([a-zA-Z0-9_]+)((?:\.[a-zA-Z0-9_]+|\[\d+\])*)\}\}/g, (_match, name, path) => {
    if (!path) {
      if (name in params) return String(params[name]);
      if (name in outputs) return stringifyWholeValue(outputs[name]);
      return `[missing: ${name}]`;
    }
    if (!(name in outputs)) return `[missing: ${name}${path}]`;
    const { found, value } = walkTemplatePath(outputs[name], path);
    if (!found) return `[missing: ${name}${path}]`;
    return String(value);
  });
}

function TemplatePreview({ value, params, outputs }: { value: string; params: Record<string, string>; outputs: Record<string, unknown> | null }) {
  if (!outputs) {
    return <div className="text-[9px] mt-1" style={{ color: 'var(--acm-fg-4)' }}>corré &quot;Probar flujo&quot; para ver valores reales acá</div>;
  }
  if (!value.includes('{{')) return null;
  return <div className="text-[9px] mt-1 p-1" style={{ background: 'var(--acm-base)', borderRadius: 4, color: 'var(--acm-fg-3)' }}>{previewTemplate(value, params, outputs)}</div>;
}

// Shared connected/disconnected rendering for a single wire-or-literal
// Inspector field (HTTP url/body — this task; Conditional field/value and
// WooCommerce search_term reuse this exact component unchanged in later
// tasks). A `kind: "data"` edge whose `targetHandle` matches `fieldName`
// and whose `target` matches `nodeId` hides the literal input (`children`)
// and shows a small chip with a disconnect action instead; with no such
// edge, `children` renders exactly as it did before this feature.
function ConnectableField({ nodeId, fieldName, edges, setEdges, children }: {
  nodeId: string;
  fieldName: string;
  edges: Edge[];
  setEdges: React.Dispatch<React.SetStateAction<Edge[]>>;
  children: React.ReactNode;
}) {
  const dataEdge = edges.find(e =>
    e.target === nodeId &&
    e.targetHandle === fieldName &&
    (e.data as { kind?: string } | undefined)?.kind === 'data'
  );
  if (!dataEdge) return <>{children}</>;
  const sourceLabel = dataEdge.sourceHandle && dataEdge.sourceHandle !== 'default'
    ? `${dataEdge.source}.${dataEdge.sourceHandle}`
    : dataEdge.source;
  return (
    <div className="flex items-center gap-1 mb-1 p-1" style={{ background: 'var(--acm-base)', border: '1px solid var(--acm-node-data)', borderRadius: 4 }}>
      <span className="text-[10px] flex-1" style={{ color: 'var(--acm-fg-3)' }}>
        🔌 conectado a {'{{'}{sourceLabel}{'}}'}
      </span>
      <button
        className="text-[var(--acm-fg-4)] hover:text-[var(--acm-err)]"
        onClick={() => setEdges(eds => eds.filter(e => e.id !== dataEdge.id))}
        title="Desconectar"
      >
        <Trash2 size={11} />
      </button>
    </div>
  );
}

// Node ids look like "prefix_N" (matching the template-substitution regex's
// [a-zA-Z0-9_]+ charset, so a UUID with hyphens is not an option here).
// The counter is seeded per-flow from the highest existing suffix already
// in that flow's graph, rather than a module-level counter that resets to
// 0 on every reload — otherwise reopening a saved flow and adding a node
// could regenerate an id already used by an existing node, silently
// dropping one of them when FlowExecutor keys nodes by id.
function maxNodeIdSuffix(nodes: Node[]): number {
  let max = 0;
  for (const n of nodes) {
    const match = /_(\d+)$/.exec(n.id);
    if (match) max = Math.max(max, parseInt(match[1], 10));
  }
  return max;
}

interface VariableSource { id: string; label: string }

// Every ancestor reachable via any incoming edge (flow or data — see the
// walk below, unchanged from the function this replaces), surfaced as an
// insertable source: its own raw node id (e.g. "weather", "http1") always,
// PLUS a Set node's custom alias name (its config.name) if it has one — a
// Set node is reachable under BOTH its id and its friendly name, since
// flow_executor.py's Set-node branch writes the value under both keys in
// `outputs`. Get nodes contribute no separate alias: referencing a Get
// node's own id resolves to whatever it aliased, exactly like any other
// node's id would.
function availableVariableSources(nodes: Node[], edges: Edge[], selectedNodeId: string): VariableSource[] {
  const incomingBySource: Record<string, string[]> = {};
  for (const e of edges) {
    (incomingBySource[e.target] ||= []).push(e.source);
  }
  const seen = new Set<string>();
  const sources: VariableSource[] = [];
  const visited = new Set<string>();
  const queue: string[] = [...(incomingBySource[selectedNodeId] || [])];
  while (queue.length > 0) {
    const currentId = queue.shift()!;
    if (visited.has(currentId)) continue;
    visited.add(currentId);
    const node = nodes.find(n => n.id === currentId);
    if (node && !seen.has(node.id)) {
      seen.add(node.id);
      sources.push({ id: node.id, label: node.id });
    }
    const setName = node?.type === 'set' ? (node.data.name as string | undefined) : undefined;
    if (setName && !seen.has(setName)) {
      seen.add(setName);
      sources.push({ id: setName, label: setName });
    }
    queue.push(...(incomingBySource[currentId] || []));
  }
  return sources;
}

function VariablePicker({ nodeId, nodes, edges, targetRef, value, onInsert, outputs }: {
  nodeId: string;
  nodes: Node[];
  edges: Edge[];
  targetRef: React.RefObject<HTMLInputElement | HTMLTextAreaElement | null>;
  value: string;
  onInsert: (newValue: string) => void;
  outputs: Record<string, unknown> | null;
}) {
  const sources = availableVariableSources(nodes, edges, nodeId);
  if (sources.length === 0) return null;

  const insert = (fullRef: string) => {
    const insertText = `{{${fullRef}}}`;
    const el = targetRef.current;
    const start = el?.selectionStart ?? value.length;
    const end = el?.selectionEnd ?? value.length;
    onInsert(value.slice(0, start) + insertText + value.slice(end));
  };

  return (
    <select
      className="acm-input w-full mb-1 text-[10px]"
      value=""
      onChange={e => { if (e.target.value) insert(e.target.value); }}
    >
      <option value="">Insertar variable...</option>
      {sources.map(source => {
        const val = outputs?.[source.id];
        const expandable = val !== null && val !== undefined && typeof val === 'object';
        if (!expandable) {
          return <option key={source.id} value={source.id}>{source.label}</option>;
        }
        const paths = enumeratePaths(val, '');
        return (
          <optgroup key={source.id} label={source.label}>
            <option value={source.id}>{source.label} (todo el valor)</option>
            {paths.map(p => (
              <option key={`${source.id}${p.path}`} value={`${source.id}${p.path}`} disabled={p.path.endsWith('…')}>
                {p.path || '(valor)'} → {p.preview}
              </option>
            ))}
          </optgroup>
        );
      })}
    </select>
  );
}

const NODE_CATEGORIES: Array<{ label: string; types: Array<keyof typeof NODE_TYPES> }> = [
  { label: 'FLUJO', types: ['start', 'end'] },
  { label: 'LÓGICA', types: ['conditional'] },
  { label: 'INTEGRACIONES', types: ['http', 'woocommerce'] },
  { label: 'DATOS', types: ['set', 'get'] },
];

const NODE_LABELS: Record<keyof typeof NODE_TYPES, string> = {
  start: '▶ Inicio', end: '■ Final', conditional: '◆ Condicional',
  http: '🌐 HTTP Request', woocommerce: '🛒 WooCommerce', set: '💾 Guardar (Set)', get: '📤 Obtener (Get)',
};

function FlowCanvasInner({ agentId, flow, onSave }: { agentId: number; flow: AgentFlow; onSave: (graphJson: string) => void }) {
  const initial = useMemo(() => toReactFlow(JSON.parse(flow.graph_json || '{"nodes":[],"edges":[]}')), [flow.id]);
  const [nodes, setNodes] = useState<Node[]>(initial.nodes);
  const [edges, setEdges] = useState<Edge[]>(initial.edges);

  // Re-sync nodes/edges when the flow's server-side content changes out from
  // under this mounted instance (e.g. the AI edits it via FlowChatPanel, or a
  // normal "Guardar flujo" save round-trips through react-query) — without
  // remounting the whole component, which would also discard unrelated local
  // UI state (the open chat panel, the ReactFlow viewport, the selected
  // node's Inspector, "Probar flujo" results, an in-progress "+ Skill" edit).
  // Keyed on the actual graph content, not a timestamp, so it's immune to
  // same-second update collisions and fires exactly when there's a real
  // change to show.
  const lastSyncedGraphJson = useRef(flow.graph_json);
  useEffect(() => {
    if (flow.graph_json === lastSyncedGraphJson.current) return;
    lastSyncedGraphJson.current = flow.graph_json;
    const fresh = toReactFlow(JSON.parse(flow.graph_json || '{"nodes":[],"edges":[]}'));
    setNodes(fresh.nodes);
    setEdges(fresh.edges);
  }, [flow.graph_json]);

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const nodeIdCounterRef = useRef(maxNodeIdSuffix(initial.nodes));
  const variableNameCounterRef = useRef(0);
  const { screenToFlowPosition } = useReactFlow();
  const canvasWrapperRef = useRef<HTMLDivElement>(null);
  const [contextMenu, setContextMenu] = useState<{ x: number; y: number; flowX: number; flowY: number } | null>(null);
  const [contextMenuSearch, setContextMenuSearch] = useState('');
  const [variableDropMenu, setVariableDropMenu] = useState<{ x: number; y: number; flowX: number; flowY: number; name: string } | null>(null);
  const urlInputRef = useRef<HTMLInputElement>(null);
  const bodyInputRef = useRef<HTMLTextAreaElement>(null);
  const conditionalFieldRef = useRef<HTMLInputElement>(null);
  const searchTermRef = useRef<HTMLInputElement>(null);
  const templateRef = useRef<HTMLTextAreaElement>(null);

  const { data: connections } = useAgentConnections(agentId);
  const createConnection = useCreateConnection(agentId);
  const [showNewConnectionForm, setShowNewConnectionForm] = useState(false);
  const [newConnName, setNewConnName] = useState('');
  const [newConnUrl, setNewConnUrl] = useState('');
  const [newConnKey, setNewConnKey] = useState('');
  const [newConnSecret, setNewConnSecret] = useState('');

  const submitNewConnection = () => {
    createConnection.mutate(
      { name: newConnName, type: 'woocommerce', url: newConnUrl, consumer_key: newConnKey, consumer_secret: newConnSecret },
      { onSuccess: () => { setShowNewConnectionForm(false); setNewConnName(''); setNewConnUrl(''); setNewConnKey(''); setNewConnSecret(''); } },
    );
  };

  const { data: flowSkill } = useAgentFlowSkill(agentId, flow.id);
  const saveFlowSkill = useSaveFlowSkill(agentId, flow.id);
  const generateFlowSkill = useGenerateFlowSkill(agentId, flow.id);
  const [showSkillPanel, setShowSkillPanel] = useState(false);
  const [showChatPanel, setShowChatPanel] = useState(false);
  const [showTestPanel, setShowTestPanel] = useState(false);
  const [skillName, setSkillName] = useState(flowSkill?.name || flow.name);
  const [skillContent, setSkillContent] = useState(flowSkill?.content || '');
  const [skillError, setSkillError] = useState<string | null>(null);

  const [testParams, setTestParams] = useState<Record<string, string>>({});
  const [testResult, setTestResult] = useState<string | null>(null);
  const [testOutputs, setTestOutputs] = useState<Record<string, unknown> | null>(null);
  const [testError, setTestError] = useState(false);
  const [testing, setTesting] = useState(false);
  const { fetchAPI } = useAPI();

  const startNode = nodes.find(n => n.type === 'start');
  const startParams = (startNode?.data.parameters as Array<{ name: string }> | undefined) || [];

  const runTest = async () => {
    setTesting(true);
    setTestResult(null);
    setTestOutputs(null);
    setTestError(false);
    try {
      // Test the graph as it currently stands in the canvas, not whatever
      // was last saved — saving before every test run was real friction.
      const currentGraph = JSON.stringify(toGraphJson(nodes, edges));
      const res = (await fetchAPI(`/api/agents/${agentId}/flows/${flow.id}/test`, {
        method: 'POST',
        body: JSON.stringify({ params: testParams, graph_json: currentGraph }),
      })) as { result: string; outputs: Record<string, unknown>; error: boolean };
      setTestResult(res.result);
      setTestOutputs(res.outputs);
      setTestError(res.error);
    } catch (e) {
      const detail = e instanceof Error ? e.message : 'Error al ejecutar la prueba.';
      setTestResult(detail);
      setTestError(true);
    } finally {
      setTesting(false);
    }
  };

  const nextNodeId = (prefix: string) => {
    nodeIdCounterRef.current += 1;
    return `${prefix}_${nodeIdCounterRef.current}`;
  };

  const clipboardRef = useRef<{ nodes: Node[]; edges: Edge[] } | null>(null);
  // How many times the CURRENT clipboard contents have been pasted, so
  // repeated Ctrl+V without a new Ctrl+C staggers each paste instead of
  // stacking every copy on the exact same position.
  const pasteCountRef = useRef(0);

  const onCanvasCopy = useCallback(() => {
    // Start/End are singleton per flow, so they're silently excluded from
    // the copy rather than blocking the whole selection or duplicating them.
    const selectedNodes = nodes.filter(n => n.selected && n.type !== 'start' && n.type !== 'end');
    if (selectedNodes.length === 0) return;
    const selectedIds = new Set(selectedNodes.map(n => n.id));
    // Only edges between two copied nodes survive — an edge to a node
    // outside the selection would dangle once pasted as a fresh copy.
    const internalEdges = edges.filter(e => selectedIds.has(e.source) && selectedIds.has(e.target));
    clipboardRef.current = { nodes: selectedNodes, edges: internalEdges };
    pasteCountRef.current = 0;
  }, [nodes, edges]);

  const onCanvasPaste = useCallback(() => {
    const clip = clipboardRef.current;
    if (!clip || clip.nodes.length === 0) return;

    pasteCountRef.current += 1;
    const offset = pasteCountRef.current * 40;

    const idMap: Record<string, string> = {};
    const pastedNodes: Node[] = clip.nodes.map(n => {
      const newId = nextNodeId((n.type || 'http') as string);
      idMap[n.id] = newId;
      return { ...n, id: newId, selected: false, position: { x: n.position.x + offset, y: n.position.y + offset } };
    });
    const pastedEdges: Edge[] = clip.edges.map(e => ({
      id: `${idMap[e.source]}-${idMap[e.target]}-${e.sourceHandle || 'default'}-${e.targetHandle || 'default'}`,
      source: idMap[e.source],
      target: idMap[e.target],
      sourceHandle: e.sourceHandle,
      targetHandle: e.targetHandle,
      data: e.data,
    }));

    setNodes(nds => [...nds, ...pastedNodes]);
    setEdges(eds => [...eds, ...pastedEdges]);
  }, [nodeIdCounterRef]);

  const onCanvasKeyDown = useCallback((event: React.KeyboardEvent) => {
    // Don't hijack Ctrl+C/Ctrl+V while the user is typing in a text field
    // (e.g. the right-click node-search input, which auto-focuses) — let
    // the native input handle copy/paste of its own text instead of also
    // triggering node clipboard actions as a side effect.
    const target = event.target as HTMLElement;
    if (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable) return;
    const isMeta = event.ctrlKey || event.metaKey;
    if (!isMeta) return;
    if (event.key === 'c' || event.key === 'C') {
      onCanvasCopy();
    } else if (event.key === 'v' || event.key === 'V') {
      onCanvasPaste();
    }
  }, [onCanvasCopy, onCanvasPaste]);

  const variableNames = useMemo(() => {
    const names = new Set<string>();
    for (const n of nodes) {
      if ((n.type === 'set' || n.type === 'get') && typeof n.data.name === 'string' && n.data.name) {
        names.add(n.data.name);
      }
    }
    return Array.from(names).sort();
  }, [nodes]);

  const onNodesChange = useCallback((changes: NodeChange[]) => setNodes(nds => applyNodeChanges(changes, nds)), []);
  const onEdgesChange = useCallback((changes: EdgeChange[]) => setEdges(eds => applyEdgeChanges(changes, eds)), []);
  const onConnect = useCallback((connection: Connection) => {
    // A data edge always targets a NAMED field/value handle (e.g. "url",
    // "value", "search_term") — every node's flow-in handle is always id
    // "default", so that's the one signal available at connect-time to
    // tell a flow edge from a data edge without a node-type lookup here.
    const kind: 'flow' | 'data' = connection.targetHandle && connection.targetHandle !== 'default' ? 'data' : 'flow';
    setEdges(eds => addEdge({ ...connection, data: { kind } }, eds));
  }, []);

  const addNodeAt = (type: keyof typeof NODE_TYPES, x: number, y: number) => {
    const defaults: Record<string, Record<string, unknown>> = {
      start: { parameters: [] },
      http: { url: '', method: 'GET', headers: {}, body: '' },
      conditional: { field: '', operator: 'contains', value: '' },
      woocommerce: { connection_id: null, search_term: '' },
      set: { name: '' },
      get: { name: '' },
      end: { template: '' },
    };
    setNodes(nds => [...nds, { id: nextNodeId(type), type, position: { x, y }, data: defaults[type] }]);
  };

  const addNewVariable = () => {
    variableNameCounterRef.current += 1;
    const name = `variable_${variableNameCounterRef.current}`;
    const x = 100;
    const y = 100 + nodes.length * 90;
    setNodes(nds => [...nds, { id: nextNodeId('set'), type: 'set', position: { x, y }, data: { name } }]);
  };

  const onConnectEnd = useCallback((event: MouseEvent | TouchEvent, connectionState: { isValid: boolean | null; fromNode: Node | null; fromHandle: { id?: string | null } | null; toHandle: { id?: string | null } | null }) => {
    // Only promote when the drag truly ended on empty canvas. `isValid`
    // alone doesn't distinguish that from "released near a real but
    // incompatible handle" (e.g. overshooting between the Conditional
    // node's adjacent true/false output handles) — in that case toHandle
    // is non-null even though isValid is false, and this must NOT create
    // a spurious Set node.
    if (connectionState.isValid || !connectionState.fromNode || connectionState.toHandle) return;
    const bounds = canvasWrapperRef.current?.getBoundingClientRect();
    if (!bounds) return;
    const point = 'changedTouches' in event ? event.changedTouches[0] : event;
    const flowPosition = screenToFlowPosition({ x: point.clientX, y: point.clientY });

    variableNameCounterRef.current += 1;
    const name = `variable_${variableNameCounterRef.current}`;
    const newId = nextNodeId('set');
    const fromNodeId = connectionState.fromNode!.id;
    const fromHandleId = connectionState.fromHandle?.id || 'default';
    // The drag might have started from a data-out pin (WooCommerce's
    // `result`/`count`, or a Get node's only handle) rather than a flow-out
    // pin — classify it so the promoted edge matches what was actually
    // dragged, instead of always assuming a flow-out drag.
    const pinKind = classifyPin(connectionState.fromNode!.type, fromHandleId, 'source');

    setNodes(nds => [...nds, { id: newId, type: 'set', position: flowPosition, data: { name } }]);
    setEdges(eds => [...eds, pinKind === 'data' ? {
      id: `${fromNodeId}-${newId}-${fromHandleId}-data`,
      source: fromNodeId,
      target: newId,
      sourceHandle: fromHandleId,
      // Dragging a data pin to empty canvas means "save this value" — wire
      // it into the new Set node's data-input "value" handle, not its
      // flow-in "default" handle.
      targetHandle: 'value',
      data: { kind: 'data' },
    } : {
      id: `${fromNodeId}-${newId}-${fromHandleId}-flow`,
      source: fromNodeId,
      target: newId,
      sourceHandle: fromHandleId,
      // A flow edge — dragging a flow-out handle to empty canvas promotes a
      // new Set node into the CHAIN (its flow-in "default" handle).
      targetHandle: 'default',
      data: { kind: 'flow' },
    }]);
  }, [screenToFlowPosition]);

  // Rejects a connection wiring a data-output pin (e.g. WooCommerce's
  // `result`) directly into a flow-in handle (`targetHandle === 'default'`)
  // — that edge would look like a normal connection on the canvas but
  // FlowExecutor.run()'s flow-walk never follows it (it only walks a
  // node's 'default' source-side flow-out edge), so the flow would
  // silently end early with "flow ended without reaching an End node".
  const isValidConnection = useCallback((connection: Edge | Connection) => {
    const targetHandle = connection.targetHandle || 'default';
    if (targetHandle !== 'default') return true;
    const sourceNode = nodes.find(n => n.id === connection.source);
    if (!sourceNode) return true;
    const sourcePinKind = classifyPin(sourceNode.type, connection.sourceHandle, 'source');
    return sourcePinKind !== 'data';
  }, [nodes]);

  const onPaneContextMenu = useCallback((event: React.MouseEvent | MouseEvent) => {
    event.preventDefault();
    const bounds = canvasWrapperRef.current?.getBoundingClientRect();
    if (!bounds) return;
    const flowPosition = screenToFlowPosition({ x: (event as MouseEvent).clientX, y: (event as MouseEvent).clientY });
    setContextMenu({
      x: (event as MouseEvent).clientX - bounds.left,
      y: (event as MouseEvent).clientY - bounds.top,
      flowX: flowPosition.x,
      flowY: flowPosition.y,
    });
    setContextMenuSearch('');
  }, [screenToFlowPosition]);

  const onCanvasDragOver = useCallback((event: React.DragEvent) => {
    if (event.dataTransfer.types.includes('application/flow-variable-name')) {
      event.preventDefault();
    }
  }, []);

  const onCanvasDrop = useCallback((event: React.DragEvent) => {
    const name = event.dataTransfer.getData('application/flow-variable-name');
    if (!name) return;
    event.preventDefault();
    const bounds = canvasWrapperRef.current?.getBoundingClientRect();
    if (!bounds) return;
    const flowPosition = screenToFlowPosition({ x: event.clientX, y: event.clientY });
    setVariableDropMenu({
      x: event.clientX - bounds.left,
      y: event.clientY - bounds.top,
      flowX: flowPosition.x,
      flowY: flowPosition.y,
      name,
    });
  }, [screenToFlowPosition]);

  const selectedNode = nodes.find(n => n.id === selectedId) || null;

  const updateSelectedNodeData = (patch: Record<string, unknown>) => {
    if (!selectedNode) return;
    setNodes(nds => nds.map(n => n.id === selectedNode.id ? { ...n, data: { ...n.data, ...patch } } : n));
  };

  const startParamsOf = (node: Node): StartParam[] => (node.data.parameters as StartParam[] | undefined) || [];

  const addStartParam = () => {
    if (!selectedNode) return;
    const next = [...startParamsOf(selectedNode), { name: '', type: 'string' as const, description: '', required: true }];
    updateSelectedNodeData({ parameters: next });
  };

  const updateStartParam = (index: number, patch: Partial<StartParam>) => {
    if (!selectedNode) return;
    const next = startParamsOf(selectedNode).map((p, i) => i === index ? { ...p, ...patch } : p);
    updateSelectedNodeData({ parameters: next });
  };

  const removeStartParam = (index: number) => {
    if (!selectedNode) return;
    const next = startParamsOf(selectedNode).filter((_, i) => i !== index);
    updateSelectedNodeData({ parameters: next });
  };

  const handleSave = () => onSave(JSON.stringify(toGraphJson(nodes, edges)));

  const handleExport = () => {
    const payload = {
      kind: 'openacm-flow',
      version: 1,
      name: flow.name,
      description: flow.description,
      graph_json: toGraphJson(nodes, edges),
    };
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    const slug = flow.name.toLowerCase().trim().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '') || 'flujo';
    a.href = url;
    a.download = `${slug}.json`;
    a.click();
    // Revoke on the next tick, not synchronously: outside Chrome the
    // download may not have started reading the blob yet when click()
    // returns, and revoking first makes the download silently fail.
    setTimeout(() => URL.revokeObjectURL(url), 0);
  };

  return (
    <div className="flex gap-2" style={{ height: 500 }}>
      <div className="flex flex-col gap-1 shrink-0" style={{ width: 120 }}>
        <div className="text-[10px]" style={{ color: 'var(--acm-fg-4)' }}>Clic derecho en el lienzo para agregar un nodo</div>
        <button onClick={handleSave} className="btn-primary text-[11px] px-2 py-1 mt-2">Guardar flujo</button>
        <button onClick={handleExport} className="btn-secondary text-[11px] px-2 py-1 mt-1">Exportar</button>
        <button onClick={() => { setSkillName(flowSkill?.name || flow.name); setSkillContent(flowSkill?.content || ''); setSkillError(null); setShowSkillPanel(true); }} className="btn-secondary text-[11px] px-2 py-1 mt-1">
          {flowSkill ? 'Editar skill' : '+ Skill'}
        </button>
        <button onClick={() => setShowChatPanel(v => !v)} className="btn-secondary text-[11px] px-2 py-1 mt-1">
          💬 Chat con IA
        </button>
        <button onClick={() => setShowTestPanel(v => !v)} className="btn-secondary text-[11px] px-2 py-1 mt-1">
          ▶ Probar flujo
        </button>
        <div className="mt-2 pt-2" style={{ borderTop: '1px solid var(--acm-border)' }}>
          <div className="label text-[var(--acm-fg-4)] mb-1">Variables</div>
          {variableNames.length === 0 ? (
            <div className="text-[10px] mb-1" style={{ color: 'var(--acm-fg-4)' }}>Ninguna todavía</div>
          ) : (
            variableNames.map(name => (
              <div
                key={name}
                draggable
                onDragStart={e => e.dataTransfer.setData('application/flow-variable-name', name)}
                className="text-[11px] px-2 py-1 mb-1 rounded"
                style={{ background: 'var(--acm-elev)', border: '1px solid var(--acm-node-data)', color: 'var(--acm-fg-2)', cursor: 'grab' }}
              >
                {name}
              </div>
            ))
          )}
          <button onClick={addNewVariable} className="btn-secondary w-full text-[11px] px-2 py-1">+ Nueva variable</button>
        </div>
      </div>
      {showChatPanel && <FlowChatPanel agentId={agentId} flow={flow} />}
      {showTestPanel && (
        <FlowTestPanel
          startParams={startParams}
          testParams={testParams}
          onParamChange={(name, value) => setTestParams(prev => ({ ...prev, [name]: value }))}
          onRun={runTest}
          testing={testing}
          result={testResult}
          outputs={testOutputs}
          error={testError}
        />
      )}
      <div
        ref={canvasWrapperRef}
        className="flex-1 relative"
        style={{ border: '1px solid var(--acm-border)', borderRadius: 8 }}
        onDragOver={onCanvasDragOver}
        onDrop={onCanvasDrop}
        onKeyDown={onCanvasKeyDown}
        tabIndex={0}
      >
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onConnect={onConnect}
          onConnectEnd={onConnectEnd}
          isValidConnection={isValidConnection}
          onNodeClick={(_e, node) => setSelectedId(node.id)}
          onPaneClick={() => { setSelectedId(null); setContextMenu(null); setVariableDropMenu(null); }}
          onPaneContextMenu={onPaneContextMenu}
          nodeTypes={NODE_TYPES}
          fitView
          colorMode="dark"
        >
          <Background />
          <Controls />
          <MiniMap
            bgColor="var(--acm-elev)"
            maskColor="oklch(0.155 0.006 255 / 0.7)"
            maskStrokeColor="var(--acm-accent)"
            nodeColor={(n) => CATEGORY_COLORS[NODE_CATEGORY[n.type ?? ''] ?? 'flow']}
            nodeStrokeColor="var(--acm-base)"
            style={{ background: 'var(--acm-elev)', border: '1px solid var(--acm-border)', borderRadius: 8 }}
          />
          {/* Unreal-style pin legend — reuses the same CATEGORY_COLORS.flow /
              CATEGORY_COLORS.data tokens the pins themselves are drawn in
              (see node-types.tsx's pinProps), so the legend can never drift
              out of sync with what a pin actually looks like. */}
          <Panel position="top-right" style={{
            background: 'var(--acm-elev)', border: '1px solid var(--acm-border)', borderRadius: 8,
            padding: '6px 10px', display: 'flex', gap: 12, alignItems: 'center', fontSize: 11, color: 'var(--acm-fg-4)',
          }}>
            <span style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
              <span style={{
                width: 9, height: 9, background: CATEGORY_COLORS.flow, borderRadius: 2,
                clipPath: 'polygon(50% 0%, 100% 50%, 50% 100%, 0% 50%)',
              }} />
              flujo
            </span>
            <span style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
              <span style={{ width: 8, height: 8, background: CATEGORY_COLORS.data, borderRadius: '50%' }} />
              dato
            </span>
          </Panel>
        </ReactFlow>
        {contextMenu && (
          <div
            className="absolute z-50 p-2"
            style={{ left: contextMenu.x, top: contextMenu.y, background: 'var(--acm-elev)', border: '1px solid var(--acm-border)', borderRadius: 8, width: 200, maxHeight: 320, overflowY: 'auto' }}
          >
            <input
              autoFocus
              className="acm-input w-full mb-2 text-[11px]"
              placeholder="Buscar nodo..."
              value={contextMenuSearch}
              onChange={e => setContextMenuSearch(e.target.value)}
              onKeyDown={e => { if (e.key === 'Escape') setContextMenu(null); }}
            />
            {NODE_CATEGORIES.map(cat => {
              const filteredTypes = cat.types.filter(t => NODE_LABELS[t].toLowerCase().includes(contextMenuSearch.toLowerCase()));
              if (filteredTypes.length === 0) return null;
              return (
                <div key={cat.label} className="mb-1">
                  <div className="label text-[var(--acm-fg-4)] mb-1">{cat.label}</div>
                  {filteredTypes.map(t => (
                    <button
                      key={t}
                      className="btn-secondary w-full text-left text-[11px] px-2 py-1 mb-1"
                      style={{ borderColor: CATEGORY_COLORS[NODE_CATEGORY[t]] }}
                      onClick={() => { addNodeAt(t, contextMenu.flowX, contextMenu.flowY); setContextMenu(null); }}
                    >
                      {NODE_LABELS[t]}
                    </button>
                  ))}
                </div>
              );
            })}
          </div>
        )}
        {variableDropMenu && (
          <div
            className="absolute z-50 p-2 flex flex-col gap-1"
            style={{ left: variableDropMenu.x, top: variableDropMenu.y, background: 'var(--acm-elev)', border: '1px solid var(--acm-border)', borderRadius: 8, width: 160 }}
          >
            <div className="text-[10px] mb-1" style={{ color: 'var(--acm-fg-4)' }}>{variableDropMenu.name}</div>
            <button
              className="btn-secondary text-[11px] px-2 py-1"
              onClick={() => {
                setNodes(nds => [...nds, { id: nextNodeId('get'), type: 'get', position: { x: variableDropMenu.flowX, y: variableDropMenu.flowY }, data: { name: variableDropMenu.name } }]);
                setVariableDropMenu(null);
              }}
            >
              📤 Obtener (Get)
            </button>
            <button
              className="btn-secondary text-[11px] px-2 py-1"
              onClick={() => {
                setNodes(nds => [...nds, { id: nextNodeId('set'), type: 'set', position: { x: variableDropMenu.flowX, y: variableDropMenu.flowY }, data: { name: variableDropMenu.name } }]);
                setVariableDropMenu(null);
              }}
            >
              💾 Guardar (Set)
            </button>
          </div>
        )}
      </div>
      {selectedNode && (
        <div className="shrink-0 p-2 text-[11px]" style={{ width: 220, border: '1px solid var(--acm-border)', borderRadius: 8, color: 'var(--acm-fg-2)' }}>
          <div
            style={{
              fontWeight: 600, marginBottom: 8, paddingBottom: 6,
              borderBottom: `2px solid ${CATEGORY_COLORS[NODE_CATEGORY[selectedNode.type || 'http']]}`,
            }}
          >
            {NODE_LABELS[(selectedNode.type || 'http') as keyof typeof NODE_TYPES]}
          </div>
          {selectedNode.type === 'start' && (
            <InspectorSection title="Parámetros">
              {((selectedNode.data.parameters as StartParam[] | undefined) || []).map((p, i) => (
                <div key={i} className="flex flex-col gap-1 mb-2 p-1" style={{ border: '1px solid var(--acm-border)', borderRadius: 4 }}>
                  <input
                    className="acm-input w-full"
                    placeholder="nombre (ej: producto)"
                    value={p.name}
                    onChange={e => updateStartParam(i, { name: e.target.value })}
                  />
                  <select
                    className="acm-input w-full"
                    value={p.type}
                    onChange={e => updateStartParam(i, { type: e.target.value as StartParam['type'] })}
                  >
                    <option value="string">texto</option>
                    <option value="number">número</option>
                    <option value="boolean">verdadero/falso</option>
                  </select>
                  <input
                    className="acm-input w-full"
                    placeholder="descripción (ayuda al LLM a saber qué mandar)"
                    value={p.description}
                    onChange={e => updateStartParam(i, { description: e.target.value })}
                  />
                  <label className="flex items-center gap-1">
                    <input type="checkbox" checked={p.required} onChange={e => updateStartParam(i, { required: e.target.checked })} />
                    Obligatorio
                  </label>
                  <button onClick={() => removeStartParam(i)} className="text-[var(--acm-fg-4)] hover:text-[var(--acm-err)] self-end">
                    <Trash2 size={11} />
                  </button>
                </div>
              ))}
              <button onClick={addStartParam} className="btn-secondary w-full">+ Parámetro</button>
            </InspectorSection>
          )}
          {selectedNode.type === 'http' && (
            <>
              <InspectorSection title="Request">
                <label>URL</label>
                <VariablePicker
                  nodeId={selectedNode.id}
                  nodes={nodes}
                  edges={edges}
                  outputs={testOutputs}
                  targetRef={urlInputRef}
                  value={String(selectedNode.data.url || '')}
                  onInsert={v => updateSelectedNodeData({ url: v })}
                />
                <ConnectableField nodeId={selectedNode.id} fieldName="url" edges={edges} setEdges={setEdges}>
                  <input ref={urlInputRef} className="acm-input w-full" value={String(selectedNode.data.url || '')} onChange={e => updateSelectedNodeData({ url: e.target.value })} />
                  <TemplatePreview value={String(selectedNode.data.url || '')} params={testParams} outputs={testOutputs} />
                </ConnectableField>
                <label>Método</label>
                <select className="acm-input w-full" value={String(selectedNode.data.method || 'GET')} onChange={e => updateSelectedNodeData({ method: e.target.value })}>
                  <option>GET</option><option>POST</option><option>PUT</option><option>DELETE</option>
                </select>
              </InspectorSection>
              <InspectorSection title="Headers & Body" defaultOpen={false}>
                <label>Cuerpo (para POST/PUT)</label>
                <VariablePicker
                  nodeId={selectedNode.id}
                  nodes={nodes}
                  edges={edges}
                  outputs={testOutputs}
                  targetRef={bodyInputRef}
                  value={String(selectedNode.data.body || '')}
                  onInsert={v => updateSelectedNodeData({ body: v })}
                />
                <ConnectableField nodeId={selectedNode.id} fieldName="body" edges={edges} setEdges={setEdges}>
                  <textarea ref={bodyInputRef} className="acm-input w-full" rows={3} value={String(selectedNode.data.body || '')} onChange={e => updateSelectedNodeData({ body: e.target.value })} />
                  <TemplatePreview value={String(selectedNode.data.body || '')} params={testParams} outputs={testOutputs} />
                </ConnectableField>
              </InspectorSection>
            </>
          )}
          {selectedNode.type === 'conditional' && (
            <>
              <div className="label text-[var(--acm-fg-4)] mb-1">Condición</div>
              <label>Campo (ej: {'{{http1.status}}'})</label>
              <VariablePicker
                nodeId={selectedNode.id}
                nodes={nodes}
                edges={edges}
                outputs={testOutputs}
                targetRef={conditionalFieldRef}
                value={String(selectedNode.data.field || '')}
                onInsert={v => updateSelectedNodeData({ field: v })}
              />
              <ConnectableField nodeId={selectedNode.id} fieldName="field" edges={edges} setEdges={setEdges}>
                <input ref={conditionalFieldRef} className="acm-input w-full mb-2" value={String(selectedNode.data.field || '')} onChange={e => updateSelectedNodeData({ field: e.target.value })} />
                <TemplatePreview value={String(selectedNode.data.field || '')} params={testParams} outputs={testOutputs} />
              </ConnectableField>
              <label>Operador</label>
              <select className="acm-input w-full mb-2" value={String(selectedNode.data.operator || 'contains')} onChange={e => updateSelectedNodeData({ operator: e.target.value })}>
                <option value="contains">contiene</option>
                <option value="equals">es igual a</option>
                <option value="is_empty">está vacío</option>
                <option value="is_error">es un error</option>
              </select>
              <label>Valor</label>
              <ConnectableField nodeId={selectedNode.id} fieldName="value" edges={edges} setEdges={setEdges}>
                <input className="acm-input w-full" value={String(selectedNode.data.value || '')} onChange={e => updateSelectedNodeData({ value: e.target.value })} />
              </ConnectableField>
            </>
          )}
          {selectedNode.type === 'woocommerce' && (
            <>
              <div className="label text-[var(--acm-fg-4)] mb-1">WooCommerce</div>
              <label>Conexión</label>
              <select
                className="acm-input w-full mb-2"
                value={String(selectedNode.data.connection_id ?? '')}
                onChange={e => updateSelectedNodeData({ connection_id: Number(e.target.value) })}
              >
                <option value="">Seleccionar...</option>
                {(connections || []).map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
              </select>
              {showNewConnectionForm ? (
                <div className="flex flex-col gap-1 mb-2">
                  <input className="acm-input w-full" placeholder="Nombre" value={newConnName} onChange={e => setNewConnName(e.target.value)} />
                  <input className="acm-input w-full" placeholder="URL de la tienda" value={newConnUrl} onChange={e => setNewConnUrl(e.target.value)} />
                  <input className="acm-input w-full" placeholder="Consumer Key" value={newConnKey} onChange={e => setNewConnKey(e.target.value)} />
                  <input className="acm-input w-full" placeholder="Consumer Secret" type="password" value={newConnSecret} onChange={e => setNewConnSecret(e.target.value)} />
                  <div className="flex gap-1 justify-end">
                    <button onClick={() => setShowNewConnectionForm(false)} className="btn-secondary text-[11px] px-2 py-1">Cancelar</button>
                    <button onClick={submitNewConnection} disabled={createConnection.isPending || !newConnName} className="btn-secondary text-[11px] px-2 py-1">Guardar</button>
                  </div>
                </div>
              ) : (
                <button onClick={() => setShowNewConnectionForm(true)} className="btn-secondary text-[11px] px-2 py-1 mb-2">+ Nueva conexión</button>
              )}
              <label>Término de búsqueda</label>
              <VariablePicker
                nodeId={selectedNode.id}
                nodes={nodes}
                edges={edges}
                outputs={testOutputs}
                targetRef={searchTermRef}
                value={String(selectedNode.data.search_term || '')}
                onInsert={v => updateSelectedNodeData({ search_term: v })}
              />
              <ConnectableField nodeId={selectedNode.id} fieldName="search_term" edges={edges} setEdges={setEdges}>
                <input ref={searchTermRef} className="acm-input w-full" value={String(selectedNode.data.search_term || '')} onChange={e => updateSelectedNodeData({ search_term: e.target.value })} />
                <TemplatePreview value={String(selectedNode.data.search_term || '')} params={testParams} outputs={testOutputs} />
              </ConnectableField>
            </>
          )}
          {selectedNode.type === 'end' && (
            <>
              <div className="label text-[var(--acm-fg-4)] mb-1">Respuesta</div>
              <label>Plantilla de respuesta</label>
              <VariablePicker
                nodeId={selectedNode.id}
                nodes={nodes}
                edges={edges}
                outputs={testOutputs}
                targetRef={templateRef}
                value={String(selectedNode.data.template || '')}
                onInsert={v => updateSelectedNodeData({ template: v })}
              />
              <textarea ref={templateRef} className="acm-input w-full" rows={4} value={String(selectedNode.data.template || '')} onChange={e => updateSelectedNodeData({ template: e.target.value })} />
              <TemplatePreview value={String(selectedNode.data.template || '')} params={testParams} outputs={testOutputs} />
            </>
          )}
          {selectedNode.type === 'set' && (
            <>
              <div className="label text-[var(--acm-fg-4)] mb-1">Guardar (Set)</div>
              <label>Nombre de la variable</label>
              <input
                className="acm-input w-full"
                placeholder="ej: resultado_busqueda"
                value={String(selectedNode.data.name || '')}
                onChange={e => updateSelectedNodeData({ name: e.target.value })}
              />
            </>
          )}
          {selectedNode.type === 'get' && (
            <>
              <div className="label text-[var(--acm-fg-4)] mb-1">Obtener (Get)</div>
              <label>Nombre de la variable</label>
              <input
                className="acm-input w-full"
                placeholder="ej: resultado_busqueda"
                value={String(selectedNode.data.name || '')}
                onChange={e => updateSelectedNodeData({ name: e.target.value })}
              />
            </>
          )}
        </div>
      )}
      {showSkillPanel && (
        <div className="shrink-0 p-2 text-[11px]" style={{ width: 260, border: '1px solid var(--acm-border)', borderRadius: 8, color: 'var(--acm-fg-2)' }}>
          <div style={{ fontWeight: 600, marginBottom: 8 }}>Skill del flujo</div>
          <label>Nombre{flowSkill ? ' (no editable tras crear)' : ''}</label>
          <input
            className="acm-input w-full mb-2"
            value={skillName}
            disabled={!!flowSkill}
            onChange={e => setSkillName(e.target.value)}
          />
          <label>Contenido (qué debe saber el LLM para usar este flujo)</label>
          <textarea className="acm-input w-full mb-2" rows={8} value={skillContent} onChange={e => setSkillContent(e.target.value)} />
          <div className="flex gap-1 flex-wrap">
            {!flowSkill && (
              <button
                className="btn-secondary text-[11px] px-2 py-1"
                disabled={generateFlowSkill.isPending}
                onClick={() => {
                  setSkillError(null);
                  generateFlowSkill.mutate(
                    { name: skillName, description: flow.description },
                    {
                      onSuccess: (skill: any) => setSkillContent(skill.content),
                      onError: () => setSkillError('Error al generar el skill con IA.'),
                    },
                  );
                }}
              >
                {generateFlowSkill.isPending ? 'Generando...' : 'Generar con IA'}
              </button>
            )}
            <button
              className="btn-primary text-[11px] px-2 py-1"
              disabled={saveFlowSkill.isPending}
              onClick={() => {
                setSkillError(null);
                saveFlowSkill.mutate(
                  { exists: !!flowSkill, data: { name: skillName, content: skillContent } },
                  { onError: () => setSkillError('Error al guardar el skill.') },
                );
              }}
            >
              {saveFlowSkill.isPending ? 'Guardando...' : 'Guardar'}
            </button>
            <button className="btn-secondary text-[11px] px-2 py-1" onClick={() => setShowSkillPanel(false)}>Cerrar</button>
          </div>
          {skillError && (
            <div className="mt-1 p-1 text-[10px]" style={{ background: 'var(--acm-base)', border: '1px solid var(--acm-err)', borderRadius: 4, color: 'var(--acm-err)' }}>
              {skillError}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export function FlowCanvas(props: { agentId: number; flow: AgentFlow; onSave: (graphJson: string) => void }) {
  return (
    <ReactFlowProvider>
      <FlowCanvasInner {...props} />
    </ReactFlowProvider>
  );
}
