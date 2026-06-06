'use client';

import { useState } from 'react';
import { X, Plus, Trash2, Edit2, Download } from 'lucide-react';

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

type PatternType = 'sender_email' | 'sender_domain' | 'subject_contains';

const PATTERN_TYPE_LABELS: Record<PatternType, string> = {
  sender_email: 'Email exacto',
  sender_domain: 'Dominio',
  subject_contains: 'Asunto contiene',
};

const PATTERN_TYPE_PLACEHOLDERS: Record<PatternType, string> = {
  sender_email: 'notificaciones@dian.gov.co',
  sender_domain: 'procuraduria.gov.co',
  subject_contains: 'notificación judicial',
};

interface Pattern {
  type: PatternType;
  value: string;
}

interface Category {
  id: number;
  name: string;
  description: string;
  color: string;
  icon: string;
  context?: string;
  known_senders?: string[];
  patterns?: Pattern[];
}

interface FormState {
  name: string;
  description: string;
  color: string;
  icon: string;
  context: string;
  known_senders: string[];
  patterns: Pattern[];
}

const EMPTY_FORM: FormState = {
  name: '',
  description: '',
  color: '#6366f1',
  icon: 'Tag',
  context: '',
  known_senders: [],
  patterns: [],
};

interface CategoryManagerProps {
  categories: Category[];
  token: string;
  onClose: () => void;
  onSaved: () => void;
}

