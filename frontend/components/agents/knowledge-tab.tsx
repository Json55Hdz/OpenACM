'use client';

import { useState } from 'react';
import { useAgentKnowledge, useAgentKnowledgeMutations, useKnowledgeFiles, type KnowledgeItem } from '@/hooks/use-agents';
import { useAPI } from '@/hooks/use-api';
import { Plus, Trash2, Loader2, X, FileText, Upload, BookOpen, Pencil, AlertTriangle } from 'lucide-react';
import { toast } from 'sonner';
import { cn } from './shared';

function KnowledgeFilesSection() {
  const { data: collections = [] } = useKnowledgeFiles();
  const { fetchAPI } = useAPI();
  const [open, setOpen] = useState(false);
  const [filter, setFilter] = useState('');
  const [editing, setEditing] = useState<{ collection: string; name: string } | null>(null);
  const [content, setContent] = useState('');
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);

  const total = collections.reduce((n, c) => n + c.files.length, 0);
  if (total === 0) return null;

  const openFile = async (collection: string, name: string) => {
    setEditing({ collection, name });
    setContent('');
    setLoading(true);
    try {
      const d = await fetchAPI(`/api/knowledge-files/${collection}/${name}`);
      setContent(d.content ?? '');
    } catch {
      toast.error('No se pudo cargar el archivo');
      setEditing(null);
    } finally {
      setLoading(false);
    }
  };

  const save = async () => {
    if (!editing) return;
    setSaving(true);
    try {
      await fetchAPI(`/api/knowledge-files/${editing.collection}/${editing.name}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content }),
      });
      toast.success('Archivo guardado');
      setEditing(null);
    } catch (err: any) {
      toast.error(err.message || 'Error al guardar');
    } finally {
      setSaving(false);
    }
  };

  const q = filter.trim().toLowerCase();

  return (
    <div className="border border-zinc-700 rounded-lg bg-zinc-900/30">
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center justify-between px-3 py-2 text-sm text-zinc-200"
      >
        <span className="flex items-center gap-2">
          <FileText className="w-4 h-4 text-blue-400" />
          Archivos de la base de búsqueda ({total})
        </span>
        <span className="text-xs text-zinc-500">{open ? 'Ocultar' : 'Ver'}</span>
      </button>
      {open && (
        <div className="px-3 pb-3 space-y-2">
          <p className="text-xs text-zinc-500">
            Documentos que el agente consulta con sus herramientas de búsqueda (no van completos en el prompt).
            Los cambios se aplican al instante.
          </p>
          {editing ? (
            <div className="space-y-2">
              <p className="text-sm text-zinc-100 font-mono">{editing.collection}/{editing.name}</p>
              {loading ? (
                <div className="flex items-center text-zinc-500 text-sm"><Loader2 className="w-4 h-4 animate-spin mr-2" />Cargando…</div>
              ) : (
                <textarea
                  value={content}
                  onChange={(e) => setContent(e.target.value)}
                  rows={20}
                  className="w-full bg-zinc-800 border border-zinc-700 rounded px-3 py-2 text-xs font-mono text-zinc-100 focus:outline-none focus:border-zinc-500"
                />
              )}
              <div className="flex gap-2">
                <button
                  onClick={save}
                  disabled={saving || loading}
                  className="px-3 py-1 text-xs bg-blue-600 hover:bg-blue-700 disabled:opacity-50 rounded text-white transition-colors"
                >
                  {saving ? 'Guardando…' : 'Guardar'}
                </button>
                <button onClick={() => setEditing(null)} className="px-3 py-1 text-xs text-zinc-400 hover:text-zinc-200">
                  Cancelar
                </button>
              </div>
            </div>
          ) : (
            <>
              <input
                value={filter}
                onChange={(e) => setFilter(e.target.value)}
                placeholder="Filtrar archivos…"
                className="w-full bg-zinc-800 border border-zinc-700 rounded px-3 py-1.5 text-sm text-zinc-100 placeholder-zinc-500 focus:outline-none focus:border-zinc-500"
              />
              <div className="max-h-80 overflow-y-auto space-y-1">
                {collections.map((c) =>
                  c.files
                    .filter((f) => !q || f.name.toLowerCase().includes(q) || f.title.toLowerCase().includes(q))
                    .map((f) => (
                      <div key={`${c.collection}/${f.name}`} className="flex items-center justify-between gap-2 text-sm py-1 border-b border-zinc-800">
                        <div className="min-w-0">
                          <p className="text-zinc-100 truncate">{f.title}</p>
                          <p className="text-xs text-zinc-500 font-mono truncate">{c.collection}/{f.name} · {(f.size / 1024).toFixed(0)} KB</p>
                        </div>
                        <button
                          onClick={() => openFile(c.collection, f.name)}
                          className="p-1 text-zinc-500 hover:text-zinc-300 transition-colors flex-shrink-0"
                          title="Ver / editar"
                        >
                          <Pencil className="w-3.5 h-3.5" />
                        </button>
                      </div>
                    ))
                )}
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}

// ── Knowledge Tab ─────────────────────────────────────────────────────────────

export function KnowledgeTab({ agentId }: { agentId: number }) {
  const { data: items = [], isLoading } = useAgentKnowledge(agentId);
  const { addText, addFile, updateItem, removeItem } = useAgentKnowledgeMutations(agentId);
  const { fetchAPI } = useAPI();

  const [showTextForm, setShowTextForm] = useState(false);
  const [textTitle, setTextTitle] = useState('');
  const [textContent, setTextContent] = useState('');
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editTitle, setEditTitle] = useState('');
  const [editContent, setEditContent] = useState('');
  const [deletingId, setDeletingId] = useState<number | null>(null);

  const totalChars = items.reduce((sum, i) => sum + (i.char_count ?? 0), 0);

  const handleAddText = async () => {
    if (!textTitle.trim() || !textContent.trim()) return;
    try {
      await addText.mutateAsync({ title: textTitle.trim(), content: textContent.trim() });
      setTextTitle('');
      setTextContent('');
      setShowTextForm(false);
      toast.success('Sección de texto agregada');
    } catch (err: any) {
      toast.error(err.message || 'Error al agregar la sección');
    }
  };

  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    try {
      await addFile.mutateAsync({ file });
      toast.success(`Archivo "${file.name}" procesado`);
    } catch (err: any) {
      toast.error(err.message || 'Error al procesar el archivo');
    }
    e.target.value = '';
  };

  const startEdit = async (item: KnowledgeItem) => {
    setEditingId(item.id);
    setEditTitle(item.title);
    setEditContent('');
    try {
      const full = await fetchAPI(`/api/agents/${agentId}/knowledge/${item.id}`);
      setEditContent(full.content ?? '');
    } catch {
      toast.error('No se pudo cargar el contenido');
    }
  };

  const handleUpdate = async (item: KnowledgeItem) => {
    const updates: { title?: string; content?: string } = {};
    if (editTitle.trim() && editTitle !== item.title) updates.title = editTitle.trim();
    if (editContent.trim()) updates.content = editContent.trim();
    if (Object.keys(updates).length === 0) { setEditingId(null); return; }
    await updateItem.mutateAsync({ kid: item.id, ...updates });
    setEditingId(null);
    toast.success('Item actualizado');
  };

  const handleDelete = async (kid: number) => {
    try {
      setDeletingId(kid);
      await removeItem.mutateAsync(kid);
      toast.success('Item eliminado');
    } catch (err: any) {
      toast.error(err.message || 'Error al eliminar el item');
    } finally {
      setDeletingId(null);
    }
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12 text-zinc-500">
        <Loader2 className="w-5 h-5 animate-spin mr-2" />
        Cargando conocimiento…
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Actions */}
      <div className="flex gap-2">
        <button
          onClick={() => setShowTextForm((v) => !v)}
          className="flex items-center gap-1.5 px-3 py-1.5 text-sm rounded-lg border border-zinc-700 text-zinc-300 hover:bg-zinc-800 transition-colors"
        >
          <Plus className="w-3.5 h-3.5" />
          Agregar texto
        </button>
        <label className="flex items-center gap-1.5 px-3 py-1.5 text-sm rounded-lg border border-zinc-700 text-zinc-300 hover:bg-zinc-800 transition-colors cursor-pointer">
          <Upload className="w-3.5 h-3.5" />
          {addFile.isPending ? 'Procesando…' : 'Subir archivo'}
          <input
            type="file"
            className="hidden"
            accept=".pdf,.docx,.xlsx,.pptx,.txt,.md,.csv,.json,.yaml,.yml"
            onChange={handleFileChange}
            disabled={addFile.isPending}
          />
        </label>
      </div>

      {/* Inline text form */}
      {showTextForm && (
        <div className="border border-zinc-700 rounded-lg p-3 space-y-2 bg-zinc-900/50">
          <input
            value={textTitle}
            onChange={(e) => setTextTitle(e.target.value)}
            placeholder="Título (ej: Política de devoluciones)"
            className="w-full bg-zinc-800 border border-zinc-700 rounded px-3 py-1.5 text-sm text-zinc-100 placeholder-zinc-500 focus:outline-none focus:border-zinc-500"
          />
          <textarea
            value={textContent}
            onChange={(e) => setTextContent(e.target.value)}
            placeholder="Contenido…"
            rows={4}
            className="w-full bg-zinc-800 border border-zinc-700 rounded px-3 py-1.5 text-sm text-zinc-100 placeholder-zinc-500 focus:outline-none focus:border-zinc-500 resize-none"
          />
          <div className="flex gap-2">
            <button
              onClick={handleAddText}
              disabled={addText.isPending || !textTitle.trim() || !textContent.trim()}
              className="px-3 py-1.5 text-sm bg-blue-600 hover:bg-blue-700 disabled:opacity-50 rounded-lg text-white transition-colors"
            >
              {addText.isPending ? 'Guardando…' : 'Guardar'}
            </button>
            <button
              onClick={() => { setShowTextForm(false); setTextTitle(''); setTextContent(''); }}
              className="px-3 py-1.5 text-sm text-zinc-400 hover:text-zinc-200 transition-colors"
            >
              Cancelar
            </button>
          </div>
        </div>
      )}

      {/* Items list */}
      {items.length === 0 && !showTextForm && (
        <div className="text-center py-8 text-zinc-500 text-sm">
          <BookOpen className="w-8 h-8 mx-auto mb-2 opacity-40" />
          Agrega documentos o secciones de texto para que tu agente tenga contexto al responder.
        </div>
      )}

      {items.map((item) => (
        <div key={item.id} className="border border-zinc-700 rounded-lg p-3 bg-zinc-900/30">
          {editingId === item.id ? (
            <div className="space-y-2">
              <input
                value={editTitle}
                onChange={(e) => setEditTitle(e.target.value)}
                className="w-full bg-zinc-800 border border-zinc-700 rounded px-3 py-1.5 text-sm text-zinc-100 focus:outline-none focus:border-zinc-500"
              />
              <textarea
                value={editContent}
                onChange={(e) => setEditContent(e.target.value)}
                placeholder="Contenido"
                rows={12}
                className="w-full bg-zinc-800 border border-zinc-700 rounded px-3 py-1.5 text-sm text-zinc-100 placeholder-zinc-500 focus:outline-none focus:border-zinc-500"
              />
              <div className="flex gap-2">
                <button
                  onClick={() => handleUpdate(item)}
                  disabled={updateItem.isPending}
                  className="px-3 py-1 text-xs bg-blue-600 hover:bg-blue-700 disabled:opacity-50 rounded text-white transition-colors"
                >
                  {updateItem.isPending ? 'Guardando…' : 'Guardar'}
                </button>
                <button
                  onClick={() => setEditingId(null)}
                  className="px-3 py-1 text-xs text-zinc-400 hover:text-zinc-200 transition-colors"
                >
                  Cancelar
                </button>
              </div>
            </div>
          ) : (
            <div className="flex items-start justify-between gap-2">
              <div className="flex items-start gap-2 min-w-0">
                {item.type === 'file' ? (
                  <FileText className="w-4 h-4 text-blue-400 mt-0.5 flex-shrink-0" />
                ) : (
                  <BookOpen className="w-4 h-4 text-purple-400 mt-0.5 flex-shrink-0" />
                )}
                <div className="min-w-0">
                  <p className="text-sm text-zinc-100 truncate">{item.title}</p>
                  <p className="text-xs text-zinc-500 mt-0.5">
                    {item.type === 'file' ? item.filename : 'Texto'}
                    {' · '}
                    {new Date(item.created_at).toLocaleDateString()}
                  </p>
                </div>
              </div>
              <div className="flex items-center gap-1 flex-shrink-0">
                <span className={cn(
                  'text-xs px-1.5 py-0.5 rounded font-mono',
                  item.type === 'file'
                    ? 'bg-blue-900/40 text-blue-300'
                    : 'bg-purple-900/40 text-purple-300'
                )}>
                  {item.type === 'file' ? 'FILE' : 'TEXT'}
                </span>
                <button
                  onClick={() => startEdit(item)}
                  className="p-1 text-zinc-500 hover:text-zinc-300 transition-colors"
                  title="Editar"
                >
                  <Pencil className="w-3.5 h-3.5" />
                </button>
                <button
                  onClick={() => handleDelete(item.id)}
                  disabled={deletingId === item.id}
                  className="p-1 text-zinc-500 hover:text-red-400 transition-colors"
                  title="Eliminar"
                >
                  <Trash2 className="w-3.5 h-3.5" />
                </button>
              </div>
            </div>
          )}
        </div>
      ))}

      <KnowledgeFilesSection />

      {/* Char counter footer */}
      {items.length > 0 && (
        <p className={cn(
          'text-xs text-right',
          totalChars >= 40_000 ? 'text-red-400' : totalChars >= 30_000 ? 'text-yellow-400' : 'text-zinc-600'
        )}>
          {totalChars >= 40_000 && <AlertTriangle className="w-3 h-3 inline mr-1" />}
          {totalChars.toLocaleString()} caracteres
          {totalChars >= 40_000 && ' — se truncará al enviar'}
          {totalChars >= 30_000 && totalChars < 40_000 && ' — cerca del límite (40k)'}
          {' · '}
          {items.length} {items.length === 1 ? 'item' : 'items'}
        </p>
      )}
    </div>
  );
}
