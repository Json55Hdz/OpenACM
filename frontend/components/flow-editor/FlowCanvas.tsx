'use client';

import { useCallback, useMemo, useRef, useState } from 'react';
import {
  ReactFlow, ReactFlowProvider, useReactFlow, Background, Controls, MiniMap, addEdge, applyNodeChanges, applyEdgeChanges,
  type Node, type Edge, type Connection, type NodeChange, type EdgeChange,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { NODE_TYPES, NODE_CATEGORY, CATEGORY_COLORS } from './node-types';
import type { AgentFlow } from '@/hooks/use-agent-flows';
import { useAgentConnections, useCreateConnection } from '@/hooks/use-agent-connections';
import { useAgentFlowSkill, useSaveFlowSkill, useGenerateFlowSkill } from '@/hooks/use-agent-flow-skill';
import { useAPI } from '@/hooks/use-api';
import { Trash2 } from 'lucide-react';
import { InspectorSection } from './InspectorSection';

interface StartParam {
  name: string;
  type: 'string' | 'number' | 'boolean';
  description: string;
  required: boolean;
}

interface GraphJson {
  nodes: Array<{ id: string; type: string; config: Record<string, unknown>; position: { x: number; y: number } }>;
  edges: Array<{ from: string; to: string; fromHandle: string }>;
}

function toReactFlow(graph: GraphJson): { nodes: Node[]; edges: Edge[] } {
  return {
    nodes: graph.nodes.map(n => ({ id: n.id, type: n.type, position: n.position, data: n.config })),
    edges: graph.edges.map(e => ({
      id: `${e.from}-${e.to}-${e.fromHandle}`, source: e.from, target: e.to, sourceHandle: e.fromHandle,
    })),
  };
}

function toGraphJson(nodes: Node[], edges: Edge[]): GraphJson {
  return {
    nodes: nodes.map(n => ({ id: n.id, type: n.type || 'http', config: n.data as Record<string, unknown>, position: n.position })),
    edges: edges.map(e => ({ from: e.source, to: e.target, fromHandle: e.sourceHandle || 'default' })),
  };
}

// Local re-implementation of flow_executor.py's substitute_templates rule
// (bare {{name}} whole-value, {{node_id.field}} one-level dict lookup,
// "[missing: ...]" marker) so the Inspector can preview a resolved value
// without a network round-trip per keystroke.
function previewTemplate(template: string, outputs: Record<string, unknown>): string {
  return template.replace(/\{\{([a-zA-Z0-9_]+)(?:\.([a-zA-Z0-9_]+))?\}\}/g, (_match, name, field) => {
    if (field === undefined) {
      return name in outputs ? String(outputs[name]) : `[missing: ${name}]`;
    }
    const value = outputs[name];
    if (value && typeof value === 'object' && field in (value as Record<string, unknown>)) {
      return String((value as Record<string, unknown>)[field]);
    }
    return `[missing: ${name}.${field}]`;
  });
}

function TemplatePreview({ value, outputs }: { value: string; outputs: Record<string, unknown> | null }) {
  if (!outputs) {
    return <div className="text-[9px] mt-1" style={{ color: 'var(--acm-fg-4)' }}>corré &quot;Probar flujo&quot; para ver valores reales acá</div>;
  }
  if (!value.includes('{{')) return null;
  return <div className="text-[9px] mt-1 p-1" style={{ background: 'var(--acm-base)', borderRadius: 4, color: 'var(--acm-fg-3)' }}>{previewTemplate(value, outputs)}</div>;
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

function availableVariableNames(nodes: Node[], edges: Edge[], selectedNodeId: string): string[] {
  // A node can have multiple incoming edges since merge points were added
  // (a Conditional's true/false branches sharing a downstream node) — this
  // collects every ancestor reachable via ANY incoming path, not just a
  // single linear chain. A Set node reachable via only one branch still
  // shows up as an insertable reference here; if the flow actually took
  // the other branch at runtime, referencing it resolves to the existing
  // "[missing: ...]" marker rather than being silently hidden from the
  // picker.
  const incomingBySource: Record<string, string[]> = {};
  for (const e of edges) {
    (incomingBySource[e.target] ||= []).push(e.source);
  }

  const names = new Set<string>();
  const visited = new Set<string>();
  const queue: string[] = [...(incomingBySource[selectedNodeId] || [])];
  while (queue.length > 0) {
    const currentId = queue.shift()!;
    if (visited.has(currentId)) continue;
    visited.add(currentId);
    const node = nodes.find(n => n.id === currentId);
    const name = node?.type === 'set' ? (node.data.name as string | undefined) : undefined;
    if (name) names.add(name);
    queue.push(...(incomingBySource[currentId] || []));
  }
  return Array.from(names);
}

function VariablePicker({ names, targetRef, value, onInsert }: {
  names: string[];
  targetRef: React.RefObject<HTMLInputElement | HTMLTextAreaElement | null>;
  value: string;
  onInsert: (newValue: string) => void;
}) {
  if (names.length === 0) return null;
  return (
    <select
      className="acm-input w-full mb-1 text-[10px]"
      value=""
      onChange={e => {
        const name = e.target.value;
        if (!name) return;
        const insertText = `{{${name}}}`;
        const el = targetRef.current;
        const start = el?.selectionStart ?? value.length;
        const end = el?.selectionEnd ?? value.length;
        onInsert(value.slice(0, start) + insertText + value.slice(end));
      }}
    >
      <option value="">Insertar variable...</option>
      {names.map(n => <option key={n} value={n}>{n}</option>)}
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
  const [skillName, setSkillName] = useState(flowSkill?.name || flow.name);
  const [skillContent, setSkillContent] = useState(flowSkill?.content || '');
  const [skillError, setSkillError] = useState<string | null>(null);

  const [testParams, setTestParams] = useState<Record<string, string>>({});
  const [testResult, setTestResult] = useState<string | null>(null);
  const [testOutputs, setTestOutputs] = useState<Record<string, unknown> | null>(null);
  const [testing, setTesting] = useState(false);
  const { fetchAPI } = useAPI();

  const startNode = nodes.find(n => n.type === 'start');
  const startParams = (startNode?.data.parameters as Array<{ name: string }> | undefined) || [];

  const runTest = async () => {
    setTesting(true);
    setTestResult(null);
    try {
      // Test the graph as it currently stands in the canvas, not whatever
      // was last saved — saving before every test run was real friction.
      const currentGraph = JSON.stringify(toGraphJson(nodes, edges));
      const res = (await fetchAPI(`/api/agents/${agentId}/flows/${flow.id}/test`, {
        method: 'POST',
        body: JSON.stringify({ params: testParams, graph_json: currentGraph }),
      })) as { result: string; outputs: Record<string, unknown> };
      setTestResult(res.result);
      setTestOutputs(res.outputs);
    } catch {
      setTestResult('Error al ejecutar la prueba.');
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
      id: `${idMap[e.source]}-${idMap[e.target]}-${e.sourceHandle || 'default'}`,
      source: idMap[e.source],
      target: idMap[e.target],
      sourceHandle: e.sourceHandle,
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
  const onConnect = useCallback((connection: Connection) => setEdges(eds => addEdge(connection, eds)), []);

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

    setNodes(nds => [...nds, { id: newId, type: 'set', position: flowPosition, data: { name } }]);
    setEdges(eds => [...eds, {
      id: `${connectionState.fromNode!.id}-${newId}-${connectionState.fromHandle?.id || 'default'}`,
      source: connectionState.fromNode!.id,
      target: newId,
      sourceHandle: connectionState.fromHandle?.id || 'default',
    }]);
  }, [screenToFlowPosition]);

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

  return (
    <div className="flex gap-2" style={{ height: 500 }}>
      <div className="flex flex-col gap-1 shrink-0" style={{ width: 120 }}>
        <div className="text-[10px]" style={{ color: 'var(--acm-fg-4)' }}>Clic derecho en el lienzo para agregar un nodo</div>
        <button onClick={handleSave} className="btn-primary text-[11px] px-2 py-1 mt-2">Guardar flujo</button>
        <button onClick={() => { setSkillName(flowSkill?.name || flow.name); setSkillContent(flowSkill?.content || ''); setSkillError(null); setShowSkillPanel(true); }} className="btn-secondary text-[11px] px-2 py-1 mt-1">
          {flowSkill ? 'Editar skill' : '+ Skill'}
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
        <div className="mt-2 pt-2" style={{ borderTop: '1px solid var(--acm-border)' }}>
          <div className="text-[11px] mb-1" style={{ color: 'var(--acm-fg-4)' }}>Probar flujo</div>
          {startParams.map(p => (
            <input
              key={p.name}
              className="acm-input w-full mb-1 text-[11px]"
              placeholder={p.name}
              value={testParams[p.name] || ''}
              onChange={e => setTestParams(prev => ({ ...prev, [p.name]: e.target.value }))}
            />
          ))}
          <button onClick={runTest} disabled={testing} className="btn-secondary text-[11px] px-2 py-1 w-full">
            {testing ? 'Ejecutando...' : 'Probar flujo'}
          </button>
          {testResult !== null && (
            <div className="mt-1 p-1 text-[10px] whitespace-pre-wrap" style={{ background: 'var(--acm-base)', border: '1px solid var(--acm-border)', borderRadius: 4, color: 'var(--acm-fg-3)' }}>
              {testResult || '(el flujo no devolvió texto — revisa la plantilla del nodo Final)'}
            </div>
          )}
        </div>
      </div>
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
          onNodeClick={(_e, node) => setSelectedId(node.id)}
          onPaneClick={() => { setSelectedId(null); setContextMenu(null); setVariableDropMenu(null); }}
          onPaneContextMenu={onPaneContextMenu}
          nodeTypes={NODE_TYPES}
          fitView
        >
          <Background />
          <Controls />
          <MiniMap />
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
                  names={availableVariableNames(nodes, edges, selectedNode.id)}
                  targetRef={urlInputRef}
                  value={String(selectedNode.data.url || '')}
                  onInsert={v => updateSelectedNodeData({ url: v })}
                />
                <input ref={urlInputRef} className="acm-input w-full" value={String(selectedNode.data.url || '')} onChange={e => updateSelectedNodeData({ url: e.target.value })} />
                <TemplatePreview value={String(selectedNode.data.url || '')} outputs={testOutputs} />
                <label>Método</label>
                <select className="acm-input w-full" value={String(selectedNode.data.method || 'GET')} onChange={e => updateSelectedNodeData({ method: e.target.value })}>
                  <option>GET</option><option>POST</option><option>PUT</option><option>DELETE</option>
                </select>
              </InspectorSection>
              <InspectorSection title="Headers & Body" defaultOpen={false}>
                <label>Cuerpo (para POST/PUT)</label>
                <VariablePicker
                  names={availableVariableNames(nodes, edges, selectedNode.id)}
                  targetRef={bodyInputRef}
                  value={String(selectedNode.data.body || '')}
                  onInsert={v => updateSelectedNodeData({ body: v })}
                />
                <textarea ref={bodyInputRef} className="acm-input w-full" rows={3} value={String(selectedNode.data.body || '')} onChange={e => updateSelectedNodeData({ body: e.target.value })} />
                <TemplatePreview value={String(selectedNode.data.body || '')} outputs={testOutputs} />
              </InspectorSection>
            </>
          )}
          {selectedNode.type === 'conditional' && (
            <>
              <div className="label text-[var(--acm-fg-4)] mb-1">Condición</div>
              <label>Campo (ej: {'{{http1.status}}'})</label>
              <VariablePicker
                names={availableVariableNames(nodes, edges, selectedNode.id)}
                targetRef={conditionalFieldRef}
                value={String(selectedNode.data.field || '')}
                onInsert={v => updateSelectedNodeData({ field: v })}
              />
              <input ref={conditionalFieldRef} className="acm-input w-full mb-2" value={String(selectedNode.data.field || '')} onChange={e => updateSelectedNodeData({ field: e.target.value })} />
              <TemplatePreview value={String(selectedNode.data.field || '')} outputs={testOutputs} />
              <label>Operador</label>
              <select className="acm-input w-full mb-2" value={String(selectedNode.data.operator || 'contains')} onChange={e => updateSelectedNodeData({ operator: e.target.value })}>
                <option value="contains">contiene</option>
                <option value="equals">es igual a</option>
                <option value="is_empty">está vacío</option>
                <option value="is_error">es un error</option>
              </select>
              <label>Valor</label>
              <input className="acm-input w-full" value={String(selectedNode.data.value || '')} onChange={e => updateSelectedNodeData({ value: e.target.value })} />
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
                names={availableVariableNames(nodes, edges, selectedNode.id)}
                targetRef={searchTermRef}
                value={String(selectedNode.data.search_term || '')}
                onInsert={v => updateSelectedNodeData({ search_term: v })}
              />
              <input ref={searchTermRef} className="acm-input w-full" value={String(selectedNode.data.search_term || '')} onChange={e => updateSelectedNodeData({ search_term: e.target.value })} />
              <TemplatePreview value={String(selectedNode.data.search_term || '')} outputs={testOutputs} />
            </>
          )}
          {selectedNode.type === 'end' && (
            <>
              <div className="label text-[var(--acm-fg-4)] mb-1">Respuesta</div>
              <label>Plantilla de respuesta</label>
              <VariablePicker
                names={availableVariableNames(nodes, edges, selectedNode.id)}
                targetRef={templateRef}
                value={String(selectedNode.data.template || '')}
                onInsert={v => updateSelectedNodeData({ template: v })}
              />
              <textarea ref={templateRef} className="acm-input w-full" rows={4} value={String(selectedNode.data.template || '')} onChange={e => updateSelectedNodeData({ template: e.target.value })} />
              <TemplatePreview value={String(selectedNode.data.template || '')} outputs={testOutputs} />
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
