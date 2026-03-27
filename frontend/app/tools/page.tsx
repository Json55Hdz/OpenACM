'use client';

import { useState } from 'react';
import { AppLayout } from '@/components/layout/app-layout';
import { useTools, useToolExecutions } from '@/hooks/use-api';
import { 
  Wrench, 
  Play, 
  Clock, 
  CheckCircle, 
  XCircle, 
  Loader2,
  ChevronDown,
  ChevronUp,
  Terminal,
  Calendar
} from 'lucide-react';
import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';

function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

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

function ToolCard({ tool }: { tool: Tool }) {
  const [isExpanded, setIsExpanded] = useState(false);
  const params = Object.entries(tool.parameters || {});
  
  return (
    <div className="bg-slate-900 rounded-xl border border-slate-800 p-5 hover:border-slate-700 transition-colors">
      <div className="flex items-start justify-between mb-3">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 bg-blue-600/20 rounded-lg flex items-center justify-center">
            <Wrench size={20} className="text-blue-400" />
          </div>
          <div>
            <h3 className="font-semibold text-white">{tool.name}</h3>
            <p className="text-sm text-slate-500">{params.length} parameters</p>
          </div>
        </div>
        <button
          onClick={() => setIsExpanded(!isExpanded)}
          className="p-1 text-slate-400 hover:text-white"
        >
          {isExpanded ? <ChevronUp size={20} /> : <ChevronDown size={20} />}
        </button>
      </div>
      
      <p className="text-sm text-slate-400 mb-3">{tool.description}</p>
      
      {isExpanded && params.length > 0 && (
        <div className="mt-4 pt-4 border-t border-slate-800">
          <h4 className="text-xs font-medium text-slate-500 uppercase tracking-wider mb-3">
            Parameters
          </h4>
          <div className="space-y-2">
            {params.map(([key, value]) => (
              <div key={key} className="flex items-center gap-2 text-sm">
                <span className="text-blue-400 font-mono">{key}</span>
                <span className="text-slate-600">→</span>
                <span className="text-slate-300">{JSON.stringify(value)}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function ExecutionRow({ execution }: { execution: ToolExecution }) {
  const [showDetails, setShowDetails] = useState(false);
  
  const statusConfig = {
    success: { icon: CheckCircle, color: 'text-green-400', bg: 'bg-green-500/20' },
    error: { icon: XCircle, color: 'text-red-400', bg: 'bg-red-500/20' },
    running: { icon: Loader2, color: 'text-blue-400', bg: 'bg-blue-500/20' },
  };
  
  const config = statusConfig[execution.status];
  const StatusIcon = config.icon;
  
  return (
    <div className="border-b border-slate-800 last:border-b-0">
      <div 
        className="flex items-center gap-4 px-4 py-3 hover:bg-slate-800/50 cursor-pointer transition-colors"
        onClick={() => setShowDetails(!showDetails)}
      >
        <div className={cn("w-8 h-8 rounded-full flex items-center justify-center", config.bg)}>
          <StatusIcon size={16} className={cn(config.color, execution.status === 'running' && "animate-spin")} />
        </div>
        
        <div className="flex-1 min-w-0">
          <p className="text-sm font-medium text-slate-200 truncate">{execution.tool_name}</p>
          <p className="text-xs text-slate-500 truncate">
            {new Date(execution.created_at).toLocaleString()}
          </p>
        </div>
        
        {execution.elapsed_ms && (
          <span className="text-xs text-slate-500">{execution.elapsed_ms}ms</span>
        )}
        
        {showDetails ? <ChevronUp size={16} className="text-slate-500" /> : <ChevronDown size={16} className="text-slate-500" />}
      </div>
      
      {showDetails && (
        <div className="px-4 pb-4 space-y-3">
          <div className="bg-slate-950 rounded-lg p-3">
            <p className="text-xs text-slate-500 uppercase tracking-wider mb-2">Arguments</p>
            <pre className="text-xs text-slate-300 font-mono overflow-x-auto">
              {execution.arguments}
            </pre>
          </div>
          
          <div className="bg-slate-950 rounded-lg p-3">
            <p className="text-xs text-slate-500 uppercase tracking-wider mb-2">Result</p>
            <pre className={cn(
              "text-xs font-mono overflow-x-auto",
              execution.status === 'error' ? "text-red-400" : "text-slate-300"
            )}>
              {execution.result}
            </pre>
          </div>
        </div>
      )}
    </div>
  );
}

export default function ToolsPage() {
  const { data: tools, isLoading: toolsLoading } = useTools();
  const { data: executions, isLoading: executionsLoading } = useToolExecutions();
  const [activeTab, setActiveTab] = useState<'tools' | 'executions'>('tools');
  
  const toolList: Tool[] = tools || [];
  const executionList: ToolExecution[] = executions || [];
  
  return (
    <AppLayout>
      <div className="p-6 lg:p-8">
        {/* Header */}
        <header className="mb-8">
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
            <div>
              <h1 className="text-3xl font-bold text-white">Tools</h1>
              <p className="text-slate-400 mt-1">Manage and monitor available tools</p>
            </div>
          </div>
        </header>
        
        {/* Tabs */}
        <div className="flex gap-2 mb-6">
          <button
            onClick={() => setActiveTab('tools')}
            className={cn(
              "flex items-center gap-2 px-4 py-2 rounded-lg transition-colors",
              activeTab === 'tools' 
                ? "bg-blue-600 text-white" 
                : "bg-slate-800 text-slate-400 hover:text-white"
            )}
          >
            <Wrench size={18} />
            <span>Tools</span>
          </button>
          <button
            onClick={() => setActiveTab('executions')}
            className={cn(
              "flex items-center gap-2 px-4 py-2 rounded-lg transition-colors",
              activeTab === 'executions' 
                ? "bg-blue-600 text-white" 
                : "bg-slate-800 text-slate-400 hover:text-white"
            )}
          >
            <Terminal size={18} />
            <span>Executions</span>
          </button>
        </div>
        
        {/* Tools Grid */}
        {activeTab === 'tools' && (
          <div>
            {toolsLoading ? (
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                {[1, 2, 3, 4, 5, 6].map((i) => (
                  <div key={i} className="bg-slate-900 rounded-xl border border-slate-800 p-5 h-40 animate-pulse" />
                ))}
              </div>
            ) : toolList.length === 0 ? (
              <div className="text-center py-16 bg-slate-900 rounded-xl border border-slate-800">
                <Wrench size={48} className="mx-auto text-slate-600 mb-4" />
                <h3 className="text-lg font-medium text-slate-300 mb-2">No tools available</h3>
                <p className="text-sm text-slate-500">
                  Tools will be loaded automatically from active skills.
                </p>
              </div>
            ) : (
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                {toolList.map((tool) => (
                  <ToolCard key={tool.name} tool={tool} />
                ))}
              </div>
            )}
          </div>
        )}
        
        {/* Executions Table */}
        {activeTab === 'executions' && (
          <div className="bg-slate-900 rounded-xl border border-slate-800">
            <div className="px-4 py-4 border-b border-slate-800">
              <h3 className="text-lg font-semibold text-white">Recent Executions</h3>
              <p className="text-sm text-slate-500">Last 20 tool executions</p>
            </div>
            
            {executionsLoading ? (
              <div className="p-8 space-y-3">
                {[1, 2, 3, 4, 5].map((i) => (
                  <div key={i} className="h-14 bg-slate-800/50 rounded animate-pulse" />
                ))}
              </div>
            ) : executionList.length === 0 ? (
              <div className="text-center py-16">
                <Terminal size={48} className="mx-auto text-slate-600 mb-4" />
                <h3 className="text-lg font-medium text-slate-300 mb-2">No executions yet</h3>
                <p className="text-sm text-slate-500">
                  Executions will appear here when tools are used.
                </p>
              </div>
            ) : (
              <div className="divide-y divide-slate-800">
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
