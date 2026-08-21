'use client';

import { useState } from 'react';

interface NodeError {
  nodeId: string;
  nodeType: string;
  message: string;
}

// Matches FlowExecutor.run()'s one exception-carrying error string —
// "Error in node 'X' (type): message" — so the panel can show which node
// failed and why, instead of the raw prefixed string. Every OTHER error
// string run() returns (missing Start node, missing param, cycle guard,
// unknown node/type) names no specific node, so they fall through to the
// plain result-block rendering below.
function parseNodeError(result: string): NodeError | null {
  const m = result.match(/^Error in node '([^']+)' \(([^)]+)\): ([\s\S]+)$/);
  return m ? { nodeId: m[1], nodeType: m[2], message: m[3] } : null;
}

export function FlowTestPanel({
  startParams, testParams, onParamChange, onRun, testing, result, outputs, error,
}: {
  startParams: Array<{ name: string; required?: boolean }>;
  testParams: Record<string, string>;
  onParamChange: (name: string, value: string) => void;
  onRun: () => void;
  testing: boolean;
  result: string | null;
  outputs: Record<string, unknown> | null;
  error: boolean;
}) {
  const [outputsOpen, setOutputsOpen] = useState(false);
  const nodeError = result !== null && error ? parseNodeError(result) : null;
  const outputEntries = outputs ? Object.entries(outputs) : [];

  return (
    <div
      className="flex flex-col gap-2 p-3 rounded shrink-0 overflow-hidden"
      style={{ background: 'var(--acm-elev)', border: '1px solid var(--acm-border)', width: 320 }}
    >
      <div className="text-[11px] font-medium uppercase tracking-[0.08em]" style={{ color: 'var(--acm-fg-4)' }}>
        Probar flujo
      </div>

      {startParams.length > 0 && (
        <div className="flex flex-col gap-1.5">
          {startParams.map(p => (
            <input
              key={p.name}
              className="acm-input text-[12px]"
              placeholder={p.required ? `${p.name} *` : p.name}
              value={testParams[p.name] || ''}
              onChange={e => onParamChange(p.name, e.target.value)}
            />
          ))}
        </div>
      )}

      <button onClick={onRun} disabled={testing} className="btn-primary text-[12px] px-2.5 py-1.5 disabled:opacity-50">
        {testing ? 'Ejecutando…' : '▶ Ejecutar'}
      </button>

      {result === null ? (
        <div className="text-[11px] leading-relaxed" style={{ color: 'var(--acm-fg-4)' }}>
          Ejecutá el flujo para ver acá el resultado y las salidas de cada nodo.
        </div>
      ) : (
        <div className="flex flex-col gap-2 min-w-0">
          <div className="flex items-center gap-1.5 text-[11px] font-medium" style={{ color: error ? 'var(--acm-err)' : 'var(--acm-ok)' }}>
            <span className={`dot ${error ? 'dot-err' : 'dot-ok'}`} />
            {error ? (nodeError ? `Error en nodo "${nodeError.nodeId}"` : 'Error') : 'Éxito'}
            {nodeError && (
              <span
                className="mono text-[9px] px-1.5 py-0.5 rounded"
                style={{ background: 'var(--acm-base)', border: '1px solid var(--acm-border)', color: 'var(--acm-fg-3)', fontWeight: 'normal' }}
              >
                {nodeError.nodeType}
              </span>
            )}
          </div>

          <div
            className="mono text-[11px] p-2 rounded overflow-y-auto overflow-x-hidden whitespace-pre-wrap break-words acm-scroll"
            style={{ background: 'var(--acm-base)', border: '1px solid var(--acm-border)', color: error ? 'var(--acm-err)' : 'var(--acm-fg-2)', maxHeight: 200 }}
          >
            {(nodeError ? nodeError.message : result) || '(el flujo no devolvió texto — revisá la plantilla del nodo Final)'}
          </div>

          {outputEntries.length > 0 && (
            <div className="min-w-0">
              <button
                onClick={() => setOutputsOpen(v => !v)}
                className="text-[10px] flex items-center gap-1 w-full"
                style={{ color: 'var(--acm-fg-4)' }}
              >
                <span>{outputsOpen ? '▾' : '▸'}</span> Salidas por nodo ({outputEntries.length})
              </button>
              {outputsOpen && (
                <div className="mt-1 flex flex-col gap-1 max-h-40 overflow-y-auto acm-scroll">
                  {outputEntries.map(([key, value]) => (
                    <div key={key} className="text-[10px] px-1.5 py-1 rounded min-w-0" style={{ background: 'var(--acm-base)', border: '1px solid var(--acm-border)' }}>
                      <div className="mono" style={{ color: 'var(--acm-node-data)' }}>{key}</div>
                      <div className="mono break-words" style={{ color: 'var(--acm-fg-3)' }}>
                        {typeof value === 'string' ? value : JSON.stringify(value)}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
