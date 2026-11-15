'use client';

import React, { useState, useRef, useEffect } from 'react';
import { Plus, Trash2, Play, Pause, CheckCircle2, AlertCircle, Loader2, Users, ListTodo, FileText, X, Upload, ArrowLeft, MessageSquare, Send, User, Radio, Sparkles, Activity, HelpCircle, RotateCcw } from 'lucide-react';
import { useAuthStore } from '@/stores/auth-store';
import { useAPI } from '@/hooks/use-api';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { WorkerCard } from './worker-views';
import { TaskRow } from './task-views';
import { SwarmMarkdown, LiveEventRow, ActivityEntry, SwarmChatsTab } from './activity-feed';
import { Swarm, SwarmMessage, SwarmDetailData, LiveEvent, SWARM_DOT } from './shared';

export function SwarmDetail({ swarmId, onBack }: { swarmId: number; onBack: () => void }) {
  const { fetchAPI } = useAPI();
  const token = useAuthStore(s => s.token);
  const qc = useQueryClient();
  const wsRef = useRef<WebSocket | null>(null);
  const [activeTab, setActiveTab] = useState<'workers' | 'tasks' | 'messages' | 'context' | 'chats'>('workers');
  const [selectedChannel, setSelectedChannel] = useState<{ channel_id: string; user_id: string } | null>(null);
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

  const [liveEvents, setLiveEvents] = useState<LiveEvent[]>([]);
  const [workerCtx, setWorkerCtx] = useState<Record<string, number>>({});
  const [plannerText, setPlannerText] = useState('');
  const prevStatusRef = useRef<string>('');

  const { data: swarm, refetch } = useQuery<SwarmDetailData>({
    queryKey: ['swarm', swarmId],
    queryFn: () => fetchAPI(`/api/swarms/${swarmId}`),
    refetchInterval: 10000,
  });

  const { data: messages = [], refetch: refetchMsgs } = useQuery<SwarmMessage[]>({
    queryKey: ['swarm-messages', swarmId],
    queryFn: () => fetchAPI(`/api/swarms/${swarmId}/messages`),
    refetchInterval: 10000,
  });

  useEffect(() => {
    const proto = window.location.protocol === 'https:' ? 'wss' : 'ws';
    const ws = new WebSocket(`${proto}://${window.location.host}/ws/swarms/${swarmId}?token=${token || ''}`);
    wsRef.current = ws;
    ws.onmessage = (evt) => {
      try {
        const msg = JSON.parse(evt.data as string);
        const type: string | undefined = msg.type;
        if (type === 'state') {
          if (msg.swarm) {
            qc.setQueryData(['swarm', swarmId], (old: SwarmDetailData | undefined) => ({
              ...(old || {} as SwarmDetailData),
              ...msg.swarm,
              workers: msg.workers ?? old?.workers ?? [],
              tasks: msg.tasks ?? old?.tasks ?? [],
            }));
          }
          if (msg.messages) {
            qc.setQueryData(['swarm-messages', swarmId], msg.messages);
          }
        } else if (type === 'swarm:planning_thought') {
          setPlannerText(msg.accumulated as string ?? '');
        } else if (type === 'message.reasoning' && msg.worker_name) {
          // Model reasoning from a swarm worker — show in live feed
          setLiveEvents(prev => [{
            ...msg, type: 'swarm:worker_thought',
            content: `[reasoning]\n${msg.content}`,
            ts: Date.now(),
          } as LiveEvent, ...prev].slice(0, 60));
        } else if (type?.startsWith('swarm:')) {
          setLiveEvents(prev => [{ ...msg, ts: Date.now() } as LiveEvent, ...prev].slice(0, 60));
          if (type === 'swarm:worker_progress' && msg.worker_name && msg.pct_used != null) {
            setWorkerCtx(prev => ({ ...prev, [msg.worker_name as string]: msg.pct_used as number }));
          }
        } else {
          refetch(); refetchMsgs();
        }
      } catch {
        refetch(); refetchMsgs();
      }
    };
    return () => ws.close();
  }, [swarmId, token]);

  // Auto-switch to Activity tab when swarm starts running
  useEffect(() => {
    if (!swarm) return;
    const prev = prevStatusRef.current;
    if (prev !== 'running' && swarm.status === 'running') {
      setActiveTab('messages');
    }
    // Clear live events when swarm stops
    if (prev === 'running' && swarm.status !== 'running') {
      setLiveEvents([]);
    }
    // Clear planner stream once planning finishes
    if (prev === 'planning' && swarm.status !== 'planning') {
      setPlannerText('');
    }
    prevStatusRef.current = swarm.status;
  }, [swarm?.status]);

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

      {/* Planning live stream banner */}
      {swarm.status === 'planning' && (
        <div className="mb-5 border border-[var(--acm-accent)] rounded-xl overflow-hidden bg-[oklch(0.84_0.16_82/0.03)]">
          <div className="flex items-center gap-2 px-4 py-2.5 border-b border-[var(--acm-accent)] bg-[oklch(0.84_0.16_82/0.06)]">
            <Loader2 size={14} className="animate-spin text-[var(--acm-accent)] shrink-0" />
            <span className="text-[13px] font-medium text-[var(--acm-fg)]">Designing your team…</span>
            <span className="text-[11px] text-[var(--acm-fg-4)] ml-1">streaming planner output</span>
            <span className="dot dot-accent acm-pulse ml-auto" />
          </div>
          {plannerText ? (
            <pre className="p-3 text-[11px] text-[var(--acm-fg-3)] mono whitespace-pre-wrap max-h-64 overflow-y-auto leading-relaxed">
              {plannerText}
            </pre>
          ) : (
            <p className="px-4 py-3 text-[11px] text-[var(--acm-fg-4)] italic">
              Waiting for model to start generating…
            </p>
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
          { id: 'messages', label: 'Activity', icon: <Activity size={14} />, badge: unseenQuestions + (activeTab !== 'messages' && liveEvents.length > 0 && swarm.status === 'running' ? 1 : 0) },
          { id: 'chats', label: 'Chats', icon: <MessageSquare size={14} /> },
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
            : (swarm.workers || []).map(w => <WorkerCard key={w.id} worker={w} swarmId={swarmId} onUpdate={refetch} ctxPct={workerCtx[w.name] ?? null} />)
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
          {/* Live activity strip — shows real-time worker events */}
          {(['running', 'planning', 'clarifying'].includes(swarm.status) || liveEvents.length > 0) && (
            <div className="acm-card p-3 mb-1">
              <div className="flex items-center gap-2 mb-2">
                <Radio size={12} className="text-[var(--acm-accent)]" />
                <span className="label text-[var(--acm-fg-3)]">Live</span>
                {['running', 'planning', 'clarifying'].includes(swarm.status) && (
                  <span className="dot dot-accent acm-pulse ml-auto" />
                )}
              </div>
              {liveEvents.length === 0 ? (
                <p className="text-[11px] text-[var(--acm-fg-4)] italic">
                  {swarm.status === 'planning'   ? 'Planning team — LLM thinking…' :
                   swarm.status === 'clarifying' ? 'Generating clarification questions…' :
                   'Waiting for worker activity…'}
                </p>
              ) : (
                <div className="space-y-0.5 max-h-48 overflow-y-auto">
                  {liveEvents.map((e, i) => <LiveEventRow key={i} event={e} />)}
                </div>
              )}
            </div>
          )}

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

      {activeTab === 'chats' && (
        <SwarmChatsTab swarmId={swarmId} selectedChannel={selectedChannel} onSelect={setSelectedChannel} fetchAPI={fetchAPI} />
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