export function CategoryManager({ categories, token, onClose, onSaved }: CategoryManagerProps) {
  const [editingId, setEditingId] = useState<number | 'new' | null>(null);
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [importing, setImporting] = useState(false);
  const [importMsg, setImportMsg] = useState('');

  const headers = { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' };

  const handleImportLabels = async () => {
    setImporting(true);
    setImportMsg('');
    try {
      const res = await fetch(`${API}/categories/import-labels`, { method: 'POST', headers });
      const data = await res.json();
      if (!res.ok) {
        setImportMsg(data.detail || 'Error al importar etiquetas');
        return;
      }
      const created = data.created ?? 0;
      const skipped = data.skipped ?? 0;
      setImportMsg(
        created === 0
          ? `Sin nuevas etiquetas (${skipped} ya existían)`
          : `${created} categoría${created === 1 ? '' : 's'} creada${created === 1 ? '' : 's'}${skipped ? ` · ${skipped} ya existían` : ''}`
      );
      onSaved();
    } catch (e) {
      setImportMsg('Error de conexión');
    } finally {
      setImporting(false);
    }
  };

  const startNew = () => {
    setForm(EMPTY_FORM);
    setEditingId('new');
    setError('');
  };

  const startEdit = (cat: Category) => {
    setForm({
      name: cat.name,
      description: cat.description,
      color: cat.color,
      icon: cat.icon,
      context: cat.context || '',
      known_senders: cat.known_senders || [],
      patterns: cat.patterns || [],
    });
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
      // Drop empty patterns/senders before sending
      const payload = {
        ...form,
        known_senders: form.known_senders.map(s => s.trim()).filter(Boolean),
        patterns: form.patterns
          .map(p => ({ type: p.type, value: p.value.trim() }))
          .filter(p => p.value),
      };
      const res = await fetch(url, { method, headers, body: JSON.stringify(payload) });
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
      <div className="bg-[var(--acm-base)] border border-[var(--acm-border)] rounded-[var(--acm-radius)] w-full max-w-2xl max-h-[90vh] flex flex-col shadow-2xl">
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
                    {(cat.known_senders?.length || cat.patterns?.length) ? (
                      <p className="text-[10px] text-[var(--acm-fg-4)] mt-1">
                        {(cat.known_senders?.length || 0)} remitentes · {(cat.patterns?.length || 0)} patrones
                      </p>
                    ) : null}
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
        <div className="px-5 py-3 border-t border-[var(--acm-border)] flex items-center justify-between gap-3 flex-wrap">
          <div className="flex gap-2">
            <button
              onClick={startNew}
              disabled={editingId !== null}
              className="btn-secondary text-[12px] py-[6px] px-3 disabled:opacity-40"
            >
              <Plus size={13} /> Nueva categoría
            </button>
            <button
              onClick={handleImportLabels}
              disabled={importing || editingId !== null}
              title="Crear una categoría por cada etiqueta de usuario en tu Gmail"
              className="btn-secondary text-[12px] py-[6px] px-3 disabled:opacity-40"
            >
              <Download size={13} className={importing ? 'animate-pulse' : ''} />
              {importing ? 'Importando…' : 'Importar de Gmail'}
            </button>
          </div>
          {importMsg && (
            <span className="text-[11px] text-[var(--acm-fg-4)]">{importMsg}</span>
          )}
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
  const [newSender, setNewSender] = useState('');

  const addSender = () => {
    const v = newSender.trim().toLowerCase();
    if (!v) return;
    if (form.known_senders.includes(v)) {
      setNewSender('');
      return;
    }
    onChange({ ...form, known_senders: [...form.known_senders, v] });
    setNewSender('');
  };

  const removeSender = (idx: number) => {
    onChange({ ...form, known_senders: form.known_senders.filter((_, i) => i !== idx) });
  };

  const addPattern = () => {
    onChange({ ...form, patterns: [...form.patterns, { type: 'sender_domain', value: '' }] });
  };

  const updatePattern = (idx: number, next: Partial<Pattern>) => {
    onChange({
      ...form,
      patterns: form.patterns.map((p, i) => i === idx ? { ...p, ...next } : p),
    });
  };

  const removePattern = (idx: number) => {
    onChange({ ...form, patterns: form.patterns.filter((_, i) => i !== idx) });
  };

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
          placeholder="Resumen corto para listar"
          rows={2}
          value={form.description}
          onChange={e => onChange({ ...form, description: e.target.value })}
        />
      </div>

      <div>
        <label className="label block mb-1.5">Contexto para la IA</label>
        <textarea
          className="w-full bg-transparent border-b border-[var(--acm-border)] text-[var(--acm-fg)] text-[13px] py-2 resize-none outline-none focus:border-[var(--acm-accent)] transition-colors placeholder:text-[var(--acm-fg-4)]"
          placeholder="Explícale a la IA qué correos deben caer aquí (entidades, temas, criterios, qué NO debe incluir, etc.)"
          rows={5}
          value={form.context}
          onChange={e => onChange({ ...form, context: e.target.value })}
        />
        <p className="text-[10px] text-[var(--acm-fg-4)] mt-1">
          Se incluye en el prompt del clasificador cuando no hay match exacto por remitente o patrón.
        </p>
      </div>

      {/* Known senders */}
      <div>
        <label className="label block mb-1.5">Remitentes conocidos</label>
        <p className="text-[10px] text-[var(--acm-fg-4)] mb-2">
          Emails exactos que SIEMPRE caen en esta categoría (salta el LLM).
        </p>
        <div className="flex flex-wrap gap-1.5 mb-2">
          {form.known_senders.map((s, i) => (
            <span key={i} className="inline-flex items-center gap-1 bg-[var(--acm-card)] border border-[var(--acm-border)] rounded px-2 py-0.5 text-[11px] text-[var(--acm-fg-2)]">
              {s}
              <button
                onClick={() => removeSender(i)}
                className="text-[var(--acm-fg-4)] hover:text-[var(--acm-err)]"
              >
                <X size={11} />
              </button>
            </span>
          ))}
        </div>
        <div className="flex gap-2">
          <input
            className="acm-input text-[12px] flex-1"
            placeholder="ejemplo@dominio.com"
            value={newSender}
            onChange={e => setNewSender(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); addSender(); } }}
          />
          <button onClick={addSender} className="btn-secondary text-[11px] py-1 px-2.5">
            <Plus size={12} /> Agregar
          </button>
        </div>
      </div>

      {/* Patterns */}
      <div>
        <label className="label block mb-1.5">Patrones</label>
        <p className="text-[10px] text-[var(--acm-fg-4)] mb-2">
          Reglas duras: si un correo matchea, salta el LLM y se asigna directo.
        </p>
        <div className="space-y-1.5">
          {form.patterns.map((p, i) => (
            <div key={i} className="flex gap-1.5">
              <select
                className="bg-[var(--acm-card)] border border-[var(--acm-border)] rounded text-[11px] px-2 py-1 text-[var(--acm-fg-2)] outline-none focus:border-[var(--acm-accent)]"
                value={p.type}
                onChange={e => updatePattern(i, { type: e.target.value as PatternType })}
              >
                {(Object.keys(PATTERN_TYPE_LABELS) as PatternType[]).map(t => (
                  <option key={t} value={t}>{PATTERN_TYPE_LABELS[t]}</option>
                ))}
              </select>
              <input
                className="acm-input text-[12px] flex-1"
                placeholder={PATTERN_TYPE_PLACEHOLDERS[p.type]}
                value={p.value}
                onChange={e => updatePattern(i, { value: e.target.value })}
              />
              <button
                onClick={() => removePattern(i)}
                className="p-1.5 text-[var(--acm-fg-4)] hover:text-[var(--acm-err)]"
              >
                <Trash2 size={12} />
              </button>
            </div>
          ))}
        </div>
        <button onClick={addPattern} className="btn-secondary text-[11px] py-1 px-2.5 mt-2">
          <Plus size={12} /> Patrón
        </button>
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
