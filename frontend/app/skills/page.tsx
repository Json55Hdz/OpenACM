'use client';

import { useState } from 'react';
import { AppLayout } from '@/components/layout/app-layout';
import { useSkills } from '@/hooks/use-api';
import {
  Brain,
  Plus,
  Edit2,
  Trash2,
  MoreVertical,
  Sparkles,
  X,
  Loader2,
  AlertCircle,
} from 'lucide-react';
import { toast } from 'sonner';

// ─── Types ───────────────────────────────────────────────────────────────────

interface Skill {
  id: number;
  name: string;
  description: string;
  content: string;
  category: string;
  is_active: boolean;
  is_builtin: boolean;
  created_at: string;
  updated_at: string;
}

interface SkillFormData {
  name: string;
  description: string;
  content: string;
  category: string;
}

// ─── Shared field style helper ────────────────────────────────────────────────

const fieldStyle: React.CSSProperties = {
  width: '100%',
  padding: '8px 12px',
  background: 'var(--acm-elev)',
  border: '1px solid var(--acm-border)',
  borderRadius: 'var(--acm-radius)',
  color: 'var(--acm-fg)',
  fontSize: '13px',
  outline: 'none',
  fontFamily: 'inherit',
  boxSizing: 'border-box',
};

// ─── SkillCard ────────────────────────────────────────────────────────────────

