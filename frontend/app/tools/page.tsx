'use client';

import { useState } from 'react';
import { AppLayout } from '@/components/layout/app-layout';
import { useTools, useToolExecutions } from '@/hooks/use-api';
import {
  Wrench,
  Terminal,
  ChevronDown,
  ChevronUp,
} from 'lucide-react';

// ─── Types ───────────────────────────────────────────────────────────────────

interface Tool {
  name: string;
  description: string;
  parameters: Record<string, unknown>;
}

interface ToolExecution {
  id: number;
  tool_name: string;
  arguments: string;
  result: string;
  status: 'success' | 'error' | 'running';
  created_at: string;
  elapsed_ms?: number;
}

// ─── Group tools by inferred category ────────────────────────────────────────

function inferCategory(tool: Tool): string {
  const n = tool.name.toLowerCase();
  if (n.includes('file') || n.includes('read') || n.includes('write')) return 'File System';
  if (n.includes('search') || n.includes('web') || n.includes('browse')) return 'Web & Search';
  if (n.includes('code') || n.includes('run') || n.includes('exec') || n.includes('shell')) return 'Code & Execution';
  if (n.includes('memory') || n.includes('note') || n.includes('save')) return 'Memory';
  if (n.includes('calendar') || n.includes('cron') || n.includes('schedule')) return 'Scheduling';
  return 'General';
}

function groupByCategory(tools: Tool[]): Record<string, Tool[]> {
  const groups: Record<string, Tool[]> = {};
  for (const tool of tools) {
    const cat = inferCategory(tool);
    if (!groups[cat]) groups[cat] = [];
    groups[cat].push(tool);
  }
  return groups;
}

// ─── ToolCard (expandable params) ────────────────────────────────────────────

