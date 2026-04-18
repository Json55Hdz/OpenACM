'use client';

import React, { useState, useRef, useCallback, useEffect, Suspense } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import {
  Plus, Trash2, Play, Pause, Clock, CheckCircle2, AlertCircle,
  Loader2, Users, ListTodo, FileText, X, Upload, ChevronRight,
  ArrowLeft, MessageSquare, ChevronDown, ChevronUp, Edit2, Check, Cpu, Bot,
  Send, User, Radio, ArrowRight, Sparkles, XCircle, Activity, HelpCircle,
} from 'lucide-react';
import { AppLayout } from '@/components/layout/app-layout';
import { useAuthStore } from '@/stores/auth-store';
import { useAPI } from '@/hooks/use-api';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Bug } from 'lucide-react';

// ─── Types ────────────────────────────────────────────────────────────────────

interface Swarm {
  id: number;
  name: string;
  goal: string;
  status: 'draft' | 'planning' | 'planned' | 'running' | 'paused' | 'idle' | 'completed' | 'failed';
  global_model: string | null;
  worker_count: number;
  task_count: number;
  created_at: string;
}

interface Worker {
  id: number;
  swarm_id: number;
  name: string;
  role: string;
  description: string;
  system_prompt: string;
  model: string | null;
  allowed_tools: string;
  status: 'idle' | 'busy' | 'done' | 'failed';
  workspace_path: string;
}

interface Task {
  id: number;
  worker_id: number | null;
  worker_name: string | null;
  title: string;
  description: string;
  depends_on: string;
  status: 'pending' | 'running' | 'completed' | 'failed' | 'waiting';
  result: string | null;
}

interface SwarmMessage {
  id: number;
  from_worker_name: string | null;
  to_worker_name: string | null;
  message_type: string;
  content: string;
  created_at: string;
}

interface SwarmDetail extends Swarm {
  shared_context: string;
  context_files: string;
  workers: Worker[];
  tasks: Task[];
}

// ─── Status helpers ───────────────────────────────────────────────────────────

const STATUS_COLOR: Record<string, string> = {
  draft:     'bg-slate-700 text-slate-300',
  planning:  'bg-blue-900/50 text-blue-300',
  planned:   'bg-yellow-900/50 text-yellow-300',
  running:   'bg-green-900/50 text-green-300',
  paused:    'bg-orange-900/50 text-orange-300',
  idle:      'bg-purple-900/50 text-purple-300',
  completed: 'bg-emerald-900/50 text-emerald-300',
  failed:    'bg-red-900/50 text-red-300',
};

const TASK_STATUS_COLOR: Record<string, string> = {
  pending:   'bg-slate-700/60 text-slate-400',
  running:   'bg-blue-900/50 text-blue-300',
  completed: 'bg-emerald-900/50 text-emerald-300',
  failed:    'bg-red-900/50 text-red-300',
  waiting:   'bg-yellow-900/50 text-yellow-300',
};

const WORKER_STATUS_DOT: Record<string, string> = {
  idle:   'bg-slate-500',
  busy:   'bg-blue-400 animate-pulse',
  done:   'bg-emerald-400',
  failed: 'bg-red-400',
};

const SWARM_STATUS_LABEL: Record<string, string> = {
  draft: 'text-slate-400', planning: 'text-blue-400', planned: 'text-yellow-400',
  running: 'text-green-400', paused: 'text-orange-400', idle: 'text-purple-400',
  completed: 'text-emerald-400', failed: 'text-red-400',
};

// ─── Create Swarm Modal ───────────────────────────────────────────────────────