function SkillCard({
  skill,
  onToggle,
  onEdit,
  onDelete,
}: {
  skill: Skill;
  onToggle: (id: number, activate: boolean) => void;
  onEdit: (skill: Skill) => void;
  onDelete: (id: number) => void;
}) {
  const [menuOpen, setMenuOpen] = useState(false);

  return (
    <div
      className="acm-card"
      style={{
        padding: '18px 20px',
        opacity: skill.is_active ? 1 : 0.55,
        position: 'relative',
        display: 'flex',
        flexDirection: 'column',
        gap: 12,
      }}
    >
      {/* ── Top row: icon + name + menu ── */}
      <div className="flex items-start gap-3">
        {/* Icon box */}
        <div
          style={{
            width: 44,
            height: 44,
            borderRadius: 10,
            background: 'var(--acm-elev)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            flexShrink: 0,
          }}
        >
          <Brain
            size={22}
            style={{
              color: skill.is_active ? 'var(--acm-accent)' : 'var(--acm-fg-4)',
            }}
          />
        </div>

        <div className="flex-1 min-w-0">
          <p className="mono text-sm font-semibold" style={{ color: 'var(--acm-fg)' }}>
            {skill.name}
          </p>
          {skill.description && (
            <p
              className="text-xs mt-0.5"
              style={{
                color: 'var(--acm-fg-3)',
                display: '-webkit-box',
                WebkitLineClamp: 2,
                WebkitBoxOrient: 'vertical',
                overflow: 'hidden',
              }}
            >
              {skill.description}
            </p>
          )}
        </div>

        {/* Dots menu */}
        <div style={{ position: 'relative', flexShrink: 0 }}>
          <button
            onClick={() => setMenuOpen((o) => !o)}
            style={{
              background: 'transparent',
              border: 'none',
              cursor: 'pointer',
              color: 'var(--acm-fg-4)',
              padding: '4px',
              borderRadius: 6,
              display: 'flex',
              alignItems: 'center',
            }}
          >
            <MoreVertical size={16} />
          </button>

          {menuOpen && (
            <>
              {/* backdrop */}
              <div
                style={{ position: 'fixed', inset: 0, zIndex: 40 }}
                onClick={() => setMenuOpen(false)}
              />
              <div
                style={{
                  position: 'absolute',
                  right: 0,
                  top: '110%',
                  zIndex: 50,
                  background: 'var(--acm-elev)',
                  border: '1px solid var(--acm-border)',
                  borderRadius: 8,
                  minWidth: 148,
                  boxShadow: '0 8px 24px oklch(0 0 0 / 0.5)',
                  overflow: 'hidden',
                }}
              >
                {[
                  {
                    label: skill.is_active ? 'Deactivate' : 'Activate',
                    icon: null,
                    color: skill.is_active ? 'var(--acm-warn)' : 'var(--acm-ok)',
                    action: () => { onToggle(skill.id, !skill.is_active); setMenuOpen(false); },
                  },
                  {
                    label: 'Edit',
                    icon: Edit2,
                    color: 'var(--acm-fg-2)',
                    action: () => { onEdit(skill); setMenuOpen(false); },
                  },
                  {
                    label: 'Delete',
                    icon: Trash2,
                    color: 'var(--acm-err)',
                    action: () => { onDelete(skill.id); setMenuOpen(false); },
                  },
                ].map((item) => (
                  <button
                    key={item.label}
                    onClick={item.action}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: 8,
                      width: '100%',
                      padding: '9px 14px',
                      background: 'transparent',
                      border: 'none',
                      cursor: 'pointer',
                      color: item.color,
                      fontSize: '13px',
                      textAlign: 'left',
                    }}
                    onMouseEnter={(e) =>
                      ((e.currentTarget as HTMLElement).style.background = 'var(--acm-card)')
                    }
                    onMouseLeave={(e) =>
                      ((e.currentTarget as HTMLElement).style.background = 'transparent')
                    }
                  >
                    {item.icon && <item.icon size={13} />}
                    {item.label}
                  </button>
                ))}
              </div>
            </>
          )}
        </div>
      </div>

      {/* ── Content preview ── */}
      {skill.content && (
        <div
          className="mono text-xs acm-scroll"
          style={{
            color: 'var(--acm-fg-4)',
            background: 'var(--acm-base)',
            borderRadius: 6,
            padding: '8px 10px',
            maxHeight: 56,
            overflowY: 'auto',
            whiteSpace: 'pre-wrap',
            wordBreak: 'break-word',
            lineHeight: 1.5,
          }}
        >
          {skill.content}
        </div>
      )}

      {/* ── Bottom row: category + builtin + on/off pill ── */}
      <div className="flex items-center gap-2" style={{ flexWrap: 'wrap' }}>
        {skill.category && (
          <span
            className="mono"
            style={{
              fontSize: '10px',
              letterSpacing: '0.09em',
              textTransform: 'uppercase',
              border: '1px solid var(--acm-border)',
              borderRadius: 5,
              padding: '2px 7px',
              color: 'var(--acm-fg-3)',
            }}
          >
            {skill.category}
          </span>
        )}

        {skill.is_builtin && (
          <span
            className="mono"
            style={{
              fontSize: '10px',
              letterSpacing: '0.06em',
              textTransform: 'uppercase',
              color: 'var(--acm-accent)',
            }}
          >
            builtin
          </span>
        )}

        <span style={{ flex: 1 }} />

        {/* On/off pill */}
        <button
          onClick={() => onToggle(skill.id, !skill.is_active)}
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: 5,
            background: 'transparent',
            border: '1px solid var(--acm-border)',
            borderRadius: 20,
            padding: '3px 9px',
            cursor: 'pointer',
            transition: 'border-color 140ms',
          }}
          onMouseEnter={(e) =>
            ((e.currentTarget as HTMLElement).style.borderColor = 'var(--acm-accent)')
          }
          onMouseLeave={(e) =>
            ((e.currentTarget as HTMLElement).style.borderColor = 'var(--acm-border)')
          }
        >
          <span
            className={`dot ${skill.is_active ? 'dot-ok' : 'dot-idle'}`}
          />
          <span
            className="mono"
            style={{
              fontSize: '10px',
              letterSpacing: '0.09em',
              textTransform: 'uppercase',
              color: skill.is_active ? 'var(--acm-ok)' : 'var(--acm-fg-4)',
            }}
          >
            {skill.is_active ? 'on' : 'off'}
          </span>
        </button>
      </div>
    </div>
  );
}

// ─── SkillModal (create / edit) ───────────────────────────────────────────────