function ToolCard({ tool }: { tool: Tool }) {
  const [isExpanded, setIsExpanded] = useState(false);
  const params = Object.entries(tool.parameters || {});

  return (
    <div style={{ borderTop: '1px solid var(--acm-border)' }} className="py-3 px-4">
      <div className="flex items-center gap-3">
        {/* Amber terminal icon */}
        <Terminal size={15} style={{ color: 'var(--acm-accent)', flexShrink: 0 }} />

        <div className="flex-1 min-w-0">
          <span className="mono text-sm" style={{ color: 'var(--acm-fg)' }}>
            {tool.name}
          </span>
          {tool.description && (
            <p className="text-xs mt-0.5 truncate" style={{ color: 'var(--acm-fg-4)' }}>
              {tool.description}
            </p>
          )}
        </div>

        <div className="flex items-center gap-2 flex-shrink-0">
          {params.length > 0 && (
            <button
              onClick={() => setIsExpanded(!isExpanded)}
              className="btn-secondary"
              style={{ padding: '3px 9px', fontSize: '11px' }}
            >
              {params.length} param{params.length !== 1 ? 's' : ''}
              {isExpanded ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
            </button>
          )}
          <span
            className="mono"
            style={{
              fontSize: '10px',
              color: 'var(--acm-accent)',
              letterSpacing: '0.06em',
            }}
          >
            builtin
          </span>
        </div>
      </div>

      {isExpanded && params.length > 0 && (
        <div
          className="mt-3 rounded-md px-3 py-2"
          style={{ background: 'var(--acm-base)' }}
        >
          <p className="label mb-2">Parameters</p>
          <div className="space-y-1">
            {params.map(([key, value]) => (
              <div key={key} className="flex items-start gap-2 text-xs">
                <span className="mono" style={{ color: 'var(--acm-accent)', flexShrink: 0 }}>
                  {key}
                </span>
                <span style={{ color: 'var(--acm-fg-4)' }}>→</span>
                <span className="mono" style={{ color: 'var(--acm-fg-2)' }}>
                  {JSON.stringify(value)}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ─── ExecutionRow ─────────────────────────────────────────────────────────────

function ExecutionRow({ execution }: { execution: ToolExecution }) {
  const [showDetails, setShowDetails] = useState(false);

  const dotClass =
    execution.status === 'success'
      ? 'dot dot-ok'
      : execution.status === 'error'
      ? 'dot dot-err'
      : 'dot dot-warn acm-pulse';

  return (
    <div style={{ borderTop: '1px solid var(--acm-border)' }}>
      <div
        className="flex items-center gap-3 px-4 py-3 cursor-pointer"
        style={{ transition: 'background 120ms' }}
        onMouseEnter={(e) => ((e.currentTarget as HTMLElement).style.background = 'oklch(0.235 0.007 255 / 0.5)')}
        onMouseLeave={(e) => ((e.currentTarget as HTMLElement).style.background = 'transparent')}
        onClick={() => setShowDetails(!showDetails)}
      >
        <span className={dotClass} style={{ flexShrink: 0 }} />

        <div className="flex-1 min-w-0">
          <span className="mono text-sm" style={{ color: 'var(--acm-fg)' }}>
            {execution.tool_name}
          </span>
          <p className="text-xs mt-0.5 truncate mono" style={{ color: 'var(--acm-fg-4)' }}>
            {new Date(execution.created_at).toLocaleString()}
          </p>
        </div>

        {execution.elapsed_ms != null && (
          <span className="mono text-xs" style={{ color: 'var(--acm-fg-4)', flexShrink: 0 }}>
            {execution.elapsed_ms}ms
          </span>
        )}

        {showDetails ? (
          <ChevronUp size={14} style={{ color: 'var(--acm-fg-4)', flexShrink: 0 }} />
        ) : (
          <ChevronDown size={14} style={{ color: 'var(--acm-fg-4)', flexShrink: 0 }} />
        )}
      </div>

      {showDetails && (
        <div className="px-4 pb-4 space-y-3">
          <div className="rounded-md px-3 py-2" style={{ background: 'var(--acm-base)' }}>
            <p className="label mb-2">Arguments</p>
            <pre
              className="mono text-xs overflow-x-auto acm-scroll"
              style={{ color: 'var(--acm-fg-2)', whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}
            >
              {execution.arguments}
            </pre>
          </div>

          <div className="rounded-md px-3 py-2" style={{ background: 'var(--acm-base)' }}>
            <p className="label mb-2">Result</p>
            <pre
              className="mono text-xs overflow-x-auto acm-scroll"
              style={{
                color: execution.status === 'error' ? 'var(--acm-err)' : 'var(--acm-fg-2)',
                whiteSpace: 'pre-wrap',
                wordBreak: 'break-all',
              }}
            >
              {execution.result}
            </pre>
          </div>
        </div>
      )}
    </div>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function ToolsPage() {
  const { data: tools, isLoading: toolsLoading } = useTools();
  const { data: executions, isLoading: executionsLoading } = useToolExecutions();
  const [activeTab, setActiveTab] = useState<'tools' | 'executions'>('tools');

  const toolList: Tool[] = tools || [];
  const executionList: ToolExecution[] = executions || [];
  const categoryGroups = groupByCategory(toolList);
  const totalTools = toolList.length;

  // Tab button styles
  const tabStyle = (active: boolean): React.CSSProperties =>
    active
      ? {
          background: 'var(--acm-accent)',
          color: 'oklch(0.18 0.015 80)',
          border: '1px solid transparent',
          borderRadius: 'var(--acm-radius)',
          padding: '6px 14px',
          fontWeight: 600,
          fontSize: '13px',
          cursor: 'pointer',
          display: 'inline-flex',
          alignItems: 'center',
          gap: '6px',
          transition: 'background 140ms',
        }
      : {
          background: 'transparent',
          color: 'var(--acm-fg-3)',
          border: '1px solid var(--acm-border)',
          borderRadius: 'var(--acm-radius)',
          padding: '6px 14px',
          fontWeight: 500,
          fontSize: '13px',
          cursor: 'pointer',
          display: 'inline-flex',
          alignItems: 'center',
          gap: '6px',
          transition: 'border-color 140ms, color 140ms',
        };

  return (
    <AppLayout>
      <div className="p-6 lg:p-8" style={{ maxWidth: 1280, margin: '0 auto' }}>

        {/* ── Header ── */}
        <header className="mb-7">
          <span className="acm-breadcrumb">System / Tools</span>
          <h1 className="text-2xl font-bold" style={{ color: 'var(--acm-fg)' }}>
            Tools
          </h1>
          <p className="mt-1 text-sm" style={{ color: 'var(--acm-fg-3)' }}>
            Manage and monitor available tools
          </p>
        </header>

        {/* ── Tabs ── */}
        <div className="flex gap-2 mb-6">
          <button
            onClick={() => setActiveTab('tools')}
            style={tabStyle(activeTab === 'tools')}
            onMouseEnter={(e) => {
              if (activeTab !== 'tools') {
                (e.currentTarget as HTMLElement).style.borderColor = 'var(--acm-accent)';
                (e.currentTarget as HTMLElement).style.color = 'var(--acm-accent)';
              }
            }}
            onMouseLeave={(e) => {
              if (activeTab !== 'tools') {
                (e.currentTarget as HTMLElement).style.borderColor = 'var(--acm-border)';
                (e.currentTarget as HTMLElement).style.color = 'var(--acm-fg-3)';
              }
            }}
          >
            <Wrench size={15} />
            Tools
            {totalTools > 0 && (
              <span
                className="mono"
                style={{
                  fontSize: '10px',
                  background: activeTab === 'tools' ? 'oklch(0.18 0.015 80 / 0.25)' : 'var(--acm-elev)',
                  padding: '1px 5px',
                  borderRadius: '4px',
                }}
              >
                {totalTools}
              </span>
            )}
          </button>
          <button
            onClick={() => setActiveTab('executions')}
            style={tabStyle(activeTab === 'executions')}
            onMouseEnter={(e) => {
              if (activeTab !== 'executions') {
                (e.currentTarget as HTMLElement).style.borderColor = 'var(--acm-accent)';
                (e.currentTarget as HTMLElement).style.color = 'var(--acm-accent)';
              }
            }}
            onMouseLeave={(e) => {
              if (activeTab !== 'executions') {
                (e.currentTarget as HTMLElement).style.borderColor = 'var(--acm-border)';
                (e.currentTarget as HTMLElement).style.color = 'var(--acm-fg-3)';
              }
            }}
          >
            <Terminal size={15} />
            Execution Log
            {executionList.length > 0 && (
              <span
                className="mono"
                style={{
                  fontSize: '10px',
                  background: activeTab === 'executions' ? 'oklch(0.18 0.015 80 / 0.25)' : 'var(--acm-elev)',
                  padding: '1px 5px',
                  borderRadius: '4px',
                }}
              >
                {executionList.length}
              </span>
            )}
          </button>
        </div>

        {/* ── Tools Tab ── */}
        {activeTab === 'tools' && (
          <>
            {toolsLoading ? (
              <div className="grid gap-4" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(380px, 1fr))' }}>
                {[1, 2, 3].map((i) => (
                  <div
                    key={i}
                    className="acm-card"
                    style={{ height: 200, opacity: 0.4, animation: 'acm-pulse 1.8s ease-in-out infinite' }}
                  />
                ))}
              </div>
            ) : toolList.length === 0 ? (
              <div
                className="acm-card flex flex-col items-center justify-center"
                style={{ padding: '64px 32px', textAlign: 'center' }}
              >
                <Wrench size={40} style={{ color: 'var(--acm-fg-4)', marginBottom: 16 }} />
                <h3 className="text-base font-semibold mb-2" style={{ color: 'var(--acm-fg-2)' }}>
                  No tools available
                </h3>
                <p className="text-sm" style={{ color: 'var(--acm-fg-4)' }}>
                  Tools will be loaded automatically from active skills.
                </p>
              </div>
            ) : (
              /* Two-column layout: category cards */
              <div className="grid gap-4" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(380px, 1fr))' }}>
                {Object.entries(categoryGroups).map(([category, catTools]) => (
                  <div key={category} className="acm-card" style={{ overflow: 'hidden' }}>
                    {/* Category header */}
                    <div
                      className="flex items-center justify-between px-4 py-3"
                      style={{ borderBottom: '1px solid var(--acm-border)' }}
                    >
                      <span className="label">{category}</span>
                      <span
                        className="mono"
                        style={{ fontSize: '10px', color: 'var(--acm-accent)' }}
                      >
                        {catTools.length} builtin
                      </span>
                    </div>

                    {/* Tool rows */}
                    {catTools.map((tool) => (
                      <ToolCard key={tool.name} tool={tool} />
                    ))}
                  </div>
                ))}
              </div>
            )}
          </>
        )}

        {/* ── Executions Tab ── */}
        {activeTab === 'executions' && (
          <div className="acm-card" style={{ overflow: 'hidden' }}>
            {/* Log header */}
            <div
              className="flex items-center justify-between px-4 py-3"
              style={{ borderBottom: '1px solid var(--acm-border)' }}
            >
              <div className="flex items-center gap-2">
                <Terminal size={14} style={{ color: 'var(--acm-accent)' }} />
                <span className="label">Execution log</span>
                <span style={{ color: 'var(--acm-fg-4)', fontSize: '12px' }}>· last 60m</span>
              </div>
              {executionList.length > 0 && (
                <span className="mono" style={{ fontSize: '11px', color: 'var(--acm-fg-4)' }}>
                  {executionList.length} runs
                </span>
              )}
            </div>

            {executionsLoading ? (
              <div className="px-4 py-6 space-y-3">
                {[1, 2, 3, 4, 5].map((i) => (
                  <div
                    key={i}
                    style={{
                      height: 40,
                      background: 'var(--acm-elev)',
                      borderRadius: 6,
                      opacity: 0.4,
                      animation: 'acm-pulse 1.8s ease-in-out infinite',
                    }}
                  />
                ))}
              </div>
            ) : executionList.length === 0 ? (
              <div
                className="flex flex-col items-center justify-center"
                style={{ padding: '48px 32px', textAlign: 'center' }}
              >
                <Terminal size={36} style={{ color: 'var(--acm-fg-4)', marginBottom: 12 }} />
                <h3 className="text-base font-semibold mb-1" style={{ color: 'var(--acm-fg-2)' }}>
                  No executions yet
                </h3>
                <p className="text-sm" style={{ color: 'var(--acm-fg-4)' }}>
                  Executions will appear here when tools are used.
                </p>
              </div>
            ) : (
              <div className="acm-scroll" style={{ maxHeight: 600, overflowY: 'auto' }}>
                {executionList.map((execution) => (
                  <ExecutionRow key={execution.id} execution={execution} />
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </AppLayout>
  );
}
