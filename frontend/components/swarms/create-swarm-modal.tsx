'use client';

import React, { useState, useRef, useCallback } from 'react';
import { Loader2, FileText, X, Upload, FolderOpen } from 'lucide-react';
import { useAuthStore } from '@/stores/auth-store';
import { useAPI } from '@/hooks/use-api';
import { Swarm } from './shared';

export function CreateSwarmModal({ onClose, onCreated }: { onClose: () => void; onCreated: (id: number) => void }) {
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