function CreateSwarmModal({ onClose, onCreated }: { onClose: () => void; onCreated: (id: number) => void }) {
  const { fetchAPI } = useAPI();
  const token = useAuthStore(s => s.token);
  const [name, setName] = useState('');
  const [goal, setGoal] = useState('');
  const [globalModel, setGlobalModel] = useState('');
  const [files, setFiles] = useState<File[]>([]);
  const [isDragging, setIsDragging] = useState(false);
  const [step, setStep] = useState<'form' | 'planning'>('form');
  const [error, setError] = useState('');
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    setFiles(prev => [...prev, ...Array.from(e.dataTransfer.files)]);
  }, []);

  const handleSubmit = async () => {
    if (!goal.trim()) { setError('Goal is required'); return; }
    setError('');
    setStep('planning');
    try {
      const fd = new FormData();
      fd.append('name', name || 'New Swarm');
      fd.append('goal', goal);
      if (globalModel) fd.append('global_model', globalModel);
      for (const f of files) fd.append('files', f);

      const headers: Record<string, string> = {};
      if (token) headers['Authorization'] = `Bearer ${token}`;
      const createRes = await fetch('/api/swarms', { method: 'POST', body: fd, headers });
      if (!createRes.ok) throw new Error(`HTTP ${createRes.status}`);
      const swarm: Swarm = await createRes.json();

      const planned = await fetchAPI(`/api/swarms/${swarm.id}/plan`, { method: 'POST', body: JSON.stringify({}) });
      onCreated(planned.id);
    } catch (e: any) {
      setError(e.message || 'Failed to create swarm');
      setStep('form');
    }
  };

  return (
    <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50 p-4">
      <div className="bg-slate-900 border border-slate-700 rounded-xl w-full max-w-2xl shadow-2xl">
        <div className="flex items-center justify-between p-5 border-b border-slate-700">
          <h2 className="text-lg font-semibold text-white">New Swarm</h2>
          <button onClick={onClose}><X size={20} className="text-slate-400 hover:text-white" /></button>
        </div>
        {step === 'planning' ? (
          <div className="p-8 flex flex-col items-center gap-4">
            <Loader2 size={40} className="animate-spin text-blue-400" />
            <p className="text-slate-300 font-medium">Planning your swarm team...</p>
            <p className="text-slate-500 text-sm text-center">The AI is designing the optimal team of workers for your goal.</p>
          </div>
        ) : (
          <div className="p-5 space-y-4">
            {error && <div className="bg-red-900/30 border border-red-700/50 rounded-lg p-3 text-red-300 text-sm">{error}</div>}
            <div>
              <label className="block text-sm font-medium text-slate-300 mb-1">Swarm Name</label>
              <input value={name} onChange={e => setName(e.target.value)} placeholder="e.g. Build REST API"
                className="w-full bg-slate-800 border border-slate-600 rounded-lg px-3 py-2 text-white placeholder-slate-500 focus:outline-none focus:border-blue-500" />
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-300 mb-1">Goal <span className="text-red-400">*</span></label>
              <textarea value={goal} onChange={e => setGoal(e.target.value)}
                placeholder="Describe what you want the swarm to accomplish in detail..." rows={4}
                className="w-full bg-slate-800 border border-slate-600 rounded-lg px-3 py-2 text-white placeholder-slate-500 focus:outline-none focus:border-blue-500 resize-none" />
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-300 mb-1">Global Model (optional)</label>
              <input value={globalModel} onChange={e => setGlobalModel(e.target.value)}
                placeholder="e.g. anthropic/claude-opus-4-6 (leave blank for system default)"
                className="w-full bg-slate-800 border border-slate-600 rounded-lg px-3 py-2 text-white placeholder-slate-500 focus:outline-none focus:border-blue-500" />
              <p className="text-xs text-slate-500 mt-1">Workers without a specific model will use this. Per-worker models can be set later.</p>
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-300 mb-1">Context Files (optional)</label>
              <div onDrop={handleDrop} onDragOver={e => { e.preventDefault(); setIsDragging(true); }}
                onDragLeave={() => setIsDragging(false)} onClick={() => fileInputRef.current?.click()}
                className={`border-2 border-dashed rounded-lg p-6 text-center cursor-pointer transition-colors ${isDragging ? 'border-blue-400 bg-blue-900/20' : 'border-slate-600 hover:border-slate-500'}`}>
                <Upload size={24} className="mx-auto text-slate-400 mb-2" />
                <p className="text-slate-400 text-sm">Drop files here or click to browse</p>
                <p className="text-slate-600 text-xs mt-1">Code, docs, specs — anything the team should understand</p>
                <input ref={fileInputRef} type="file" multiple className="hidden"
                  onChange={e => setFiles(prev => [...prev, ...Array.from(e.target.files || [])])} />
              </div>
              {files.length > 0 && (
                <ul className="mt-2 space-y-1">
                  {files.map((f, i) => (
                    <li key={i} className="flex items-center gap-2 text-sm text-slate-300">
                      <FileText size={14} className="text-slate-400" />
                      <span className="flex-1 truncate">{f.name}</span>
                      <span className="text-slate-500 text-xs">{(f.size / 1024).toFixed(1)}kb</span>
                      <button onClick={() => setFiles(prev => prev.filter((_, j) => j !== i))}
                        className="text-slate-500 hover:text-red-400"><X size={14} /></button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
            <div className="flex gap-3 pt-2">
              <button onClick={onClose} className="flex-1 py-2 rounded-lg border border-slate-600 text-slate-300 hover:bg-slate-800 transition-colors">Cancel</button>
              <button onClick={handleSubmit} disabled={!goal.trim()}
                className="flex-1 py-2 rounded-lg bg-blue-600 hover:bg-blue-500 disabled:opacity-50 disabled:cursor-not-allowed text-white font-medium transition-colors">
                Plan Swarm
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// ─── Worker Card ──────────────────────────────────────────────────────────────

function WorkerCard({ worker, swarmId, onUpdate }: { worker: Worker; swarmId: number; onUpdate: () => void }) {
  const { fetchAPI } = useAPI();
  const [editModel, setEditModel] = useState(false);
  const [modelVal, setModelVal] = useState(worker.model || '');
  const [expanded, setExpanded] = useState(false);

  const saveModel = async () => {
    await fetchAPI(`/api/swarms/${swarmId}/workers/${worker.id}`, {
      method: 'PUT', body: JSON.stringify({ model: modelVal || null }),
    });
    setEditModel(false);
    onUpdate();
  };

  return (
    <div className={`bg-slate-800/50 border rounded-xl p-4 transition-colors ${worker.status === 'busy' ? 'border-blue-600/50' : 'border-slate-700'}`}>
      <div className="flex items-start gap-3">
        <div className="w-9 h-9 rounded-lg bg-slate-700 flex items-center justify-center flex-shrink-0">
          <Bot size={18} className="text-slate-300" />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="font-semibold text-white text-sm">{worker.name}</span>
            <span className={`text-xs px-2 py-0.5 rounded-full ${worker.role === 'orchestrator' ? 'bg-purple-900/50 text-purple-300' : 'bg-slate-700 text-slate-400'}`}>
              {worker.role}
            </span>
            <span className={`w-2 h-2 rounded-full ml-auto ${WORKER_STATUS_DOT[worker.status] || WORKER_STATUS_DOT.idle}`} />
            <span className="text-xs text-slate-500">{worker.status}</span>
          </div>
          <p className="text-slate-400 text-xs mt-1">{worker.description}</p>
          <div className="flex items-center gap-2 mt-2">
            <Cpu size={12} className="text-slate-500" />
            {editModel ? (
              <div className="flex items-center gap-1 flex-1">
                <input value={modelVal} onChange={e => setModelVal(e.target.value)}
                  placeholder="e.g. anthropic/claude-opus-4-6"
                  className="flex-1 bg-slate-700 border border-slate-600 rounded px-2 py-1 text-xs text-white focus:outline-none focus:border-blue-500" autoFocus />
                <button onClick={saveModel} className="text-green-400 hover:text-green-300"><Check size={14} /></button>
                <button onClick={() => { setEditModel(false); setModelVal(worker.model || ''); }} className="text-slate-400 hover:text-slate-300"><X size={14} /></button>
              </div>
            ) : (
              <button onClick={() => setEditModel(true)}
                className="flex items-center gap-1 text-xs text-slate-500 hover:text-slate-300 transition-colors group">
                <span className="font-mono">{worker.model || 'system default'}</span>
                <Edit2 size={11} className="opacity-0 group-hover:opacity-100 transition-opacity" />
              </button>
            )}
          </div>
        </div>
      </div>
      <button onClick={() => setExpanded(v => !v)} className="flex items-center gap-1 text-xs text-slate-600 hover:text-slate-400 mt-3 transition-colors">
        {expanded ? <ChevronUp size={12} /> : <ChevronDown size={12} />} System prompt
      </button>
      {expanded && (
        <pre className="mt-2 text-xs text-slate-400 bg-slate-900 rounded-lg p-3 overflow-auto max-h-40 whitespace-pre-wrap">{worker.system_prompt}</pre>
      )}
    </div>
  );
}

// ─── Task Row ─────────────────────────────────────────────────────────────────

function TaskRow({ task }: { task: Task }) {
  const [expanded, setExpanded] = useState(false);
  return (
    <div className={`border rounded-lg p-3 ${task.status === 'running' ? 'border-blue-600/50 bg-blue-900/10' : task.status === 'waiting' ? 'border-yellow-600/40 bg-yellow-900/10' : 'border-slate-700 bg-slate-800/30'}`}>
      <div className="flex items-start gap-3">
        <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium flex-shrink-0 ${TASK_STATUS_COLOR[task.status] || ''}`}>
          {task.status === 'running' && <Loader2 size={10} className="animate-spin" />}
          {task.status === 'completed' && <CheckCircle2 size={10} />}
          {task.status === 'failed' && <AlertCircle size={10} />}
          {task.status === 'pending' && <Clock size={10} />}
          {task.status === 'waiting' && <HelpCircle size={10} />}
          {task.status}
        </span>
        <div className="flex-1 min-w-0">
          <p className="text-white text-sm font-medium">{task.title}</p>
          {task.worker_name && <p className="text-slate-500 text-xs mt-0.5">→ {task.worker_name}</p>}
        </div>
        {task.result && (
          <button onClick={() => setExpanded(v => !v)} className="text-slate-500 hover:text-slate-300">
            {expanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
          </button>
        )}
      </div>
      {expanded && task.result && (
        <div className="mt-2 text-xs text-slate-300 bg-slate-900 rounded-lg p-3 max-h-64 overflow-auto whitespace-pre-wrap">{task.result}</div>
      )}
    </div>
  );
}

// ─── Shared Markdown renderer ─────────────────────────────────────────────────

function SwarmMarkdown({ content, textColor }: { content: string; textColor: string }) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      components={{
        p: ({ children }) => <p className={`mb-1.5 last:mb-0 leading-relaxed text-sm ${textColor}`}>{children}</p>,
        h1: ({ children }) => <h1 className="text-base font-bold text-white mt-3 mb-1 first:mt-0">{children}</h1>,
        h2: ({ children }) => <h2 className="text-sm font-semibold text-white mt-2 mb-1 first:mt-0">{children}</h2>,
        h3: ({ children }) => <h3 className="text-sm font-semibold text-slate-200 mt-1.5 mb-0.5 first:mt-0">{children}</h3>,
        strong: ({ children }) => <strong className="font-semibold text-white">{children}</strong>,
        em: ({ children }) => <em className="italic text-slate-300">{children}</em>,
        ul: ({ children }) => <ul className="list-disc list-inside space-y-0.5 my-1.5 pl-2 text-sm">{children}</ul>,
        ol: ({ children }) => <ol className="list-decimal list-inside space-y-0.5 my-1.5 pl-2 text-sm">{children}</ol>,
        li: ({ children }) => <li className={`text-sm ${textColor}`}>{children}</li>,
        code: ({ children, className }) => {
          const isBlock = className?.includes('language-');
          return isBlock
            ? <code className="block bg-slate-950 text-green-300 rounded-lg px-3 py-2 my-1.5 text-xs font-mono overflow-x-auto whitespace-pre">{children}</code>
            : <code className="bg-slate-800 text-blue-300 rounded px-1 py-0.5 text-xs font-mono">{children}</code>;
        },
        pre: ({ children }) => <>{children}</>,
        blockquote: ({ children }) => <blockquote className="border-l-2 border-slate-500 pl-2 my-1.5 text-slate-400 italic text-sm">{children}</blockquote>,
        hr: () => <hr className="border-slate-700 my-2" />,
      }}
    >
      {content}
    </ReactMarkdown>
  );
}

// ─── Activity Feed Entry ──────────────────────────────────────────────────────

function ActivityEntry({ msg, onReply }: { msg: SwarmMessage; onReply?: (prefix: string) => void }) {
  const [expanded, setExpanded] = useState(false);
  const type = msg.message_type;

  const cfg: Record<string, { border: string; bg: string; icon: React.ReactNode; label: () => React.ReactNode; textColor: string; collapsible?: boolean }> = {
    user: {
      border: 'border-blue-600/40', bg: 'bg-blue-900/10', textColor: 'text-blue-200',
      icon: <User size={13} className="text-blue-400" />,
      label: () => <span className="font-semibold text-blue-400">You</span>,
    },
    question: {
      border: 'border-yellow-500/60', bg: 'bg-yellow-900/20', textColor: 'text-yellow-100',
      icon: <HelpCircle size={13} className="text-yellow-400" />,
      label: () => <span className="font-semibold text-yellow-400">{msg.from_worker_name || 'Worker'} asks</span>,
    },
    task_result: {
      border: 'border-emerald-600/30', bg: 'bg-emerald-900/10', textColor: 'text-emerald-200',
      icon: <CheckCircle2 size={13} className="text-emerald-400" />,
      label: () => <span className="font-semibold text-emerald-400">{msg.from_worker_name || 'Worker'}</span>,
      collapsible: true,
    },
    task_failed: {
      border: 'border-red-600/30', bg: 'bg-red-900/10', textColor: 'text-red-300',
      icon: <XCircle size={13} className="text-red-400" />,
      label: () => <span className="font-semibold text-red-400">{msg.from_worker_name || 'Worker'}</span>,
    },
    task_waiting: {
      border: 'border-yellow-600/40', bg: 'bg-yellow-900/10', textColor: 'text-yellow-200',
      icon: <HelpCircle size={13} className="text-yellow-400" />,
      label: () => <span className="font-semibold text-yellow-400">{msg.from_worker_name || 'Worker'} — waiting</span>,
    },
    bug_report: {
      border: 'border-red-500/60', bg: 'bg-red-900/20', textColor: 'text-red-100',
      icon: <Bug size={13} className="text-red-400" />,
      label: () => <span className="font-semibold text-red-400">{msg.from_worker_name || 'QA'} — bug found</span>,
    },
    synthesis: {
      border: 'border-amber-500/40', bg: 'bg-amber-900/10', textColor: 'text-amber-100',
      icon: <Sparkles size={13} className="text-amber-400" />,
      label: () => <span className="font-semibold text-amber-400">Final Summary</span>,
      collapsible: true,
    },
    broadcast: {
      border: 'border-violet-600/30', bg: 'bg-violet-900/10', textColor: 'text-violet-200',
      icon: <Radio size={13} className="text-violet-400" />,
      label: () => <span className="font-semibold text-violet-400">{msg.from_worker_name || 'Worker'}</span>,
    },
    message: {
      border: 'border-slate-600/40', bg: 'bg-slate-800/40', textColor: 'text-slate-300',
      icon: <ArrowRight size={13} className="text-slate-400" />,
      label: () => (
        <><span className="font-semibold text-slate-300">{msg.from_worker_name || '?'}</span>
        <ArrowRight size={11} className="text-slate-500 mx-0.5" />
        <span className="font-semibold text-slate-300">{msg.to_worker_name || '?'}</span></>
      ),
    },
  };

  const c = cfg[type] ?? cfg['message'];
  const isCollapsible = c.collapsible && msg.content.length > 400;
  const displayContent = isCollapsible && !expanded ? msg.content.slice(0, 400) + '…' : msg.content;

  // Bug reports are stored as JSON — render as a structured card
  if (type === 'bug_report') {
    let bug: { title?: string; description?: string; severity?: string; fixer?: string; cycle?: number; fix_task?: string; retest_task?: string } = {};
    try { bug = JSON.parse(msg.content); } catch { bug = { title: msg.content }; }
    const sevColor: Record<string, string> = {
      critical: 'bg-red-600 text-white',
      high:     'bg-orange-500 text-white',
      medium:   'bg-yellow-500 text-black',
      low:      'bg-blue-500 text-white',
    };
    const sev = (bug.severity || 'medium').toLowerCase();
    return (
      <div className="border border-red-500/60 bg-red-900/20 rounded-lg p-3">
        <div className="flex items-center gap-1.5 mb-2 text-xs text-slate-500">
          <Bug size={13} className="text-red-400" />
          <span className="font-semibold text-red-400">{msg.from_worker_name || 'QA'} — bug found</span>
          <span className={`ml-1 px-1.5 py-0.5 rounded text-xs font-bold ${sevColor[sev] || sevColor.medium}`}>{sev.toUpperCase()}</span>
          {bug.cycle && bug.cycle > 1 && <span className="text-slate-500">cycle {bug.cycle}</span>}
          <span className="ml-auto text-slate-600">{new Date(msg.created_at).toLocaleTimeString()}</span>
        </div>
        <p className="text-sm font-semibold text-red-200 mb-1">{bug.title}</p>
        {bug.description && <p className="text-xs text-red-300/80 mb-2 whitespace-pre-wrap">{bug.description}</p>}
        <div className="flex gap-3 text-xs text-slate-400">
          {bug.fixer && <span>🔧 Fix → <span className="text-slate-300">{bug.fixer}</span></span>}
          {bug.retest_task && <span>🔁 Re-test scheduled</span>}
        </div>
      </div>
    );
  }

  return (
    <div className={`border rounded-lg p-3 ${c.border} ${c.bg}`}>
      <div className="flex items-center gap-1.5 mb-1.5 text-xs text-slate-500">
        {c.icon}
        {c.label()}
        <span className="ml-auto text-slate-600">{new Date(msg.created_at).toLocaleTimeString()}</span>
      </div>
      <SwarmMarkdown content={displayContent} textColor={c.textColor} />
      <div className="flex items-center gap-2 mt-1.5">
        {isCollapsible && (
          <button onClick={() => setExpanded(x => !x)}
            className="text-xs text-slate-500 hover:text-slate-300 transition-colors">
            {expanded ? '↑ collapse' : '↓ show full output'}
          </button>
        )}
        {(type === 'question' || type === 'task_waiting') && onReply && (
          <button
            onClick={() => onReply(`@${msg.from_worker_name || 'Worker'}: `)}
            className="ml-auto flex items-center gap-1 px-2 py-0.5 rounded text-xs bg-yellow-700/40 hover:bg-yellow-600/50 text-yellow-200 transition-colors"
          >
            <Send size={10} /> Reply
          </button>
        )}
      </div>
    </div>
  );
}

// ─── Swarm Detail ─────────────────────────────────────────────────────────────

function SwarmDetail({ swarmId, onBack }: { swarmId: number; onBack: () => void }) {
  const { fetchAPI } = useAPI();
  const token = useAuthStore(s => s.token);
  const qc = useQueryClient();
  const wsRef = useRef<WebSocket | null>(null);
  const [activeTab, setActiveTab] = useState<'workers' | 'tasks' | 'messages' | 'context'>('workers');
  const [userMsg, setUserMsg] = useState('');
  const [sending, setSending] = useState(false);
  const msgEndRef = useRef<HTMLDivElement>(null);
  const prevMsgCountRef = useRef(0);
  const [unseenQuestions, setUnseenQuestions] = useState(0);

  const { data: swarm, refetch } = useQuery<SwarmDetail>({
    queryKey: ['swarm', swarmId],
    queryFn: () => fetchAPI(`/api/swarms/${swarmId}`),
    refetchInterval: 2000,
  });

  const { data: messages = [], refetch: refetchMsgs } = useQuery<SwarmMessage[]>({
    queryKey: ['swarm-messages', swarmId],
    queryFn: () => fetchAPI(`/api/swarms/${swarmId}/messages`),
    refetchInterval: 3000,
  });

  useEffect(() => {
    const proto = window.location.protocol === 'https:' ? 'wss' : 'ws';
    const ws = new WebSocket(`${proto}://${window.location.host}/ws/swarms/${swarmId}?token=${token || ''}`);
    wsRef.current = ws;
    ws.onmessage = () => { refetch(); refetchMsgs(); };
    return () => ws.close();
  }, [swarmId, token]);

  // Track new question messages and badge the Activity tab when not viewing it
  useEffect(() => {
    const newCount = messages.length;
    if (newCount > prevMsgCountRef.current) {
      const newMsgs = messages.slice(prevMsgCountRef.current);
      const newQuestions = newMsgs.filter(m => m.message_type === 'question').length;
      if (newQuestions > 0 && activeTab !== 'messages') {
        setUnseenQuestions(q => q + newQuestions);
      }
    }
    prevMsgCountRef.current = newCount;
  }, [messages]);

  // Clear badge when user opens Activity tab
  useEffect(() => {
    if (activeTab === 'messages') setUnseenQuestions(0);
  }, [activeTab]);

  const startMutation = useMutation({
    mutationFn: () => fetchAPI(`/api/swarms/${swarmId}/start`, { method: 'POST', body: JSON.stringify({}) }),
    onSuccess: () => { refetch(); qc.invalidateQueries({ queryKey: ['swarms'] }); },
  });
  const stopMutation = useMutation({
    mutationFn: () => fetchAPI(`/api/swarms/${swarmId}/stop`, { method: 'POST', body: JSON.stringify({}) }),
    onSuccess: () => { refetch(); qc.invalidateQueries({ queryKey: ['swarms'] }); },
  });
  const completeMutation = useMutation({
    mutationFn: () => fetchAPI(`/api/swarms/${swarmId}/complete`, { method: 'POST', body: JSON.stringify({}) }),
    onSuccess: () => { refetch(); qc.invalidateQueries({ queryKey: ['swarms'] }); },
  });
  const deleteMutation = useMutation({
    mutationFn: () => fetchAPI(`/api/swarms/${swarmId}`, { method: 'DELETE' }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['swarms'] }); onBack(); },
  });

  const sendMessage = async () => {
    const text = userMsg.trim();
    if (!text || sending) return;
    setSending(true);
    try {
      await fetchAPI(`/api/swarms/${swarmId}/message`, {
        method: 'POST', body: JSON.stringify({ message: text }),
      });
      setUserMsg('');
      setTimeout(() => { refetchMsgs(); setActiveTab('messages'); }, 300);
    } finally {
      setSending(false);
    }
  };

  const handleMsgKey = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
  };

  if (!swarm) return <div className="flex items-center justify-center h-64"><Loader2 size={32} className="animate-spin text-blue-400" /></div>;

  const tasks = swarm.tasks || [];
  const running = tasks.filter(t => t.status === 'running');
  const pending = tasks.filter(t => t.status === 'pending');
  const waiting = tasks.filter(t => t.status === 'waiting');
  const completed = tasks.filter(t => t.status === 'completed');
  const failed = tasks.filter(t => t.status === 'failed');
  const orderedTasks = [...running, ...waiting, ...pending, ...completed, ...failed];
  const contextFiles = JSON.parse(swarm.context_files || '[]') as string[];
  const canStart = ['planned', 'paused', 'idle'].includes(swarm.status);
  const canStop = swarm.status === 'running';
  const canComplete = ['idle', 'paused', 'planned'].includes(swarm.status);

  return (
    <div>
      <div className="flex items-start gap-4 mb-6">
        <button onClick={onBack} className="mt-1 text-slate-400 hover:text-white transition-colors"><ArrowLeft size={20} /></button>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-3 flex-wrap">
            <h1 className="text-2xl font-bold text-white truncate">{swarm.name}</h1>
            <span className={`text-sm font-medium ${SWARM_STATUS_LABEL[swarm.status] || 'text-slate-400'}`}>
              {swarm.status === 'running' && <Loader2 size={14} className="inline animate-spin mr-1" />}
              {swarm.status}
            </span>
          </div>
          <div className="text-slate-400 text-sm mt-1 prose-swarm">
            <SwarmMarkdown content={swarm.goal} textColor="text-slate-400" />
          </div>
          {swarm.global_model && <p className="text-slate-500 text-xs mt-1 font-mono">Global model: {swarm.global_model}</p>}
        </div>
        <div className="flex items-center gap-2 flex-shrink-0">
          {canStart && (
            <button onClick={() => startMutation.mutate()} disabled={startMutation.isPending}
              className="flex items-center gap-2 px-4 py-2 bg-green-600 hover:bg-green-500 disabled:opacity-50 text-white rounded-lg transition-colors text-sm font-medium">
              {startMutation.isPending ? <Loader2 size={15} className="animate-spin" /> : <Play size={15} />} Start
            </button>
          )}
          {canStop && (
            <button onClick={() => stopMutation.mutate()} disabled={stopMutation.isPending}
              className="flex items-center gap-2 px-4 py-2 bg-orange-600 hover:bg-orange-500 disabled:opacity-50 text-white rounded-lg transition-colors text-sm font-medium">
              <Pause size={15} /> Pause
            </button>
          )}
          {canComplete && (
            <button onClick={() => { if (confirm('Mark this swarm as completed?')) completeMutation.mutate(); }}
              disabled={completeMutation.isPending}
              className="flex items-center gap-2 px-4 py-2 bg-emerald-700 hover:bg-emerald-600 disabled:opacity-50 text-white rounded-lg transition-colors text-sm font-medium">
              {completeMutation.isPending ? <Loader2 size={15} className="animate-spin" /> : <CheckCircle2 size={15} />} Finalizar
            </button>
          )}
          <button onClick={() => { if (confirm('Delete this swarm and all its data?')) deleteMutation.mutate(); }}
            className="p-2 text-slate-400 hover:text-red-400 hover:bg-red-900/20 rounded-lg transition-colors">
            <Trash2 size={16} />
          </button>
        </div>
      </div>

      <div className="grid grid-cols-4 gap-3 mb-6">
        {[
          { label: 'Workers', value: (swarm.workers || []).length, icon: <Users size={15} /> },
          { label: 'Tasks', value: tasks.length, icon: <ListTodo size={15} /> },
          { label: 'Done', value: completed.length, icon: <CheckCircle2 size={15} className="text-emerald-400" /> },
          waiting.length > 0
            ? { label: 'Waiting', value: waiting.length, icon: <HelpCircle size={15} className="text-yellow-400" /> }
            : { label: 'Activity', value: messages.length, icon: <Activity size={15} /> },
        ].map(s => (
          <div key={s.label} className={`bg-slate-800/50 border rounded-xl p-3 flex items-center gap-3 ${s.label === 'Waiting' ? 'border-yellow-600/40' : 'border-slate-700'}`}>
            <span className="text-slate-400">{s.icon}</span>
            <div><p className={`text-xl font-bold ${s.label === 'Waiting' ? 'text-yellow-300' : 'text-white'}`}>{s.value}</p><p className="text-xs text-slate-500">{s.label}</p></div>
          </div>
        ))}
      </div>

      <div className="flex gap-1 mb-4 bg-slate-800/50 rounded-lg p-1 border border-slate-700">
        {([
          { id: 'workers', label: 'Workers', icon: <Users size={15} /> },
          { id: 'tasks', label: 'Tasks', icon: <ListTodo size={15} />, badge: waiting.length > 0 ? waiting.length : 0 },
          { id: 'messages', label: 'Activity', icon: <Activity size={15} />, badge: unseenQuestions },
          { id: 'context', label: 'Context', icon: <FileText size={15} /> },
        ] as const).map(tab => (
          <button key={tab.id} onClick={() => setActiveTab(tab.id)}
            className={`flex-1 flex items-center justify-center gap-2 py-2 px-3 rounded-md text-sm font-medium transition-colors ${activeTab === tab.id ? 'bg-slate-700 text-white' : 'text-slate-400 hover:text-slate-200'}`}>
            {tab.icon}{tab.label}
            {'badge' in tab && tab.badge > 0 && (
              <span className="ml-0.5 bg-yellow-500 text-black text-xs font-bold rounded-full w-4 h-4 flex items-center justify-center leading-none">
                {tab.badge > 9 ? '9+' : tab.badge}
              </span>
            )}
          </button>
        ))}
      </div>

      {activeTab === 'workers' && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {(swarm.workers || []).length === 0
            ? <div className="col-span-2 text-center py-10 text-slate-500">No workers yet.</div>
            : (swarm.workers || []).map(w => <WorkerCard key={w.id} worker={w} swarmId={swarmId} onUpdate={refetch} />)
          }
        </div>
      )}

      {activeTab === 'tasks' && (
        <div className="space-y-2">
          {orderedTasks.length === 0
            ? <div className="text-center py-10 text-slate-500">No tasks yet.</div>
            : orderedTasks.map(t => <TaskRow key={t.id} task={t} />)
          }
        </div>
      )}

      {activeTab === 'messages' && (
        <div className="flex flex-col gap-2">
          {messages.length === 0
            ? (
              <div className="flex flex-col items-center justify-center py-12 text-slate-500">
                <Activity size={32} className="mb-3" />
                <p className="text-sm">No activity yet. Start the swarm to see the feed.</p>
              </div>
            )
            : messages.map(m => (
                <ActivityEntry
                  key={m.id}
                  msg={m}
                  onReply={prefix => {
                    setUserMsg(prefix);
                    setActiveTab('messages');
                    setTimeout(() => document.querySelector<HTMLTextAreaElement>('textarea[placeholder*="feedback"]')?.focus(), 50);
                  }}
                />
              ))
          }
          <div ref={msgEndRef} />
        </div>
      )}

      {activeTab === 'context' && (
        contextFiles.length === 0 && !swarm.shared_context
          ? <div className="text-center py-10 text-slate-500">No context files provided.</div>
          : <div className="space-y-3">
            {contextFiles.length > 0 && (
              <div className="bg-slate-800/50 border border-slate-700 rounded-xl p-4">
                <h3 className="text-sm font-semibold text-slate-300 mb-2">Uploaded Files</h3>
                <ul className="space-y-1">{contextFiles.map((f, i) => <li key={i} className="flex items-center gap-2 text-sm text-slate-400"><FileText size={14} />{f}</li>)}</ul>
              </div>
            )}
            {swarm.shared_context && (
              <div className="bg-slate-800/50 border border-slate-700 rounded-xl p-4">
                <h3 className="text-sm font-semibold text-slate-300 mb-2">Shared Context</h3>
                <pre className="text-xs text-slate-400 whitespace-pre-wrap max-h-96 overflow-auto">{swarm.shared_context}</pre>
              </div>
            )}
          </div>
      )}

      {/* ── User message input ── always visible at the bottom ── */}
      <div className="mt-6 pt-4 border-t border-slate-700/50">
        <p className="text-xs text-slate-500 mb-2">
          Send feedback, new instructions, or ask for changes — the orchestrator will react and create tasks if needed.
        </p>
        <div className="flex gap-2">
          <textarea
            value={userMsg}
            onChange={e => setUserMsg(e.target.value)}
            onKeyDown={handleMsgKey}
            placeholder="Give feedback, request changes, add instructions… (Enter to send)"
            rows={2}
            className="flex-1 bg-slate-800 border border-slate-600 rounded-lg px-3 py-2 text-white placeholder-slate-500 text-sm focus:outline-none focus:border-blue-500 resize-none"
          />
          <button
            onClick={sendMessage}
            disabled={!userMsg.trim() || sending}
            className="px-4 bg-blue-600 hover:bg-blue-500 disabled:opacity-40 disabled:cursor-not-allowed text-white rounded-lg transition-colors flex items-center gap-2 self-end pb-2 pt-2"
          >
            {sending ? <Loader2 size={16} className="animate-spin" /> : <Send size={16} />}
          </button>
        </div>
      </div>
    </div>
  );
}

// ─── Swarm Card (list view) ───────────────────────────────────────────────────

function SwarmCard({ swarm, onSelect, onDelete }: { swarm: Swarm; onSelect: () => void; onDelete: () => void }) {
  return (
    <div onClick={onSelect}
      className="bg-slate-800/50 border border-slate-700 rounded-xl p-5 hover:border-slate-500 hover:bg-slate-800 transition-all cursor-pointer group">
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium ${STATUS_COLOR[swarm.status] || STATUS_COLOR.draft}`}>
              {swarm.status === 'running' && <Loader2 size={12} className="animate-spin" />}
              {swarm.status}
            </span>
            {swarm.global_model && <span className="text-xs text-slate-500 font-mono truncate">{swarm.global_model}</span>}
          </div>
          <h3 className="text-white font-semibold text-base truncate">{swarm.name}</h3>
          <p className="text-slate-400 text-sm mt-1 line-clamp-2">{swarm.goal}</p>
        </div>
        <ChevronRight size={18} className="text-slate-600 group-hover:text-slate-400 transition-colors mt-1 flex-shrink-0" />
      </div>
      <div className="flex items-center gap-4 mt-4 pt-3 border-t border-slate-700">
        <span className="flex items-center gap-1.5 text-xs text-slate-500"><Users size={13} />{swarm.worker_count} worker{swarm.worker_count !== 1 ? 's' : ''}</span>
        <span className="flex items-center gap-1.5 text-xs text-slate-500"><ListTodo size={13} />{swarm.task_count} task{swarm.task_count !== 1 ? 's' : ''}</span>
        <span className="ml-auto text-xs text-slate-600">{new Date(swarm.created_at).toLocaleDateString()}</span>
        <button onClick={e => { e.stopPropagation(); onDelete(); }} className="text-slate-600 hover:text-red-400 transition-colors">
          <Trash2 size={14} />
        </button>
      </div>
    </div>
  );
}

// ─── Inner page (uses useSearchParams — must be inside Suspense) ──────────────

function SwarmsInner() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const { fetchAPI } = useAPI();
  const qc = useQueryClient();
  const [showCreate, setShowCreate] = useState(false);

  const selectedId = searchParams.get('id') ? Number(searchParams.get('id')) : null;

  const { data: swarms = [], isLoading } = useQuery<Swarm[]>({
    queryKey: ['swarms'],
    queryFn: () => fetchAPI('/api/swarms'),
    refetchInterval: 3000,
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) => fetchAPI(`/api/swarms/${id}`, { method: 'DELETE' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['swarms'] }),
  });

  const handleCreated = (id: number) => {
    setShowCreate(false);
    qc.invalidateQueries({ queryKey: ['swarms'] });
    router.push(`/swarms?id=${id}`);
  };

  if (selectedId) {
    return <SwarmDetail swarmId={selectedId} onBack={() => router.push('/swarms')} />;
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-white">Swarms</h1>
          <p className="text-slate-400 text-sm mt-1">Multi-agent teams that collaborate to accomplish complex goals</p>
        </div>
        <button onClick={() => setShowCreate(true)}
          className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white rounded-lg font-medium transition-colors">
          <Plus size={18} /> New Swarm
        </button>
      </div>

      {isLoading ? (
        <div className="flex items-center justify-center py-20"><Loader2 size={32} className="animate-spin text-blue-400" /></div>
      ) : swarms.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-20 text-center">
          <Users size={48} className="text-slate-600 mb-4" />
          <h3 className="text-lg font-semibold text-slate-300 mb-2">No swarms yet</h3>
          <p className="text-slate-500 text-sm mb-6 max-w-sm">Create your first swarm — give it a goal and optional context files, and the AI will design a team of specialized workers.</p>
          <button onClick={() => setShowCreate(true)} className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white rounded-lg transition-colors">
            <Plus size={16} /> Create Swarm
          </button>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {swarms.map(s => (
            <SwarmCard key={s.id} swarm={s}
              onSelect={() => router.push(`/swarms?id=${s.id}`)}
              onDelete={() => deleteMutation.mutate(s.id)} />
          ))}
        </div>
      )}

      {showCreate && <CreateSwarmModal onClose={() => setShowCreate(false)} onCreated={handleCreated} />}
    </div>
  );
}

// ─── Page export ──────────────────────────────────────────────────────────────

export default function SwarmsPage() {
  return (
    <AppLayout>
      <div className="p-6 max-w-5xl mx-auto">
        <Suspense fallback={<div className="flex items-center justify-center py-20"><Loader2 size={32} className="animate-spin text-blue-400" /></div>}>
          <SwarmsInner />
        </Suspense>
      </div>
    </AppLayout>
  );
}
