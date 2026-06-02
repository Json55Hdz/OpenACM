'use client';

import { useState } from 'react';
import { X, Plus, Trash2, Edit2 } from 'lucide-react';

const API = '/api/gmail-classifier';

const PRESET_COLORS = [
  '#6366f1', '#3b82f6', '#10b981', '#f59e0b',
  '#ef4444', '#8b5cf6', '#ec4899', '#6b7280',
  '#0ea5e9', '#14b8a6', '#f97316', '#84cc16',
];

const PRESET_ICONS = [
  'Tag', 'Mail', 'Car', 'FileText', 'Inbox',
  'Briefcase', 'Home', 'Star', 'Bell', 'Users',
  'ShoppingCart', 'Calendar', 'Map', 'Truck', 'Landmark',
];

interface Category {
  id: number;
  name: string;
  description: string;
  color: string;
  icon: string;
}

interface FormState {
  name: string;
  description: string;
  color: string;
  icon: string;
}

interface CategoryManagerProps {
  categories: Category[];
  token: string;
  onClose: () => void;
  onSaved: () => void;
}

export function CategoryManager({ categories, token, onClose, onSaved }: CategoryManagerProps) {
  const [editingId, setEditingId] = useState<number | 'new' | null>(null);
  const [form, setForm] = useState<FormState>({ name: '', description: '', color: '#6366f1', icon: 'Tag' });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  const headers = { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' };

  const startNew = () => {
    setForm({ name: '', description: '', color: '#6366f1', icon: 'Tag' });
    setEditingId('new');
    setError('');
  };

  const startEdit = (cat: Category) => {
    setForm({ name: cat.name, description: cat.description, color: cat.color, icon: cat.icon });
    setEditingId(cat.id);
    setError('');
  };

  const handleSave = async () => {
    if (!form.name.trim()) { setError('El nombre es requerido'); return; }
    setSaving(true);
    setError('');
    try {
      const url = editingId === 'new' ? `${API}/categories` : `${API}/categories/${editingId}`;
      const method = editingId === 'new' ? 'POST' : 'PUT';
      const res = await fetch(url, { method, headers, body: JSON.stringify(form) });
      if (!res.ok) {
        const e = await res.json();
        setError(e.detail || 'Error al guardar');
        return;
      }
      onSaved();
      setEditingId(null);
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (id: number) => {
    if (!confirm("¿Eliminar esta categoría? Los correos pasarán a 'Otros'.")) return;
    await fetch(`${API}/categories/${id}`, { method: 'DELETE', headers });
    onSaved();
  };

  return (
    <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50">
      <div className="bg-[var(--acm-base)] border border-[var(--acm-border)] rounded-[var(--acm-radius)] w-full max-w-lg max-h-[80vh] flex flex-col shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-[var(--acm-border)]">
          <div>
            <span className="acm-breadcrumb">/ gmail / categorías</span>
            <h2 className="text-[15px] font-semibold text-[var(--acm-fg)]">Gestionar Categorías</h2>
          </div>
          <button onClick={onClose} className="p-1.5 hover:bg-[var(--acm-elev)] rounded text-[var(--acm-fg-3)]">
            <X size={16} />
          </button>
        </div>

        {/* List */}
        <div className="flex-1 overflow-y-auto acm-scroll px-5 py-3 space-y-2">
          {categories.map(cat => (
            <div key={cat.id} className="acm-card overflow-hidden">
              {editingId === cat.id ? (
                <CategoryForm
                  form={form}
                  onChange={setForm}
                  onSave={handleSave}
                  onCancel={() => setEditingId(null)}
                  saving={saving}
                  error={error}
                />
              ) : (
                <div className="flex items-center gap-3 px-4 py-3">
                  <div className="w-3 h-3 rounded-full flex-shrink-0" style={{ backgroundColor: cat.color }} />
                  <div className="flex-1 min-w-0">
                    <p className="text-[13px] font-medium text-[var(--acm-fg)]">{cat.name}</p>
                    {cat.description && (
                      <p className="text-[11px] text-[var(--acm-fg-4)] truncate mt-0.5">{cat.description}</p>
                    )}
                  </div>
                  {cat.name !== 'Otros' && (
                    <div className="flex gap-1">
                      <button
                        onClick={() => startEdit(cat)}
                        className="p-1.5 hover:bg-[var(--acm-elev)] rounded text-[var(--acm-fg-4)] hover:text-[var(--acm-fg-2)] transition-colors"
                      >
                        <Edit2 size={13} />
                      </button>
                      <button
                        onClick={() => handleDelete(cat.id)}
                        className="p-1.5 hover:bg-[var(--acm-elev)] rounded text-[var(--acm-fg-4)] hover:text-[var(--acm-err)] transition-colors"
                      >
                        <Trash2 size={13} />
                      </button>
                    </div>
                  )}
                  {cat.name === 'Otros' && (
                    <span className="text-[10px] text-[var(--acm-fg-4)] label">default</span>
                  )}
                </div>
              )}
            </div>
          ))}

          {editingId === 'new' && (
            <div className="border border-[var(--acm-accent)] rounded-[var(--acm-radius)] overflow-hidden">
              <CategoryForm
                form={form}
                onChange={setForm}
                onSave={handleSave}
                onCancel={() => setEditingId(null)}
                saving={saving}
                error={error}
              />
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="px-5 py-3 border-t border-[var(--acm-border)]">
          <button
            onClick={startNew}
            disabled={editingId !== null}
            className="btn-secondary text-[12px] py-[6px] px-3 disabled:opacity-40"
          >
            <Plus size={13} /> Nueva categoría
          </button>
        </div>
      </div>
    </div>
  );
}

function CategoryForm({
  form, onChange, onSave, onCancel, saving, error,
}: {
  form: FormState;
  onChange: (f: FormState) => void;
  onSave: () => void;
  onCancel: () => void;
  saving: boolean;
  error: string;
}) {
  return (
    <div className="px-4 py-4 space-y-4 bg-[var(--acm-elev)]">
      <div>
        <label className="label block mb-1.5">Nombre *</label>
        <input
          className="acm-input text-[13px]"
          placeholder="Ej: Parqueaderos"
          value={form.name}
          onChange={e => onChange({ ...form, name: e.target.value })}
          autoFocus
        />
      </div>
      <div>
        <label className="label block mb-1.5">Descripción</label>
        <textarea
          className="w-full bg-transparent border-b border-[var(--acm-border)] text-[var(--acm-fg)] text-[13px] py-2 resize-none outline-none focus:border-[var(--acm-accent)] transition-colors placeholder:text-[var(--acm-fg-4)]"
          placeholder="Describe el tipo de correos para que la IA clasifique mejor"
          rows={2}
          value={form.description}
          onChange={e => onChange({ ...form, description: e.target.value })}
        />
      </div>

      {/* Color picker */}
      <div>
        <label className="label block mb-2">Color</label>
        <div className="flex gap-2 flex-wrap">
          {PRESET_COLORS.map(c => (
            <button
              key={c}
              onClick={() => onChange({ ...form, color: c })}
              className={`w-6 h-6 rounded-full transition-transform ${form.color === c ? 'scale-125 ring-2 ring-white/50' : 'hover:scale-110'}`}
              style={{ backgroundColor: c }}
            />
          ))}
        </div>
      </div>

      {/* Icon picker */}
      <div>
        <label className="label block mb-2">Icono</label>
        <div className="flex gap-1.5 flex-wrap">
          {PRESET_ICONS.map(icon => (
            <button
              key={icon}
              onClick={() => onChange({ ...form, icon })}
              className={`px-2 py-1 text-[11px] rounded transition-colors ${
                form.icon === icon
                  ? 'bg-[var(--acm-accent)] text-[oklch(0.18_0.015_80)] font-medium'
                  : 'bg-[var(--acm-card)] border border-[var(--acm-border)] text-[var(--acm-fg-3)] hover:border-[var(--acm-accent)] hover:text-[var(--acm-accent)]'
              }`}
            >
              {icon}
            </button>
          ))}
        </div>
      </div>

      {error && <p className="text-[11px] text-[var(--acm-err)]">{error}</p>}

      <div className="flex gap-2 pt-1">
        <button onClick={onSave} disabled={saving} className="btn-primary text-[12px] py-[7px] px-3">
          {saving ? 'Guardando…' : 'Guardar'}
        </button>
        <button onClick={onCancel} className="btn-secondary text-[12px] py-[7px] px-3">
          Cancelar
        </button>
      </div>
    </div>
  );
}
