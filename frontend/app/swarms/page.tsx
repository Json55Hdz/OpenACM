'use client';

import React, { useState, useRef, useCallback, useEffect, Suspense } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import {
  Plus, Trash2, Play, Pause, Clock, CheckCircle2, AlertCircle,
  Loader2, Users, ListTodo, FileText, X, Upload, ChevronRight,
  ArrowLeft, MessageSquare, ChevronDown, ChevronUp, Edit2, Check, Cpu, Bot,
  Send, User, Radio, ArrowRight, Sparkles, XCircle, Activity, HelpCircle, FolderOpen, RotateCcw,
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
  status: 'draft' | 'clarifying' | 'planning' | 'planned' | 'running' | 'paused' | 'idle' | 'completed' | 'failed';
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
  clarification_questions: string;
  clarification_answers: string;
  workers: Worker[];
  tasks: Task[];
}

// ─── Status helpers ───────────────────────────────────────────────────────────

const WORKER_DOT: Record<string, string> = {
  idle:   'dot-idle',
  busy:   'dot-accent acm-pulse',
  done:   'dot-ok',
  failed: 'dot-err',
};

const SWARM_DOT: Record<string, string> = {
  running:    'dot-accent acm-pulse',
  completed:  'dot-ok',
  failed:     'dot-err',
  paused:     'dot-warn',
  draft:      'dot-idle',
  clarifying: 'dot-warn acm-pulse',
  planning:   'dot-accent acm-pulse',
  planned:    'dot-warn',
  idle:       'dot-idle',
};

const TASK_DOT: Record<string, string> = {
  pending:   'dot-idle',
  running:   'dot-accent acm-pulse',
  completed: 'dot-ok',
  failed:    'dot-err',
  waiting:   'dot-warn',
};

// ─── Create Swarm Modal ───────────────────────────────────────────────────────

