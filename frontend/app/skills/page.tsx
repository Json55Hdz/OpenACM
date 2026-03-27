'use client';

import { useState } from 'react';
import { AppLayout } from '@/components/layout/app-layout';
import { useSkills } from '@/hooks/use-api';
import {
  Brain,
  Plus,
  Edit2,
  Trash2,
  Power,
  PowerOff,
  FileCode,
  Sparkles,
  X,
  Loader2,
  AlertCircle
} from 'lucide-react';
import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';
import { toast } from 'sonner';

function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

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

function SkillCard({ 
  skill, 
  onToggle, 
  onEdit, 
  onDelete 
}: { 
  skill: Skill; 
  onToggle: (id: number, activate: boolean) => void;
  onEdit: (skill: Skill) => void;
  onDelete: (id: number) => void;
}) {
  return (
    <div className={cn(
      "bg-slate-900 rounded-xl border p-5 transition-all",
      skill.is_active 
        ? "border-slate-800 hover:border-slate-700" 
        : "border-slate-800/50 opacity-60"
    )}>
      <div className="flex items-start justify-between mb-4">
        <div className="flex items-center gap-3">
          <div className={cn(
            "w-12 h-12 rounded-xl flex items-center justify-center",
            skill.is_active ? "bg-blue-600/20" : "bg-slate-800"
          )}>
            <Brain size={24} className={skill.is_active ? "text-blue-400" : "text-slate-500"} />
          </div>
          <div>
            <h3 className="font-semibold text-white">{skill.name}</h3>
            <div className="flex items-center gap-2 mt-1">
              <span className={cn(
                "text-xs px-2 py-0.5 rounded-full",
                skill.is_active
                  ? "bg-green-500/20 text-green-400"
                  : "bg-slate-700 text-slate-400"
              )}>
                {skill.is_active ? 'Active' : 'Inactive'}
              </span>
              {skill.category && (
                <span className="text-xs text-slate-500 flex items-center gap-1">
                  <FileCode size={12} />
                  {skill.category}
                </span>
              )}
              {skill.is_builtin && (
                <span className="text-xs px-2 py-0.5 rounded-full bg-blue-500/20 text-blue-400">
                  Built-in
                </span>
              )}
            </div>
          </div>
        </div>
        
        <div className="flex items-center gap-1">
          <button
            onClick={() => onToggle(skill.id, !skill.is_active)}
            className={cn(
              "p-2 rounded-lg transition-colors",
              skill.is_active 
                ? "text-green-400 hover:bg-green-500/20" 
                : "text-slate-500 hover:bg-slate-800"
            )}
            title={skill.is_active ? 'Deactivate' : 'Activate'}
          >
            {skill.is_active ? <Power size={18} /> : <PowerOff size={18} />}
          </button>
          <button
            onClick={() => onEdit(skill)}
            className="p-2 text-slate-400 hover:text-blue-400 hover:bg-blue-500/20 rounded-lg transition-colors"
            title="Edit"
          >
            <Edit2 size={18} />
          </button>
          <button
            onClick={() => onDelete(skill.id)}
            className="p-2 text-slate-400 hover:text-red-400 hover:bg-red-500/20 rounded-lg transition-colors"
            title="Delete"
          >
            <Trash2 size={18} />
          </button>
        </div>
      </div>
      
      <p className="text-sm text-slate-400 mb-4 line-clamp-2">{skill.description}</p>
      
      <div className="bg-slate-950 rounded-lg p-3">
        <p className="text-xs text-slate-500 uppercase tracking-wider mb-2">Content</p>
        <p className="text-xs text-slate-400 line-clamp-3 font-mono">{skill.content}</p>
      </div>
    </div>
  );
}

