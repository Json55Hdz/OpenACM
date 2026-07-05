'use client';

import { useCallback, useMemo, useRef, useState } from 'react';
import {
  ReactFlow, Background, Controls, MiniMap, addEdge, applyNodeChanges, applyEdgeChanges,
  type Node, type Edge, type Connection, type NodeChange, type EdgeChange,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { NODE_TYPES } from './node-types';
import type { AgentFlow } from '@/hooks/use-agent-flows';
import { useAgentConnections, useCreateConnection } from '@/hooks/use-agent-connections';
import { useAPI } from '@/hooks/use-api';

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

export function FlowCanvas({ agentId, flow, onSave }: { agentId: number; flow: AgentFlow; onSave: (graphJson: string) => void }) {
  const initial = useMemo(() => toReactFlow(JSON.parse(flow.graph_json || '{"nodes":[],"edges":[]}')), [flow.id]);
  const [nodes, setNodes] = useState<Node[]>(initial.nodes);
  const [edges, setEdges] = useState<Edge[]>(initial.edges);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const nodeIdCounterRef = useRef(maxNodeIdSuffix(initial.nodes));

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

  const [testParams, setTestParams] = useState<Record<string, string>>({});
  const [testResult, setTestResult] = useState<string | null>(null);
  const [testing, setTesting] = useState(false);
  const { fetchAPI } = useAPI();

  const startNode = nodes.find(n => n.type === 'start');
  const startParams = (startNode?.data.parameters as Array<{ name: string }> | undefined) || [];

  const runTest = async () => {
    setTesting(true);
    setTestResult(null);
    try {
      const res = (await fetchAPI(`/api/agents/${agentId}/flows/${flow.id}/test`, {
        method: 'POST',
        body: JSON.stringify({ params: testParams }),
      })) as { result: string };
      setTestResult(res.result);
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

  const onNodesChange = useCallback((changes: NodeChange[]) => setNodes(nds => applyNodeChanges(changes, nds)), []);
  const onEdgesChange = useCallback((changes: EdgeChange[]) => setEdges(eds => applyEdgeChanges(changes, eds)), []);
  const onConnect = useCallback((connection: Connection) => setEdges(eds => addEdge(connection, eds)), []);

  const addNode = (type: keyof typeof NODE_TYPES) => {
    const defaults: Record<string, Record<string, unknown>> = {
      start: { parameters: [] },
      http: { url: '', method: 'GET', headers: {}, body: '' },
      conditional: { field: '', operator: 'contains', value: '' },
      woocommerce: { connection_id: null, search_term: '' },
      end: { template: '' },
    };
    setNodes(nds => [...nds, { id: nextNodeId(type), type, position: { x: 100, y: 100 + nds.length * 90 }, data: defaults[type] }]);
  };

  const selectedNode = nodes.find(n => n.id === selectedId) || null;

  const updateSelectedNodeData = (patch: Record<string, unknown>) => {
    if (!selectedNode) return;
    setNodes(nds => nds.map(n => n.id === selectedNode.id ? { ...n, data: { ...n.data, ...patch } } : n));
  };

  const handleSave = () => onSave(JSON.stringify(toGraphJson(nodes, edges)));

  return (
    <div className="flex gap-2" style={{ height: 500 }}>
      <div className="flex flex-col gap-1 shrink-0" style={{ width: 120 }}>
        {(Object.keys(NODE_TYPES) as (keyof typeof NODE_TYPES)[]).map(t => (
          <button key={t} onClick={() => addNode(t)} className="btn-secondary text-[11px] px-2 py-1">+ {t}</button>
        ))}
        <button onClick={handleSave} className="btn-primary text-[11px] px-2 py-1 mt-2">Guardar flujo</button>
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
          {testResult && (
            <div className="mt-1 p-1 text-[10px] whitespace-pre-wrap" style={{ background: 'var(--acm-base)', border: '1px solid var(--acm-border)', borderRadius: 4, color: 'var(--acm-fg-3)' }}>
              {testResult}
            </div>
          )}
        </div>
      </div>
      <div className="flex-1" style={{ border: '1px solid var(--acm-border)', borderRadius: 8 }}>
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onConnect={onConnect}
          onNodeClick={(_e, node) => setSelectedId(node.id)}
          onPaneClick={() => setSelectedId(null)}
          nodeTypes={NODE_TYPES}
          fitView
        >
          <Background />
          <Controls />
          <MiniMap />
        </ReactFlow>
      </div>
      {selectedNode && (
        <div className="shrink-0 p-2 text-[11px]" style={{ width: 220, border: '1px solid var(--acm-border)', borderRadius: 8, color: 'var(--acm-fg-2)' }}>
          <div style={{ fontWeight: 600, marginBottom: 8 }}>{selectedNode.type}</div>
          {selectedNode.type === 'http' && (
            <>
              <label>URL</label>
              <input className="acm-input w-full mb-2" value={String(selectedNode.data.url || '')} onChange={e => updateSelectedNodeData({ url: e.target.value })} />
              <label>Método</label>
              <select className="acm-input w-full mb-2" value={String(selectedNode.data.method || 'GET')} onChange={e => updateSelectedNodeData({ method: e.target.value })}>
                <option>GET</option><option>POST</option><option>PUT</option><option>DELETE</option>
              </select>
            </>
          )}
          {selectedNode.type === 'conditional' && (
            <>
              <label>Campo (ej: {'{{http1.status}}'})</label>
              <input className="acm-input w-full mb-2" value={String(selectedNode.data.field || '')} onChange={e => updateSelectedNodeData({ field: e.target.value })} />
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
              <input className="acm-input w-full" value={String(selectedNode.data.search_term || '')} onChange={e => updateSelectedNodeData({ search_term: e.target.value })} />
            </>
          )}
          {selectedNode.type === 'end' && (
            <>
              <label>Plantilla de respuesta</label>
              <textarea className="acm-input w-full" rows={4} value={String(selectedNode.data.template || '')} onChange={e => updateSelectedNodeData({ template: e.target.value })} />
            </>
          )}
        </div>
      )}
    </div>
  );
}