function CreateSwarmModal({ onClose, onCreated }: { onClose: () => void; onCreated: (id: number) => void }) {
  const { fetchAPI } = useAPI();
  const token = useAuthStore(s => s.token);
  const [name, setName] = useState('');
  const [goal, setGoal] = useState('');
  const [globalModel, setGlobalModel] = useState('');
  const [workingPath, setWorkingPath] = useState('');
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
      if (workingPath) fd.append('working_path', workingPath);
      for (const f of files) fd.append('files', f);

      const headers: Record<string, string> = {};
      if (token) headers['Authorization'] = `Bearer ${token}`;
      const createRes = await fetch('/api/swarms', { method: 'POST', body: fd, headers });
      if (!createRes.ok) throw new Error(`HTTP ${createRes.status}`);
      const swarm: Swarm = await createRes.json();

      await fetchAPI(`/api/swarms/${swarm.id}/clarify`, { method: 'POST', body: JSON.stringify({}) });
      onCreated(swarm.id);
    } catch (e: any) {
      setError(e.message || 'Failed to create swarm');
      setStep('form');
    }
  };

  return (
    <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50 p-4">
      <div className="bg-[var(--acm-base)] border border-[var(--acm-border)] rounded-xl w-full max-w-2xl shadow-2xl">
        <div className="flex items-center justify-between p-5 border-b border-[var(--acm-border)]">
          <h2 className="text-[15px] font-semibold text-[var(--acm-fg)]">New Swarm</h2>
          <button onClick={onClose}>
            <X size={18} className="text-[var(--acm-fg-3)] hover:text-[var(--acm-fg)] transition-colors" />
          </button>
        </div>

        {step === 'planning' ? (
          <div className="p-10 flex flex-col items-center gap-4">
            <Loader2 size={36} className="animate-spin text-[var(--acm-accent)]" />
            <p className="text-[var(--acm-fg)] text-[14px] font-medium">Reviewing your goal and context…</p>
            <p className="text-[var(--acm-fg-4)] text-[12px] text-center">
              The AI is reading your documents and preparing clarifying questions before planning.
            </p>
          </div>
        ) : (
          <div className="p-5 space-y-4">
            {error && (
              <div className="border border-l-2 border-l-[var(--acm-err)] border-[var(--acm-border)] rounded-lg p-3 text-[var(--acm-err)] text-[12px]">
                {error}
              </div>
            )}
            <div>
              <label className="label block mb-2">Swarm Name</label>
              <input
                value={name}
                onChange={e => setName(e.target.value)}
                placeholder="e.g. Build REST API"
                className="acm-input w-full"
              />
            </div>
            <div>
              <label className="label block mb-2">
                Goal <span className="text-[var(--acm-err)]">*</span>
              </label>
              <textarea
                value={goal}
                onChange={e => setGoal(e.target.value)}
                placeholder="Describe what you want the swarm to accomplish in detail..."
                rows={4}
                className="w-full bg-[var(--acm-elev)] border border-[var(--acm-border)] rounded-lg px-3 py-2 text-[var(--acm-fg)] placeholder-[var(--acm-fg-4)] text-[13px] outline-none focus:border-[var(--acm-accent)] resize-none transition-colors"
              />
            </div>
            <div>
              <label className="label block mb-2">Global Model (optional)</label>
              <input
                value={globalModel}
                onChange={e => setGlobalModel(e.target.value)}
                placeholder="e.g. anthropic/claude-opus-4-6 (leave blank for system default)"
                className="acm-input w-full"
              />
              <p className="text-[11px] text-[var(--acm-fg-4)] mt-1.5">
                Workers without a specific model will use this. Per-worker models can be set later.
              </p>
            </div>
            <div>
              <label className="label block mb-2">Working Path (optional)</label>
              <div className="flex gap-2">
                <input
                  value={workingPath}
                  onChange={e => setWorkingPath(e.target.value)}
                  placeholder="Leave blank to use the default workspace"
                  className="acm-input flex-1 min-w-0"
                />
                <button
                  type="button"
                  title="Browse folder"
                  onClick={async () => {
                    try {
                      const res = await fetch('/api/system/pick-folder', {
                        headers: token ? { Authorization: `Bearer ${token}` } : {},
                      });
                      const data = await res.json();
                      if (data.path) setWorkingPath(data.path);
                    } catch {}
                  }}
                  className="shrink-0 px-3 h-9 border border-[var(--acm-border)] rounded-lg bg-[var(--acm-elev)] hover:border-[var(--acm-accent)] text-[var(--acm-fg-3)] hover:text-[var(--acm-fg)] transition-colors flex items-center"
                >
                  <FolderOpen size={15} />
                </button>
              </div>
              <p className="text-[11px] text-[var(--acm-fg-4)] mt-1.5">
                Directory where workers will create and edit files. Leave blank to use the default workspace.
              </p>
            </div>
            <div>
              <label className="label block mb-2">Context Files (optional)</label>
              <div
                onDrop={handleDrop}
                onDragOver={e => { e.preventDefault(); setIsDragging(true); }}
                onDragLeave={() => setIsDragging(false)}
                onClick={() => fileInputRef.current?.click()}
                className={`border border-dashed rounded-lg p-6 text-center cursor-pointer transition-colors ${
                  isDragging
                    ? 'border-[var(--acm-accent)] bg-[oklch(0.84_0.16_82/0.06)]'
                    : 'border-[var(--acm-border-strong)] hover:border-[var(--acm-accent)]'
                }`}
              >
                <Upload size={22} className="mx-auto text-[var(--acm-fg-3)] mb-2" />
                <p className="text-[var(--acm-fg-3)] text-[13px]">Drop files here or click to browse</p>
                <p className="text-[var(--acm-fg-4)] text-[11px] mt-1">
                  Code, docs, specs — anything the team should understand
                </p>
                <input
                  ref={fileInputRef}
                  type="file"
                  multiple
                  className="hidden"
                  onChange={e => setFiles(prev => [...prev, ...Array.from(e.target.files || [])])}
                />
              </div>
              {files.length > 0 && (
                <ul className="mt-2 space-y-1">
                  {files.map((f, i) => (
                    <li key={i} className="flex items-center gap-2 text-[12px] text-[var(--acm-fg-2)]">
                      <FileText size={13} className="text-[var(--acm-fg-3)]" />
                      <span className="flex-1 truncate">{f.name}</span>
                      <span className="text-[var(--acm-fg-4)] mono">{(f.size / 1024).toFixed(1)}kb</span>
                      <button
                        onClick={() => setFiles(prev => prev.filter((_, j) => j !== i))}
                        className="text-[var(--acm-fg-4)] hover:text-[var(--acm-err)] transition-colors"
                      >
                        <X size={13} />
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
            <div className="flex gap-3 pt-2">
              <button onClick={onClose} className="btn-secondary flex-1 py-2">
                Cancel
              </button>
              <button
                onClick={handleSubmit}
                disabled={!goal.trim()}
                className="btn-primary flex-1 py-2 disabled:opacity-40 disabled:cursor-not-allowed"
              >
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
    <div className="acm-card p-[12px] flex flex-col gap-[10px] relative overflow-hidden">
      {worker.status === 'busy' && (
        <div className="acm-pulse absolute top-0 left-0 right-0 h-px bg-[var(--acm-accent)]" />
      )}
      <div className="flex items-start gap-3">
        <div className="w-8 h-8 rounded-lg bg-[var(--acm-elev)] flex items-center justify-center flex-shrink-0 border border-[var(--acm-border)]">
          <Bot size={15} className="text-[var(--acm-fg-3)]" />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="mono text-[12px] text-[var(--acm-fg)] font-semibold">{worker.name}</span>
            <span className={`label px-1.5 py-0.5 rounded border ${
              worker.role === 'orchestrator'
                ? 'border-[var(--acm-accent)] text-[var(--acm-accent)]'
                : 'border-[var(--acm-border-strong)] text-[var(--acm-fg-3)]'
            }`}>
              {worker.role}
            </span>
            <span className={`dot ${WORKER_DOT[worker.status] || 'dot-idle'} ml-auto`} />
            <span className="mono text-[10px] text-[var(--acm-fg-4)]">{worker.status}</span>
          </div>
          <p className="text-[var(--acm-fg-3)] text-[11px] mt-1 leading-relaxed">{worker.description}</p>
          <div className="flex items-center gap-2 mt-2">
            <Cpu size={11} className="text-[var(--acm-fg-4)]" />
            {editModel ? (
              <div className="flex items-center gap-1 flex-1">
                <input
                  value={modelVal}
                  onChange={e => setModelVal(e.target.value)}
                  placeholder="e.g. anthropic/claude-opus-4-6"
                  className="flex-1 bg-[var(--acm-elev)] border border-[var(--acm-border)] rounded px-2 py-0.5 text-[11px] text-[var(--acm-fg)] focus:outline-none focus:border-[var(--acm-accent)] mono"
                  autoFocus
                />
                <button onClick={saveModel} className="text-[var(--acm-ok)] hover:opacity-80 transition-opacity">
                  <Check size={13} />
                </button>
                <button
                  onClick={() => { setEditModel(false); setModelVal(worker.model || ''); }}
                  className="text-[var(--acm-fg-4)] hover:text-[var(--acm-fg)] transition-colors"
                >
                  <X size={13} />
                </button>
              </div>
            ) : (
              <button
                onClick={() => setEditModel(true)}
                className="flex items-center gap-1 text-[11px] text-[var(--acm-fg-4)] hover:text-[var(--acm-fg-2)] transition-colors group"
              >
                <span className="mono">{worker.model || 'system default'}</span>
                <Edit2 size={10} className="opacity-0 group-hover:opacity-100 transition-opacity" />
              </button>
            )}
          </div>
        </div>
      </div>
      <button
        onClick={() => setExpanded(v => !v)}
        className="flex items-center gap-1 text-[10px] text-[var(--acm-fg-4)] hover:text-[var(--acm-fg-3)] transition-colors"
      >
        {expanded ? <ChevronUp size={11} /> : <ChevronDown size={11} />}
        <span className="label">System prompt</span>
      </button>
      {expanded && (
        <pre className="text-[11px] text-[var(--acm-fg-3)] bg-[var(--acm-elev)] border border-[var(--acm-border)] rounded-lg p-3 overflow-auto max-h-40 whitespace-pre-wrap mono">
          {worker.system_prompt}
        </pre>
      )}
    </div>
  );
}

// ─── Task Row ─────────────────────────────────────────────────────────────────

function TaskRow({ task, swarmId, onAction }: { task: Task; swarmId: number; onAction?: () => void }) {
  const [expanded, setExpanded] = useState(false);
  const [mode, setMode] = useState<null | 'retry' | 'complete'>(null);
  const [notes, setNotes] = useState('');
  const [manualResult, setManualResult] = useState('');
  const [loading, setLoading] = useState(false);
  const { fetchAPI } = useAPI();

  const handleRetry = async () => {
    setLoading(true);
    try {
      await fetchAPI(`/api/swarms/${swarmId}/tasks/${task.id}/retry`, {
        method: 'POST',
        body: JSON.stringify({ user_notes: notes }),
      });
      setMode(null); setNotes('');
      onAction?.();
    } catch (e) { /* ignore, fetchAPI toasts */ }
    setLoading(false);
  };

  const handleComplete = async () => {
    if (!manualResult.trim()) return;
    setLoading(true);
    try {
      await fetchAPI(`/api/swarms/${swarmId}/tasks/${task.id}/complete`, {
        method: 'POST',
        body: JSON.stringify({ result: manualResult }),
      });
      setMode(null); setManualResult('');
      onAction?.();
    } catch (e) { /* ignore */ }
    setLoading(false);
  };

  const isFailed = task.status === 'failed';

  return (
    <div className={`border rounded-lg p-3 transition-colors ${
      task.status === 'running'  ? 'border-l-2 border-l-[var(--acm-accent)] border-[var(--acm-border)]' :
      task.status === 'waiting'  ? 'border-l-2 border-l-[var(--acm-warn)] border-[var(--acm-border)]' :
      isFailed                   ? 'border-l-2 border-l-[var(--acm-err)] border-[var(--acm-border)]' :
      task.status === 'completed'? 'border-[var(--acm-border)] bg-[var(--acm-card)]' :
                                   'border-[var(--acm-border)]'
    }`}>
      <div className="flex items-start gap-3">
        <div className="flex items-center gap-1.5 flex-shrink-0 pt-0.5">
          <span className={`dot ${TASK_DOT[task.status] || 'dot-idle'}`} />
          {task.status === 'running' && <Loader2 size={10} className="animate-spin text-[var(--acm-accent)]" />}
          {task.status === 'completed' && <CheckCircle2 size={10} className="text-[var(--acm-ok)]" />}
          {task.status === 'failed' && <AlertCircle size={10} className="text-[var(--acm-err)]" />}
          {task.status === 'pending' && <Clock size={10} className="text-[var(--acm-fg-4)]" />}
          {task.status === 'waiting' && <HelpCircle size={10} className="text-[var(--acm-warn)]" />}
        </div>
        <div className="flex-1 min-w-0">
          <p className="text-[var(--acm-fg)] text-[13px] font-medium">{task.title}</p>
          {task.worker_name && (
            <p className="text-[var(--acm-fg-4)] mono text-[11px] mt-0.5">→ {task.worker_name}</p>
          )}
        </div>
        <div className="flex items-center gap-1 flex-shrink-0">
          {isFailed && mode === null && (
            <>
              <button
                onClick={() => setMode('retry')}
                className="text-[11px] px-2 py-0.5 rounded border border-[var(--acm-warn)] text-[var(--acm-warn)] hover:bg-[oklch(0.84_0.16_82/0.08)] transition-colors"
              >
                Retry
              </button>
              <button
                onClick={() => setMode('complete')}
                className="text-[11px] px-2 py-0.5 rounded border border-[var(--acm-ok)] text-[var(--acm-ok)] hover:bg-[oklch(0.55_0.12_160/0.1)] transition-colors"
              >
                Completar
              </button>
            </>
          )}
          {task.result && (
            <button
              onClick={() => setExpanded(v => !v)}
              className="text-[var(--acm-fg-4)] hover:text-[var(--acm-fg-3)] ml-1 transition-colors"
            >
              {expanded ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
            </button>
          )}
        </div>
      </div>

      {expanded && task.result && (
        <div className="mt-2 text-[11px] text-[var(--acm-fg-3)] bg-[var(--acm-elev)] border border-[var(--acm-border)] rounded-lg p-3 max-h-64 overflow-auto whitespace-pre-wrap mono">
          {task.result}
        </div>
      )}

      {/* Retry with guidance */}
      {mode === 'retry' && (
        <div className="acm-card mt-3 p-3 space-y-2">
          <p className="label text-[var(--acm-warn)]">Retry — añade instrucciones para el worker (opcional):</p>
          <textarea
            value={notes}
            onChange={e => setNotes(e.target.value)}
            placeholder="Ej: El archivo ya está en src/foo.py, léelo primero. Usa un enfoque más simple..."
            rows={3}
            className="w-full text-[11px] bg-[var(--acm-elev)] border border-[var(--acm-border)] rounded-lg p-2 text-[var(--acm-fg)] placeholder-[var(--acm-fg-4)] resize-none outline-none focus:border-[var(--acm-accent)] transition-colors"
          />
          <div className="flex gap-2">
            <button
              onClick={handleRetry}
              disabled={loading}
              className="btn-primary text-[11px] px-3 py-1 disabled:opacity-50 flex items-center gap-1"
            >
              {loading && <Loader2 size={10} className="animate-spin" />}
              Reintentar
            </button>
            <button
              onClick={() => setMode(null)}
              className="btn-secondary text-[11px] px-3 py-1"
            >
              Cancelar
            </button>
          </div>
        </div>
      )}

      {/* Manual completion */}
      {mode === 'complete' && (
        <div className="acm-card mt-3 p-3 space-y-2">
          <p className="label text-[var(--acm-ok)]">Completar manualmente — escribe el resultado:</p>
          <textarea
            value={manualResult}
            onChange={e => setManualResult(e.target.value)}
            placeholder="Describe lo que se hizo, qué archivos se crearon, y cualquier output relevante para las tareas dependientes..."
            rows={5}
            className="w-full text-[11px] bg-[var(--acm-elev)] border border-[var(--acm-border)] rounded-lg p-2 text-[var(--acm-fg)] placeholder-[var(--acm-fg-4)] resize-none outline-none focus:border-[var(--acm-accent)] transition-colors"
          />
          <div className="flex gap-2">
            <button
              onClick={handleComplete}
              disabled={loading || !manualResult.trim()}
              className="btn-primary text-[11px] px-3 py-1 disabled:opacity-50 flex items-center gap-1"
            >
              {loading && <Loader2 size={10} className="animate-spin" />}
              Marcar completada
            </button>
            <button
              onClick={() => setMode(null)}
              className="btn-secondary text-[11px] px-3 py-1"
            >
              Cancelar
            </button>
          </div>
        </div>
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
        p: ({ children }) => <p className={`mb-1.5 last:mb-0 leading-relaxed text-[13px] ${textColor}`}>{children}</p>,
        h1: ({ children }) => <h1 className="text-[14px] font-bold text-[var(--acm-fg)] mt-3 mb-1 first:mt-0">{children}</h1>,
        h2: ({ children }) => <h2 className="text-[13px] font-semibold text-[var(--acm-fg)] mt-2 mb-1 first:mt-0">{children}</h2>,
        h3: ({ children }) => <h3 className="text-[13px] font-semibold text-[var(--acm-fg-2)] mt-1.5 mb-0.5 first:mt-0">{children}</h3>,
        strong: ({ children }) => <strong className="font-semibold text-[var(--acm-fg)]">{children}</strong>,
        em: ({ children }) => <em className="italic text-[var(--acm-fg-2)]">{children}</em>,
        ul: ({ children }) => <ul className="list-disc list-inside space-y-0.5 my-1.5 pl-2 text-[13px]">{children}</ul>,
        ol: ({ children }) => <ol className="list-decimal list-inside space-y-0.5 my-1.5 pl-2 text-[13px]">{children}</ol>,
        li: ({ children }) => <li className={`text-[13px] ${textColor}`}>{children}</li>,
        code: ({ children, className }) => {
          const isBlock = className?.includes('language-');
          return isBlock
            ? <code className="block bg-[var(--acm-elev)] text-[var(--acm-ok)] border border-[var(--acm-border)] rounded-lg px-3 py-2 my-1.5 text-[11px] mono overflow-x-auto whitespace-pre">{children}</code>
            : <code className="bg-[var(--acm-elev)] text-[var(--acm-accent)] border border-[var(--acm-border)] rounded px-1 py-0.5 text-[11px] mono">{children}</code>;
        },
        pre: ({ children }) => <>{children}</>,
        blockquote: ({ children }) => <blockquote className="border-l-2 border-l-[var(--acm-border-strong)] pl-2 my-1.5 text-[var(--acm-fg-3)] italic text-[13px]">{children}</blockquote>,
        hr: () => <hr className="border-[var(--acm-border)] my-2" />,
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

  const cfg: Record<string, {
    containerClass: string;
    icon: React.ReactNode;
    label: () => React.ReactNode;
    textColor: string;
    collapsible?: boolean;
  }> = {
    user: {
      containerClass: 'border-l-2 border-l-[var(--acm-accent)] border-[var(--acm-border)] bg-[oklch(0.84_0.16_82/0.04)]',
      textColor: 'text-[var(--acm-fg-2)]',
      icon: <User size={12} className="text-[var(--acm-accent)]" />,
      label: () => <span className="font-semibold text-[var(--acm-accent)]">You</span>,
    },
    question: {
      containerClass: 'border-l-2 border-l-[var(--acm-warn)] border-[var(--acm-border)]',
      textColor: 'text-[var(--acm-fg-2)]',
      icon: <HelpCircle size={12} className="text-[var(--acm-warn)]" />,
      label: () => <span className="font-semibold text-[var(--acm-warn)]">{msg.from_worker_name || 'Worker'} asks</span>,
    },
    task_result: {
      containerClass: 'border-[var(--acm-border)] bg-[var(--acm-card)]',
      textColor: 'text-[var(--acm-fg-2)]',
      icon: <CheckCircle2 size={12} className="text-[var(--acm-ok)]" />,
      label: () => <span className="font-semibold text-[var(--acm-ok)]">{msg.from_worker_name || 'Worker'}</span>,
      collapsible: true,
    },
    task_failed: {
      containerClass: 'border-l-2 border-l-[var(--acm-err)] border-[var(--acm-border)]',
      textColor: 'text-[var(--acm-fg-2)]',
      icon: <XCircle size={12} className="text-[var(--acm-err)]" />,
      label: () => <span className="font-semibold text-[var(--acm-err)]">{msg.from_worker_name || 'Worker'}</span>,
    },
    task_waiting: {
      containerClass: 'border-l-2 border-l-[var(--acm-warn)] border-[var(--acm-border)]',
      textColor: 'text-[var(--acm-fg-2)]',
      icon: <HelpCircle size={12} className="text-[var(--acm-warn)]" />,
      label: () => <span className="font-semibold text-[var(--acm-warn)]">{msg.from_worker_name || 'Worker'} — waiting</span>,
    },
    bug_report: {
      containerClass: 'border-l-2 border-l-[var(--acm-err)] border-[var(--acm-border)]',
      textColor: 'text-[var(--acm-fg-2)]',
      icon: <Bug size={12} className="text-[var(--acm-err)]" />,
      label: () => <span className="font-semibold text-[var(--acm-err)]">{msg.from_worker_name || 'QA'} — bug found</span>,
    },
    synthesis: {
      containerClass: 'border-l-2 border-l-[var(--acm-accent)] border-[var(--acm-border)] bg-[oklch(0.84_0.16_82/0.03)]',
      textColor: 'text-[var(--acm-fg-2)]',
      icon: <Sparkles size={12} className="text-[var(--acm-accent)]" />,
      label: () => <span className="font-semibold text-[var(--acm-accent)]">Final Summary</span>,
      collapsible: true,
    },
    broadcast: {
      containerClass: 'border-[var(--acm-border)] bg-[var(--acm-card)]',
      textColor: 'text-[var(--acm-fg-2)]',
      icon: <Radio size={12} className="text-[var(--acm-fg-3)]" />,
      label: () => <span className="font-semibold text-[var(--acm-fg-2)]">{msg.from_worker_name || 'Worker'}</span>,
    },
    message: {
      containerClass: 'border-[var(--acm-border)] bg-[var(--acm-card)]',
      textColor: 'text-[var(--acm-fg-2)]',
      icon: <ArrowRight size={12} className="text-[var(--acm-fg-4)]" />,
      label: () => (
        <>
          <span className="font-semibold text-[var(--acm-fg-2)]">{msg.from_worker_name || '?'}</span>
          <ArrowRight size={10} className="text-[var(--acm-fg-4)] mx-0.5" />
          <span className="font-semibold text-[var(--acm-fg-2)]">{msg.to_worker_name || '?'}</span>
        </>
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
    const sevClass: Record<string, string> = {
      critical: 'bg-[var(--acm-err)] text-[var(--acm-base)]',
      high:     'bg-[var(--acm-warn)] text-[var(--acm-base)]',
      medium:   'bg-[var(--acm-accent)] text-[oklch(0.18_0.015_80)]',
      low:      'bg-[var(--acm-fg-4)] text-[var(--acm-base)]',
    };
    const sev = (bug.severity || 'medium').toLowerCase();
    return (
      <div className="border-l-2 border-l-[var(--acm-err)] border-[var(--acm-border)] rounded-lg p-3">
        <div className="flex items-center gap-1.5 mb-2 text-[11px] text-[var(--acm-fg-4)]">
          <Bug size={12} className="text-[var(--acm-err)]" />
          <span className="font-semibold text-[var(--acm-err)]">{msg.from_worker_name || 'QA'} — bug found</span>
          <span className={`ml-1 px-1.5 py-0.5 rounded mono text-[10px] font-bold ${sevClass[sev] || sevClass.medium}`}>
            {sev.toUpperCase()}
          </span>
          {bug.cycle && bug.cycle > 1 && <span className="text-[var(--acm-fg-4)]">cycle {bug.cycle}</span>}
          <span className="ml-auto mono text-[var(--acm-fg-4)]">{new Date(msg.created_at).toLocaleTimeString()}</span>
        </div>
        <p className="text-[13px] font-semibold text-[var(--acm-fg)] mb-1">{bug.title}</p>
        {bug.description && (
          <p className="text-[11px] text-[var(--acm-fg-3)] mb-2 whitespace-pre-wrap">{bug.description}</p>
        )}
        <div className="flex gap-3 text-[11px] text-[var(--acm-fg-4)]">
          {bug.fixer && <span>Fix → <span className="text-[var(--acm-fg-2)]">{bug.fixer}</span></span>}
          {bug.retest_task && <span>Re-test scheduled</span>}
        </div>
      </div>
    );
  }

  return (
    <div className={`border rounded-lg p-3 ${c.containerClass}`}>
      <div className="flex items-center gap-1.5 mb-1.5 text-[11px] text-[var(--acm-fg-4)]">
        {c.icon}
        {c.label()}
        <span className="ml-auto mono text-[var(--acm-fg-4)]">{new Date(msg.created_at).toLocaleTimeString()}</span>
      </div>
      <SwarmMarkdown content={displayContent} textColor={c.textColor} />
      <div className="flex items-center gap-2 mt-1.5">
        {isCollapsible && (
          <button
            onClick={() => setExpanded(x => !x)}
            className="text-[11px] text-[var(--acm-fg-4)] hover:text-[var(--acm-fg-3)] transition-colors"
          >
            {expanded ? '↑ collapse' : '↓ show full output'}
          </button>
        )}
        {(type === 'question' || type === 'task_waiting') && onReply && (
          <button
            onClick={() => onReply(`@${msg.from_worker_name || 'Worker'}: `)}
            className="ml-auto flex items-center gap-1 px-2 py-0.5 rounded text-[11px] border border-[var(--acm-warn)] text-[var(--acm-warn)] hover:bg-[oklch(0.84_0.16_82/0.08)] transition-colors"
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
  const [showReuseForm, setShowReuseForm] = useState(false);
  const [reuseGoal, setReuseGoal] = useState('');
  const [reuseFiles, setReuseFiles] = useState<File[]>([]);
  const [reuseLoading, setReuseLoading] = useState(false);
  const [reuseError, setReuseError] = useState('');
  const [reuseWarning, setReuseWarning] = useState<{ reason: string; suggestion: string } | null>(null);
  const reuseFileRef = useRef<HTMLInputElement>(null);
  const [clarifyAnswers, setClarifyAnswers] = useState<Record<number, string>>({});
  const [clarifyFiles, setClarifyFiles] = useState<File[]>([]);
  const [clarifySubmitting, setClarifySubmitting] = useState(false);
  const [clarifyError, setClarifyError] = useState('');
  const clarifyFileRef = useRef<HTMLInputElement>(null);
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

  if (!swarm) return (
    <div className="flex items-center justify-center h-64">
      <Loader2 size={28} className="animate-spin text-[var(--acm-accent)]" />
    </div>
  );

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
  const canReuse = !['running', 'planning', 'clarifying'].includes(swarm.status);

  // Progress bar segments
  const totalTasks = tasks.length;
  const pctDone = totalTasks ? (completed.length / totalTasks) * 100 : 0;
  const pctRunning = totalTasks ? (running.length / totalTasks) * 100 : 0;
  const pctFailed = totalTasks ? (failed.length / totalTasks) * 100 : 0;

  return (
    <div>
      {/* Header */}
      <div className="flex items-start gap-4 mb-6">
        <button
          onClick={onBack}
          className="mt-1 text-[var(--acm-fg-3)] hover:text-[var(--acm-fg)] transition-colors"
        >
          <ArrowLeft size={18} />
        </button>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-3 flex-wrap">
            <h1 className="text-[20px] font-semibold tracking-[-0.01em] text-[var(--acm-fg)] truncate">
              {swarm.name}
            </h1>
            <span className={`dot ${SWARM_DOT[swarm.status] || 'dot-idle'}`} />
            <span className="mono text-[12px] text-[var(--acm-fg-3)]">
              {swarm.status === 'running' && <Loader2 size={12} className="inline animate-spin mr-1 text-[var(--acm-accent)]" />}
              {swarm.status}
            </span>
          </div>
          <div className="text-[var(--acm-fg-3)] text-[13px] mt-1">
            <SwarmMarkdown content={swarm.goal} textColor="text-[var(--acm-fg-3)]" />
          </div>
          {swarm.global_model && (
            <p className="text-[var(--acm-fg-4)] text-[11px] mt-1 mono">Global model: {swarm.global_model}</p>
          )}
        </div>
        <div className="flex items-center gap-2 flex-shrink-0">
          {canStart && (
            <button
              onClick={() => startMutation.mutate()}
              disabled={startMutation.isPending}
              className="btn-primary flex items-center gap-2 px-4 py-2 text-[13px] disabled:opacity-50"
            >
              {startMutation.isPending ? <Loader2 size={14} className="animate-spin" /> : <Play size={14} />}
              Start
            </button>
          )}
          {canStop && (
            <button
              onClick={() => stopMutation.mutate()}
              disabled={stopMutation.isPending}
              className="btn-secondary flex items-center gap-2 px-4 py-2 text-[13px] disabled:opacity-50"
            >
              <Pause size={14} /> Pause
            </button>
          )}
          {canComplete && (
            <button
              onClick={() => { if (confirm('Mark this swarm as completed?')) completeMutation.mutate(); }}
              disabled={completeMutation.isPending}
              className="btn-secondary flex items-center gap-2 px-4 py-2 text-[13px] disabled:opacity-50"
            >
              {completeMutation.isPending
                ? <Loader2 size={14} className="animate-spin" />
                : <CheckCircle2 size={14} />}
              Finalizar
            </button>
          )}
          {canReuse && (
            <button
              onClick={() => { setReuseGoal(swarm.goal); setShowReuseForm(f => !f); setReuseError(''); }}
              className="btn-secondary flex items-center gap-2 px-4 py-2 text-[13px]"
              title="Reuse this swarm with a new goal"
            >
              <RotateCcw size={14} /> Reuse
            </button>
          )}
          <button
            onClick={() => { if (confirm('Delete this swarm and all its data?')) deleteMutation.mutate(); }}
            className="p-2 text-[var(--acm-fg-4)] hover:text-[var(--acm-err)] transition-colors rounded-lg hover:bg-[oklch(0.5_0.18_25/0.08)]"
          >
            <Trash2 size={15} />
          </button>
        </div>
      </div>

      {/* Clarification panel — shown while waiting for user answers before planning */}
      {swarm.status === 'clarifying' && (() => {
        let questions: string[] = [];
        try { questions = JSON.parse(swarm.clarification_questions || '[]'); } catch {}
        const handleSubmit = async () => {
          setClarifySubmitting(true);
          setClarifyError('');
          try {
            const pairs = questions.map((q, i) => ({ question: q, answer: clarifyAnswers[i] || '' }));
            const fd = new FormData();
            fd.append('answers', JSON.stringify(pairs));
            for (const f of clarifyFiles) fd.append('files', f);
            const headers: Record<string, string> = {};
            if (token) headers['Authorization'] = `Bearer ${token}`;
            const res = await fetch(`/api/swarms/${swarmId}/clarify/answer`, { method: 'POST', body: fd, headers });
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            setClarifyAnswers({});
            setClarifyFiles([]);
            refetch();
            qc.invalidateQueries({ queryKey: ['swarms'] });
          } catch (e: any) {
            setClarifyError(e.message || 'Failed to submit answers');
          } finally {
            setClarifySubmitting(false);
          }
        };

        return (
          <div className="mb-6 border border-[var(--acm-warn)] rounded-xl overflow-hidden">
            <div className="px-4 py-3 bg-[oklch(0.84_0.16_82/0.06)] border-b border-[var(--acm-warn)] flex items-center gap-2">
              <HelpCircle size={15} className="text-[var(--acm-warn)] shrink-0" />
              <p className="text-[13px] font-medium text-[var(--acm-fg)]">
                Before planning the team, the AI needs a few clarifications
              </p>
            </div>
            <div className="p-4 space-y-4">
              {clarifySubmitting ? (
                <div className="flex items-center gap-3 py-6 justify-center">
                  <Loader2 size={20} className="animate-spin text-[var(--acm-accent)]" />
                  <span className="text-[13px] text-[var(--acm-fg-3)]">Planning the team with your answers…</span>
                </div>
              ) : (
                <>
                  {questions.length === 0 ? (
                    <p className="text-[13px] text-[var(--acm-fg-3)] italic">No questions generated — you can proceed directly to planning.</p>
                  ) : (
                    questions.map((q, i) => (
                      <div key={i}>
                        <label className="block text-[12px] font-medium text-[var(--acm-fg-2)] mb-1">
                          {i + 1}. {q}
                        </label>
                        <textarea
                          rows={2}
                          value={clarifyAnswers[i] || ''}
                          onChange={e => setClarifyAnswers(prev => ({ ...prev, [i]: e.target.value }))}
                          className="acm-input w-full resize-none text-[13px]"
                          placeholder="Your answer…"
                        />
                      </div>
                    ))
                  )}

                  {/* Extra files */}
                  <div>
                    <input
                      ref={clarifyFileRef}
                      type="file"
                      multiple
                      className="hidden"
                      onChange={e => setClarifyFiles(prev => [...prev, ...Array.from(e.target.files || [])])}
                    />
                    <button
                      type="button"
                      onClick={() => clarifyFileRef.current?.click()}
                      className="flex items-center gap-1.5 px-3 py-1.5 text-[12px] border border-[var(--acm-border)] rounded-lg bg-[var(--acm-elev)] hover:border-[var(--acm-accent)] text-[var(--acm-fg-3)] hover:text-[var(--acm-fg)] transition-colors"
                    >
                      <Upload size={12} /> Attach additional documents
                    </button>
                    {clarifyFiles.length > 0 && (
                      <ul className="mt-2 space-y-0.5">
                        {clarifyFiles.map((f, i) => (
                          <li key={i} className="flex items-center gap-1.5 text-[11px] text-[var(--acm-fg-3)]">
                            <FileText size={10} className="shrink-0" />
                            {f.name}
                            <button onClick={() => setClarifyFiles(p => p.filter((_, j) => j !== i))} className="ml-auto text-[var(--acm-fg-4)] hover:text-[var(--acm-err)]">
                              <X size={10} />
                            </button>
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>

                  {clarifyError && <p className="text-[var(--acm-err)] text-[12px]">{clarifyError}</p>}

                  <div className="flex justify-end gap-2 pt-1">
                    <button
                      onClick={handleSubmit}
                      className="btn-primary flex items-center gap-2 px-5 py-2 text-[13px]"
                    >
                      <Sparkles size={14} /> Submit answers & Plan the team
                    </button>
                  </div>
                </>
              )}
            </div>
          </div>
        );
      })()}

      {/* Reuse form */}
      {showReuseForm && (
        <div className="mb-5 p-4 border border-[var(--acm-border)] rounded-xl bg-[var(--acm-card)]">
          {reuseLoading ? (
            <div className="flex items-center gap-3 py-4 justify-center">
              <Loader2 size={20} className="animate-spin text-[var(--acm-accent)]" />
              <span className="text-[13px] text-[var(--acm-fg-3)]">
                {reuseWarning === null ? 'Checking compatibility…' : 'Resetting swarm…'}
              </span>
            </div>
          ) : reuseWarning ? (
            /* ── Incompatibility warning ── */
            <>
              <div className="mb-4 p-3 rounded-lg border border-[var(--acm-warn)] bg-[oklch(0.84_0.16_82/0.06)] flex gap-3">
                <AlertCircle size={16} className="text-[var(--acm-warn)] shrink-0 mt-0.5" />
                <div>
                  <p className="text-[13px] font-medium text-[var(--acm-fg)] mb-1">
                    This goal doesn't match the current team
                  </p>
                  <p className="text-[12px] text-[var(--acm-fg-3)]">{reuseWarning.reason}</p>
                  {reuseWarning.suggestion && (
                    <p className="text-[12px] text-[var(--acm-fg-3)] mt-1 italic">{reuseWarning.suggestion}</p>
                  )}
                </div>
              </div>
              {reuseError && <p className="text-[var(--acm-err)] text-[12px] mb-2">{reuseError}</p>}
              <div className="flex gap-2 justify-end flex-wrap">
                <button
                  onClick={() => { setShowReuseForm(false); setReuseFiles([]); setReuseError(''); setReuseWarning(null); }}
                  className="btn-secondary px-4 py-1.5 text-[13px]"
                >
                  Cancel
                </button>
                <button
                  onClick={async () => {
                    // Force proceed despite warning
                    setReuseError('');
                    setReuseLoading(true);
                    try {
                      const fd = new FormData();
                      if (reuseGoal.trim()) fd.append('goal', reuseGoal.trim());
                      for (const f of reuseFiles) fd.append('files', f);
                      const headers: Record<string, string> = {};
                      if (token) headers['Authorization'] = `Bearer ${token}`;
                      const res = await fetch(`/api/swarms/${swarmId}/reset`, { method: 'POST', body: fd, headers });
                      if (!res.ok) throw new Error(`HTTP ${res.status}`);
                      await fetchAPI(`/api/swarms/${swarmId}/start`, { method: 'POST', body: JSON.stringify({}) });
                      setShowReuseForm(false); setReuseFiles([]); setReuseWarning(null);
                      refetch(); qc.invalidateQueries({ queryKey: ['swarms'] });
                    } catch (e: any) {
                      setReuseError(e.message || 'Failed to reset swarm');
                    } finally { setReuseLoading(false); }
                  }}
                  className="btn-secondary px-4 py-1.5 text-[13px] border-[var(--acm-warn)] text-[var(--acm-warn)]"
                >
                  Continue anyway
                </button>
                <button
                  onClick={() => { setShowReuseForm(false); setReuseWarning(null); }}
                  className="btn-primary px-4 py-1.5 text-[13px]"
                >
                  <Plus size={13} className="inline mr-1" /> Create new swarm
                </button>
              </div>
            </>
          ) : (
            /* ── Normal reuse form ── */
            <>
              <p className="text-[12px] text-[var(--acm-fg-3)] mb-3 font-medium">
                Workers and task definitions are kept — only results are cleared.
                Optionally update the goal or swap out the context files.
              </p>
              <textarea
                value={reuseGoal}
                onChange={e => { setReuseGoal(e.target.value); setReuseWarning(null); }}
                rows={3}
                className="acm-input w-full resize-none text-[13px] mb-3"
                placeholder="Goal (leave unchanged to keep the current one)"
                autoFocus
              />

              {/* File upload */}
              <input
                ref={reuseFileRef}
                type="file"
                multiple
                className="hidden"
                onChange={e => setReuseFiles(prev => [...prev, ...Array.from(e.target.files || [])])}
              />
              <div className="flex items-center gap-2 mb-2">
                <button
                  type="button"
                  onClick={() => reuseFileRef.current?.click()}
                  className="flex items-center gap-1.5 px-3 py-1.5 text-[12px] border border-[var(--acm-border)] rounded-lg bg-[var(--acm-elev)] hover:border-[var(--acm-accent)] text-[var(--acm-fg-3)] hover:text-[var(--acm-fg)] transition-colors"
                >
                  <Upload size={12} /> Attach new context files
                </button>
                {reuseFiles.length > 0 && (
                  <span className="text-[11px] text-[var(--acm-fg-4)]">
                    {reuseFiles.length} file{reuseFiles.length > 1 ? 's' : ''} selected
                    <button onClick={() => setReuseFiles([])} className="ml-1.5 text-[var(--acm-err)] hover:underline">clear</button>
                  </span>
                )}
              </div>
              {reuseFiles.length > 0 && (
                <ul className="mb-3 space-y-0.5">
                  {reuseFiles.map((f, i) => (
                    <li key={i} className="flex items-center gap-1.5 text-[11px] text-[var(--acm-fg-3)]">
                      <FileText size={10} className="shrink-0" />
                      {f.name}
                      <button onClick={() => setReuseFiles(p => p.filter((_, j) => j !== i))} className="ml-auto text-[var(--acm-fg-4)] hover:text-[var(--acm-err)]">
                        <X size={10} />
                      </button>
                    </li>
                  ))}
                </ul>
              )}

              {reuseError && <p className="text-[var(--acm-err)] text-[12px] mb-2">{reuseError}</p>}
              <div className="flex gap-2 justify-end">
                <button
                  onClick={() => { setShowReuseForm(false); setReuseFiles([]); setReuseError(''); setReuseWarning(null); }}
                  className="btn-secondary px-4 py-1.5 text-[13px]"
                >
                  Cancel
                </button>
                <button
                  onClick={async () => {
                    setReuseError('');
                    setReuseLoading(true);
                    try {
                      const effectiveGoal = reuseGoal.trim() || swarm.goal;
                      // Only check compatibility when the goal actually changed
                      if (reuseGoal.trim() && reuseGoal.trim() !== swarm.goal) {
                        const check = await fetchAPI(`/api/swarms/${swarmId}/check-reuse`, {
                          method: 'POST',
                          body: JSON.stringify({ goal: effectiveGoal }),
                        });
                        if (!check.compatible) {
                          setReuseWarning({ reason: check.reason, suggestion: check.suggestion });
                          setReuseLoading(false);
                          return;
                        }
                      }
                      const fd = new FormData();
                      if (reuseGoal.trim()) fd.append('goal', reuseGoal.trim());
                      for (const f of reuseFiles) fd.append('files', f);
                      const headers: Record<string, string> = {};
                      if (token) headers['Authorization'] = `Bearer ${token}`;
                      const res = await fetch(`/api/swarms/${swarmId}/reset`, { method: 'POST', body: fd, headers });
                      if (!res.ok) throw new Error(`HTTP ${res.status}`);
                      await fetchAPI(`/api/swarms/${swarmId}/start`, { method: 'POST', body: JSON.stringify({}) });
                      setShowReuseForm(false); setReuseFiles([]); setReuseWarning(null);
                      refetch(); qc.invalidateQueries({ queryKey: ['swarms'] });
                    } catch (e: any) {
                      setReuseError(e.message || 'Failed to reset swarm');
                    } finally { setReuseLoading(false); }
                  }}
                  className="btn-primary flex items-center gap-2 px-4 py-1.5 text-[13px]"
                >
                  <RotateCcw size={13} /> Re-run
                </button>
              </div>
            </>
          )}
        </div>
      )}

      {/* Progress bar */}
      {totalTasks > 0 && (
        <div className="mb-5 h-1.5 rounded-full overflow-hidden flex bg-[var(--acm-border)]">
          <div
            className="h-full bg-[var(--acm-ok)] transition-all"
            style={{ width: `${pctDone}%` }}
          />
          <div
            className={`h-full bg-[var(--acm-accent)] transition-all ${running.length > 0 ? 'acm-pulse' : ''}`}
            style={{ width: `${pctRunning}%` }}
          />
          <div
            className="h-full bg-[var(--acm-err)] transition-all"
            style={{ width: `${pctFailed}%` }}
          />
        </div>
      )}

      {/* Stats */}
      <div className="grid grid-cols-4 gap-3 mb-5">
        {[
          { label: 'Workers', value: (swarm.workers || []).length, icon: <Users size={14} /> },
          { label: 'Tasks', value: tasks.length, icon: <ListTodo size={14} /> },
          { label: 'Done', value: completed.length, icon: <CheckCircle2 size={14} className="text-[var(--acm-ok)]" /> },
          waiting.length > 0
            ? { label: 'Waiting', value: waiting.length, icon: <HelpCircle size={14} className="text-[var(--acm-warn)]" /> }
            : { label: 'Activity', value: messages.length, icon: <Activity size={14} /> },
        ].map(s => (
          <div key={s.label} className="acm-card p-3 flex items-center gap-3">
            <span className="text-[var(--acm-fg-3)]">{s.icon}</span>
            <div>
              <p className="mono text-[18px] font-bold text-[var(--acm-fg)]">{s.value}</p>
              <p className="label text-[var(--acm-fg-4)]">{s.label}</p>
            </div>
          </div>
        ))}
      </div>

      {/* Tabs */}
      <div className="flex gap-1 mb-4 bg-[var(--acm-card)] border border-[var(--acm-border)] rounded-[6px] p-1">
        {([
          { id: 'workers', label: 'Workers', icon: <Users size={14} /> },
          { id: 'tasks', label: 'Tasks', icon: <ListTodo size={14} />, badge: waiting.length > 0 ? waiting.length : 0 },
          { id: 'messages', label: 'Activity', icon: <Activity size={14} />, badge: unseenQuestions },
          { id: 'context', label: 'Context', icon: <FileText size={14} /> },
        ] as const).map(tab => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`flex-1 flex items-center justify-center gap-1.5 py-1.5 px-3 rounded-[6px] text-[12px] font-medium transition-colors ${
              activeTab === tab.id
                ? 'bg-[var(--acm-accent)] text-[oklch(0.18_0.015_80)]'
                : 'text-[var(--acm-fg-3)] hover:text-[var(--acm-fg-2)]'
            }`}
          >
            {tab.icon}
            {tab.label}
            {'badge' in tab && tab.badge > 0 && (
              <span className="ml-0.5 bg-[var(--acm-warn)] text-[oklch(0.18_0.015_80)] mono text-[9px] font-bold rounded-full w-4 h-4 flex items-center justify-center leading-none">
                {tab.badge > 9 ? '9+' : tab.badge}
              </span>
            )}
          </button>
        ))}
      </div>

      {/* Tab panels */}
      {activeTab === 'workers' && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          {(swarm.workers || []).length === 0
            ? <div className="col-span-2 text-center py-10 text-[var(--acm-fg-4)] text-[13px]">No workers yet.</div>
            : (swarm.workers || []).map(w => <WorkerCard key={w.id} worker={w} swarmId={swarmId} onUpdate={refetch} />)
          }
        </div>
      )}

      {activeTab === 'tasks' && (
        <div className="space-y-2">
          {orderedTasks.length === 0
            ? <div className="text-center py-10 text-[var(--acm-fg-4)] text-[13px]">No tasks yet.</div>
            : orderedTasks.map(t => <TaskRow key={t.id} task={t} swarmId={swarmId} onAction={refetch} />)
          }
        </div>
      )}

      {activeTab === 'messages' && (
        <div className="flex flex-col gap-2">
          {messages.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 text-[var(--acm-fg-4)]">
              <Activity size={28} className="mb-3 text-[var(--acm-fg-4)]" />
              <p className="text-[13px]">No activity yet. Start the swarm to see the feed.</p>
            </div>
          ) : (
            messages.map(m => (
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
          )}
          <div ref={msgEndRef} />
        </div>
      )}

      {activeTab === 'context' && (
        contextFiles.length === 0 && !swarm.shared_context ? (
          <div className="text-center py-10 text-[var(--acm-fg-4)] text-[13px]">No context files provided.</div>
        ) : (
          <div className="space-y-3">
            {contextFiles.length > 0 && (
              <div className="acm-card p-4">
                <h3 className="label text-[var(--acm-fg-3)] mb-3">Uploaded Files</h3>
                <ul className="space-y-1">
                  {contextFiles.map((f, i) => (
                    <li key={i} className="flex items-center gap-2 text-[12px] text-[var(--acm-fg-3)]">
                      <FileText size={13} className="text-[var(--acm-fg-4)]" />
                      <span className="mono">{f}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {swarm.shared_context && (
              <div className="acm-card p-4">
                <h3 className="label text-[var(--acm-fg-3)] mb-3">Shared Context</h3>
                <pre className="text-[11px] text-[var(--acm-fg-3)] whitespace-pre-wrap max-h-96 overflow-auto mono">
                  {swarm.shared_context}
                </pre>
              </div>
            )}
          </div>
        )
      )}

      {/* User message input */}
      <div className="mt-6 pt-4 border-t border-[var(--acm-border)]">
        <p className="text-[11px] text-[var(--acm-fg-4)] mb-2">
          Send feedback, new instructions, or ask for changes — the orchestrator will react and create tasks if needed.
        </p>
        <div className="flex gap-2">
          <textarea
            value={userMsg}
            onChange={e => setUserMsg(e.target.value)}
            onKeyDown={handleMsgKey}
            placeholder="Give feedback, request changes, add instructions… (Enter to send)"
            rows={2}
            className="flex-1 bg-[var(--acm-card)] border border-[var(--acm-border)] rounded-lg px-3 py-2 text-[var(--acm-fg)] placeholder-[var(--acm-fg-4)] text-[13px] outline-none focus:border-[var(--acm-accent)] resize-none transition-colors"
          />
          <button
            onClick={sendMessage}
            disabled={!userMsg.trim() || sending}
            className="btn-primary px-4 self-end pb-2 pt-2 disabled:opacity-40 disabled:cursor-not-allowed flex items-center gap-2"
          >
            {sending ? <Loader2 size={15} className="animate-spin" /> : <Send size={15} />}
          </button>
        </div>
      </div>
    </div>
  );
}

// ─── Swarm Card (list view) ───────────────────────────────────────────────────

function SwarmCard({ swarm, onSelect, onDelete }: { swarm: Swarm; onSelect: () => void; onDelete: () => void }) {
  return (
    <div
      onClick={onSelect}
      className="acm-card cursor-pointer p-5 group"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-2">
            <span className={`dot ${SWARM_DOT[swarm.status] || 'dot-idle'}`} />
            <span className="mono text-[11px] text-[var(--acm-fg-3)]">
              {swarm.status === 'running' && <Loader2 size={10} className="inline animate-spin mr-1 text-[var(--acm-accent)]" />}
              {swarm.status}
            </span>
            {swarm.global_model && (
              <span className="mono text-[10px] text-[var(--acm-fg-4)] truncate ml-1">{swarm.global_model}</span>
            )}
          </div>
          <h3 className="text-[var(--acm-fg)] font-semibold text-[14px] truncate">{swarm.name}</h3>
          <p className="text-[var(--acm-fg-3)] text-[12px] mt-1 line-clamp-2">{swarm.goal}</p>
        </div>
        <ChevronRight size={16} className="text-[var(--acm-fg-4)] group-hover:text-[var(--acm-accent)] transition-colors mt-1 flex-shrink-0" />
      </div>
      <div className="flex items-center gap-4 mt-4 pt-3 border-t border-[var(--acm-border)]">
        <span className="flex items-center gap-1.5 text-[11px] text-[var(--acm-fg-4)]">
          <Users size={12} />{swarm.worker_count} worker{swarm.worker_count !== 1 ? 's' : ''}
        </span>
        <span className="flex items-center gap-1.5 text-[11px] text-[var(--acm-fg-4)]">
          <ListTodo size={12} />{swarm.task_count} task{swarm.task_count !== 1 ? 's' : ''}
        </span>
        <span className="ml-auto mono text-[10px] text-[var(--acm-fg-4)]">
          {new Date(swarm.created_at).toLocaleDateString()}
        </span>
        <button
          onClick={e => { e.stopPropagation(); onDelete(); }}
          className="text-[var(--acm-fg-4)] hover:text-[var(--acm-err)] transition-colors"
        >
          <Trash2 size={13} />
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
  const [localSelectedId, setLocalSelectedId] = useState<number | null>(null);

  const urlId = searchParams.get('id') ? Number(searchParams.get('id')) : null;
  const selectedId = localSelectedId ?? urlId;

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
    setLocalSelectedId(id);
    router.push(`/swarms?id=${id}`);
  };

  const handleBack = () => {
    setLocalSelectedId(null);
    router.push('/swarms');
  };

  if (selectedId) {
    return <SwarmDetail swarmId={selectedId} onBack={handleBack} />;
  }

  return (
    <div>
      {/* Page header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <span className="acm-breadcrumb">/ swarms</span>
          <h1 className="text-[22px] font-semibold tracking-[-0.01em] text-[var(--acm-fg)]">Swarms</h1>
          <p className="text-[12px] text-[var(--acm-fg-3)] mt-1">Multi-agent teams for complex goals</p>
        </div>
        <button
          onClick={() => setShowCreate(true)}
          className="btn-primary flex items-center gap-2 px-4 py-2"
        >
          <Plus size={16} /> New Swarm
        </button>
      </div>

      {isLoading ? (
        <div className="flex items-center justify-center py-20">
          <Loader2 size={28} className="animate-spin text-[var(--acm-accent)]" />
        </div>
      ) : swarms.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-20 text-center">
          <Users size={40} className="text-[var(--acm-fg-4)] mb-4" />
          <h3 className="text-[15px] font-semibold text-[var(--acm-fg-2)] mb-2">No swarms yet</h3>
          <p className="text-[var(--acm-fg-4)] text-[13px] mb-6 max-w-sm">
            Create your first swarm — give it a goal and optional context files, and the AI will design a team of specialized workers.
          </p>
          <button
            onClick={() => setShowCreate(true)}
            className="btn-primary flex items-center gap-2 px-4 py-2"
          >
            <Plus size={15} /> Create Swarm
          </button>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {swarms.map(s => (
            <SwarmCard
              key={s.id}
              swarm={s}
              onSelect={() => { setLocalSelectedId(s.id); router.push(`/swarms?id=${s.id}`); }}
              onDelete={() => deleteMutation.mutate(s.id)}
            />
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
      <div className="p-6">
        <Suspense fallback={
          <div className="flex items-center justify-center py-20">
            <Loader2 size={28} className="animate-spin text-[var(--acm-accent)]" />
          </div>
        }>
          <SwarmsInner />
        </Suspense>
      </div>
    </AppLayout>
  );
}