function SkillModal({
  isOpen,
  onClose,
  onSubmit,
  initialData,
  isLoading,
  mode,
}: {
  isOpen: boolean;
  onClose: () => void;
  onSubmit: (data: SkillFormData) => void;
  initialData?: Skill;
  isLoading: boolean;
  mode: 'create' | 'edit';
}) {
  const [formData, setFormData] = useState<SkillFormData>({
    name: initialData?.name || '',
    description: initialData?.description || '',
    content: initialData?.content || '',
    category: initialData?.category || 'custom',
  });

  if (!isOpen) return null;

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    onSubmit(formData);
  };

  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 50,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: 16,
        background: 'oklch(0 0 0 / 0.72)',
      }}
    >
      <div
        className="acm-card acm-scroll"
        style={{
          width: '100%',
          maxWidth: 560,
          maxHeight: '90vh',
          overflowY: 'auto',
        }}
      >
        {/* Header */}
        <div
          className="flex items-center justify-between"
          style={{
            padding: '18px 20px',
            borderBottom: '1px solid var(--acm-border)',
          }}
        >
          <div>
            <span className="acm-breadcrumb" style={{ marginBottom: 2 }}>
              Skills
            </span>
            <h2 className="text-base font-semibold" style={{ color: 'var(--acm-fg)' }}>
              {mode === 'create' ? 'New Skill' : 'Edit Skill'}
            </h2>
          </div>
          <button
            onClick={onClose}
            style={{
              background: 'transparent',
              border: 'none',
              cursor: 'pointer',
              color: 'var(--acm-fg-4)',
              padding: 4,
              borderRadius: 6,
              display: 'flex',
            }}
          >
            <X size={18} />
          </button>
        </div>

        <form onSubmit={handleSubmit} style={{ padding: '20px', display: 'flex', flexDirection: 'column', gap: 16 }}>
          {/* Name */}
          <div>
            <p className="label mb-2">Name</p>
            <input
              type="text"
              value={formData.name}
              onChange={(e) => setFormData({ ...formData, name: e.target.value })}
              style={fieldStyle}
              placeholder="e.g. code-reviewer"
              required
              disabled={mode === 'edit'} // name is immutable on edit
            />
          </div>

          {/* Description */}
          <div>
            <p className="label mb-2">Description</p>
            <input
              type="text"
              value={formData.description}
              onChange={(e) => setFormData({ ...formData, description: e.target.value })}
              style={fieldStyle}
              placeholder="Brief description of the skill"
              required
            />
          </div>

          {/* Content */}
          <div>
            <p className="label mb-2">Content</p>
            <textarea
              value={formData.content}
              onChange={(e) => setFormData({ ...formData, content: e.target.value })}
              rows={7}
              style={{ ...fieldStyle, fontFamily: "'JetBrains Mono', ui-monospace, monospace", resize: 'vertical' }}
              placeholder="System instructions / markdown content for this skill..."
              required
            />
          </div>

          {/* Category */}
          <div>
            <p className="label mb-2">Category</p>
            <select
              value={formData.category}
              onChange={(e) => setFormData({ ...formData, category: e.target.value })}
              style={fieldStyle}
            >
              <option value="custom">Custom</option>
              <option value="general">General</option>
              <option value="coding">Coding</option>
              <option value="writing">Writing</option>
              <option value="analysis">Analysis</option>
            </select>
          </div>

          {/* Actions */}
          <div className="flex items-center justify-end gap-3" style={{ paddingTop: 4 }}>
            <button
              type="button"
              onClick={onClose}
              className="btn-secondary"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={isLoading}
              className="btn-primary"
            >
              {isLoading && <Loader2 size={15} className="animate-spin" />}
              {mode === 'create' ? 'Create' : 'Save'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

// ─── GenerateSkillModal ───────────────────────────────────────────────────────

function GenerateSkillModal({
  isOpen,
  onClose,
  onSubmit,
  isLoading,
}: {
  isOpen: boolean;
  onClose: () => void;
  onSubmit: (name: string, description: string) => void;
  isLoading: boolean;
}) {
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');

  if (!isOpen) return null;

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    onSubmit(name, description);
  };

  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 50,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: 16,
        background: 'oklch(0 0 0 / 0.72)',
      }}
    >
      <div
        className="acm-card"
        style={{ width: '100%', maxWidth: 480 }}
      >
        {/* Header */}
        <div
          className="flex items-center justify-between"
          style={{
            padding: '18px 20px',
            borderBottom: '1px solid var(--acm-border)',
          }}
        >
          <div className="flex items-center gap-3">
            <div
              style={{
                width: 38,
                height: 38,
                borderRadius: 9,
                background: 'var(--acm-accent-tint)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
              }}
            >
              <Sparkles size={18} style={{ color: 'var(--acm-accent)' }} />
            </div>
            <div>
              <h2 className="text-base font-semibold" style={{ color: 'var(--acm-fg)' }}>
                Generate with AI
              </h2>
              <p className="text-xs" style={{ color: 'var(--acm-fg-4)' }}>
                AI will create a skill automatically
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            style={{
              background: 'transparent',
              border: 'none',
              cursor: 'pointer',
              color: 'var(--acm-fg-4)',
              padding: 4,
              borderRadius: 6,
              display: 'flex',
            }}
          >
            <X size={18} />
          </button>
        </div>

        <form onSubmit={handleSubmit} style={{ padding: '20px', display: 'flex', flexDirection: 'column', gap: 16 }}>
          {/* Name */}
          <div>
            <p className="label mb-2">Skill name</p>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              style={fieldStyle}
              placeholder="e.g. python-code-optimizer"
              required
            />
          </div>

          {/* Description */}
          <div>
            <p className="label mb-2">Describe the skill you need</p>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={4}
              style={{ ...fieldStyle, resize: 'vertical' }}
              placeholder="e.g. A skill that analyzes Python code and suggests performance improvements..."
              required
            />
          </div>

          {/* Info notice */}
          <div
            style={{
              background: 'var(--acm-accent-tint)',
              border: '1px solid oklch(0.84 0.16 82 / 0.2)',
              borderRadius: 8,
              padding: '10px 14px',
              display: 'flex',
              alignItems: 'flex-start',
              gap: 10,
            }}
          >
            <AlertCircle size={16} style={{ color: 'var(--acm-accent)', flexShrink: 0, marginTop: 1 }} />
            <p className="text-xs" style={{ color: 'var(--acm-fg-2)' }}>
              AI will generate the content and configuration based on your description.
            </p>
          </div>

          {/* Actions */}
          <div className="flex items-center justify-end gap-3" style={{ paddingTop: 4 }}>
            <button type="button" onClick={onClose} className="btn-secondary">
              Cancel
            </button>
            <button type="submit" disabled={isLoading} className="btn-primary">
              {isLoading && <Loader2 size={15} className="animate-spin" />}
              <Sparkles size={14} />
              Generate Skill
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function SkillsPage() {
  const {
    skills,
    isLoading,
    toggleSkill,
    deleteSkill,
    createSkill,
    updateSkill,
    generateSkill,
  } = useSkills();

  const [isCreateModalOpen, setIsCreateModalOpen] = useState(false);
  const [isEditModalOpen, setIsEditModalOpen] = useState(false);
  const [isGenerateModalOpen, setIsGenerateModalOpen] = useState(false);
  const [editingSkill, setEditingSkill] = useState<Skill | undefined>();
  const [isSubmitting, setIsSubmitting] = useState(false);

  const skillList: Skill[] = skills || [];
  const activeCount = skillList.filter((s) => s.is_active).length;

  const handleToggle = (id: number, activate: boolean) => {
    toggleSkill({ id, activate });
  };

  const handleDelete = (id: number) => {
    if (confirm('Are you sure you want to delete this skill?')) {
      deleteSkill(id);
    }
  };

  const handleEdit = (skill: Skill) => {
    setEditingSkill(skill);
    setIsEditModalOpen(true);
  };

  const handleCreate = async (data: SkillFormData) => {
    setIsSubmitting(true);
    createSkill({
      name: data.name,
      description: data.description,
      content: data.content,
      category: data.category,
    });

    setTimeout(() => {
      setIsSubmitting(false);
      setIsCreateModalOpen(false);
    }, 500);
  };

  const handleUpdate = async (data: SkillFormData) => {
    if (!editingSkill) return;

    setIsSubmitting(true);
    updateSkill({
      id: editingSkill.id,
      data: {
        description: data.description,
        content: data.content,
        category: data.category,
      },
    });

    setTimeout(() => {
      setIsSubmitting(false);
      setIsEditModalOpen(false);
      setEditingSkill(undefined);
    }, 500);
  };

  const handleGenerate = async (name: string, description: string) => {
    setIsSubmitting(true);
    generateSkill({ name, description });

    setTimeout(() => {
      setIsSubmitting(false);
      setIsGenerateModalOpen(false);
    }, 500);
  };

  return (
    <AppLayout>
      <div className="p-6 lg:p-8" style={{ maxWidth: 1280, margin: '0 auto' }}>

        {/* ── Header ── */}
        <header className="mb-7">
          <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-4">
            <div>
              <span className="acm-breadcrumb">System / Skills</span>
              <h1 className="text-2xl font-bold" style={{ color: 'var(--acm-fg)' }}>
                Skills
              </h1>
              <p className="mt-1 text-sm" style={{ color: 'var(--acm-fg-3)' }}>
                Manage the assistant's capabilities and behaviors
              </p>
            </div>

            <div className="flex items-center gap-2 flex-shrink-0">
              {skillList.length > 0 && (
                <div
                  className="flex items-center gap-2"
                  style={{
                    padding: '5px 12px',
                    background: 'var(--acm-card)',
                    border: '1px solid var(--acm-border)',
                    borderRadius: 'var(--acm-radius)',
                    marginRight: 4,
                  }}
                >
                  <span className="dot dot-ok" />
                  <span className="mono" style={{ fontSize: '11px', color: 'var(--acm-fg-3)' }}>
                    {activeCount}/{skillList.length} active
                  </span>
                </div>
              )}

              <button
                onClick={() => setIsGenerateModalOpen(true)}
                className="btn-secondary"
              >
                <Sparkles size={14} />
                Generate with AI
              </button>

              <button
                onClick={() => setIsCreateModalOpen(true)}
                className="btn-primary"
              >
                <Plus size={14} />
                New Skill
              </button>
            </div>
          </div>
        </header>

        {/* ── Skills Grid ── */}
        {isLoading ? (
          <div
            className="grid gap-4"
            style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))' }}
          >
            {[1, 2, 3, 4].map((i) => (
              <div
                key={i}
                className="acm-card"
                style={{
                  height: 200,
                  opacity: 0.35,
                  animation: 'acm-pulse 1.8s ease-in-out infinite',
                }}
              />
            ))}
          </div>
        ) : skillList.length === 0 ? (
          <div
            className="acm-card flex flex-col items-center justify-center"
            style={{ padding: '64px 32px', textAlign: 'center' }}
          >
            <Brain size={48} style={{ color: 'var(--acm-fg-4)', marginBottom: 16 }} />
            <h3 className="text-lg font-semibold mb-2" style={{ color: 'var(--acm-fg-2)' }}>
              No skills yet
            </h3>
            <p className="text-sm mb-6" style={{ color: 'var(--acm-fg-4)', maxWidth: 360 }}>
              Create your first skill to expand the assistant's capabilities or generate one
              automatically with AI.
            </p>
            <div className="flex items-center gap-3">
              <button
                onClick={() => setIsGenerateModalOpen(true)}
                className="btn-secondary"
              >
                <Sparkles size={14} />
                Generate with AI
              </button>
              <button
                onClick={() => setIsCreateModalOpen(true)}
                className="btn-primary"
              >
                <Plus size={14} />
                Create Manually
              </button>
            </div>
          </div>
        ) : (
          <div
            className="grid gap-4"
            style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))' }}
          >
            {skillList.map((skill) => (
              <SkillCard
                key={skill.id}
                skill={skill}
                onToggle={handleToggle}
                onEdit={handleEdit}
                onDelete={handleDelete}
              />
            ))}
          </div>
        )}

        {/* ── Create Modal ── */}
        <SkillModal
          isOpen={isCreateModalOpen}
          onClose={() => setIsCreateModalOpen(false)}
          onSubmit={handleCreate}
          isLoading={isSubmitting}
          mode="create"
        />

        {/* ── Edit Modal ── */}
        <SkillModal
          isOpen={isEditModalOpen}
          onClose={() => {
            setIsEditModalOpen(false);
            setEditingSkill(undefined);
          }}
          onSubmit={handleUpdate}
          initialData={editingSkill}
          isLoading={isSubmitting}
          mode="edit"
        />

        {/* ── Generate Modal ── */}
        <GenerateSkillModal
          isOpen={isGenerateModalOpen}
          onClose={() => setIsGenerateModalOpen(false)}
          onSubmit={handleGenerate}
          isLoading={isSubmitting}
        />
      </div>
    </AppLayout>
  );
}