function SkillModal({
  isOpen,
  onClose,
  onSubmit,
  initialData,
  isLoading,
  mode
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
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70">
      <div className="bg-slate-900 rounded-xl border border-slate-800 w-full max-w-2xl max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between p-6 border-b border-slate-800">
          <h2 className="text-xl font-semibold text-white">
            {mode === 'create' ? 'New Skill' : 'Edit Skill'}
          </h2>
          <button
            onClick={onClose}
            className="p-2 text-slate-400 hover:text-white rounded-lg hover:bg-slate-800"
          >
            <X size={20} />
          </button>
        </div>
        
        <form onSubmit={handleSubmit} className="p-6 space-y-4">
          <div>
            <label className="block text-sm font-medium text-slate-300 mb-2">
              Name
            </label>
            <input
              type="text"
              value={formData.name}
              onChange={(e) => setFormData({ ...formData, name: e.target.value })}
              className="w-full px-4 py-2 bg-slate-800 border border-slate-700 rounded-lg text-white placeholder-slate-500 focus:outline-none focus:border-blue-500"
              placeholder="e.g. code-reviewer"
              required
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-slate-300 mb-2">
              Description
            </label>
            <input
              type="text"
              value={formData.description}
              onChange={(e) => setFormData({ ...formData, description: e.target.value })}
              className="w-full px-4 py-2 bg-slate-800 border border-slate-700 rounded-lg text-white placeholder-slate-500 focus:outline-none focus:border-blue-500"
              placeholder="Brief description of the skill"
              required
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-slate-300 mb-2">
              Content
            </label>
            <textarea
              value={formData.content}
              onChange={(e) => setFormData({ ...formData, content: e.target.value })}
              rows={6}
              className="w-full px-4 py-2 bg-slate-800 border border-slate-700 rounded-lg text-white placeholder-slate-500 focus:outline-none focus:border-blue-500 font-mono text-sm"
              placeholder="System instructions / markdown content for this skill..."
              required
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-slate-300 mb-2">
              Category
            </label>
            <select
              value={formData.category}
              onChange={(e) => setFormData({ ...formData, category: e.target.value })}
              className="w-full px-4 py-2 bg-slate-800 border border-slate-700 rounded-lg text-white focus:outline-none focus:border-blue-500"
            >
              <option value="custom">Custom</option>
              <option value="general">General</option>
              <option value="coding">Coding</option>
              <option value="writing">Writing</option>
              <option value="analysis">Analysis</option>
            </select>
          </div>
          
          <div className="flex justify-end gap-3 pt-4">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 text-slate-400 hover:text-white transition-colors"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={isLoading}
              className="flex items-center gap-2 px-6 py-2 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white rounded-lg transition-colors"
            >
              {isLoading && <Loader2 size={18} className="animate-spin" />}
              {mode === 'create' ? 'Create' : 'Save'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

function GenerateSkillModal({
  isOpen,
  onClose,
  onSubmit,
  isLoading
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
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70">
      <div className="bg-slate-900 rounded-xl border border-slate-800 w-full max-w-lg">
        <div className="flex items-center justify-between p-6 border-b border-slate-800">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 bg-purple-600/20 rounded-lg flex items-center justify-center">
              <Sparkles size={20} className="text-purple-400" />
            </div>
            <div>
              <h2 className="text-xl font-semibold text-white">Generate with AI</h2>
              <p className="text-sm text-slate-500">AI will create a skill automatically</p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-2 text-slate-400 hover:text-white rounded-lg hover:bg-slate-800"
          >
            <X size={20} />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="p-6 space-y-4">
          <div>
            <label className="block text-sm font-medium text-slate-300 mb-2">
              Skill name
            </label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="w-full px-4 py-2 bg-slate-800 border border-slate-700 rounded-lg text-white placeholder-slate-500 focus:outline-none focus:border-blue-500"
              placeholder="e.g. python-code-optimizer"
              required
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-slate-300 mb-2">
              Describe the skill you need
            </label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={4}
              className="w-full px-4 py-2 bg-slate-800 border border-slate-700 rounded-lg text-white placeholder-slate-500 focus:outline-none focus:border-blue-500"
              placeholder="e.g. A skill that analyzes Python code and suggests performance improvements..."
              required
            />
          </div>

          <div className="bg-blue-500/10 border border-blue-500/20 rounded-lg p-4">
            <div className="flex items-start gap-3">
              <AlertCircle size={20} className="text-blue-400 flex-shrink-0 mt-0.5" />
              <p className="text-sm text-blue-300">
                AI will generate the content and configuration based on your description.
              </p>
            </div>
          </div>

          <div className="flex justify-end gap-3 pt-2">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 text-slate-400 hover:text-white transition-colors"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={isLoading}
              className="flex items-center gap-2 px-6 py-2 bg-purple-600 hover:bg-purple-700 disabled:opacity-50 text-white rounded-lg transition-colors"
            >
              {isLoading && <Loader2 size={18} className="animate-spin" />}
              <Sparkles size={18} />
              Generate Skill
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

export default function SkillsPage() {
  const { 
    skills, 
    isLoading, 
    toggleSkill, 
    deleteSkill, 
    createSkill, 
    updateSkill,
    generateSkill 
  } = useSkills();
  
  const [isCreateModalOpen, setIsCreateModalOpen] = useState(false);
  const [isEditModalOpen, setIsEditModalOpen] = useState(false);
  const [isGenerateModalOpen, setIsGenerateModalOpen] = useState(false);
  const [editingSkill, setEditingSkill] = useState<Skill | undefined>();
  const [isSubmitting, setIsSubmitting] = useState(false);
  
  const skillList: Skill[] = skills || [];
  
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
      <div className="p-6 lg:p-8">
        {/* Header */}
        <header className="mb-8">
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
            <div>
              <h1 className="text-3xl font-bold text-white">Skills</h1>
              <p className="text-slate-400 mt-1">
                Manage the assistant's capabilities and behaviors
              </p>
            </div>
            
            <div className="flex gap-3">
              <button
                onClick={() => setIsGenerateModalOpen(true)}
                className="flex items-center gap-2 px-4 py-2 bg-purple-600/20 text-purple-400 border border-purple-600/30 rounded-lg hover:bg-purple-600/30 transition-colors"
              >
                <Sparkles size={18} />
                <span>Generate with AI</span>
              </button>
              <button
                onClick={() => setIsCreateModalOpen(true)}
                className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg transition-colors"
              >
                <Plus size={18} />
                <span>New Skill</span>
              </button>
            </div>
          </div>
        </header>
        
        {/* Skills Grid */}
        {isLoading ? (
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            {[1, 2, 3, 4].map((i) => (
              <div key={i} className="bg-slate-900 rounded-xl border border-slate-800 p-5 h-64 animate-pulse" />
            ))}
          </div>
        ) : skillList.length === 0 ? (
          <div className="text-center py-16 bg-slate-900 rounded-xl border border-slate-800">
            <Brain size={64} className="mx-auto text-slate-600 mb-4" />
            <h3 className="text-xl font-medium text-slate-300 mb-2">No skills yet</h3>
            <p className="text-slate-500 mb-6 max-w-md mx-auto">
              Create your first skill to expand the assistant's capabilities or generate one automatically with AI.
            </p>
            <div className="flex justify-center gap-3">
              <button
                onClick={() => setIsGenerateModalOpen(true)}
                className="flex items-center gap-2 px-4 py-2 bg-purple-600/20 text-purple-400 border border-purple-600/30 rounded-lg hover:bg-purple-600/30 transition-colors"
              >
                <Sparkles size={18} />
                Generate with AI
              </button>
              <button
                onClick={() => setIsCreateModalOpen(true)}
                className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg transition-colors"
              >
                <Plus size={18} />
                Create Manually
              </button>
            </div>
          </div>
        ) : (
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
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
        
        {/* Create Modal */}
        <SkillModal
          isOpen={isCreateModalOpen}
          onClose={() => setIsCreateModalOpen(false)}
          onSubmit={handleCreate}
          isLoading={isSubmitting}
          mode="create"
        />
        
        {/* Edit Modal */}
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
        
        {/* Generate Modal */}
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
