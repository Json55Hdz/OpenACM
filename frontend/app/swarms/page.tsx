'use client';

import { useState, Suspense } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { Plus, Trash2, Loader2, Users, ListTodo, ChevronRight } from 'lucide-react';
import { AppLayout } from '@/components/layout/app-layout';
import { useAPI } from '@/hooks/use-api';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { CreateSwarmModal } from '@/components/swarms/create-swarm-modal';
import { SwarmDetail } from '@/components/swarms/swarm-detail';
import { Swarm, SWARM_DOT } from '@/components/swarms/shared';

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
