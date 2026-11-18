'use client';

import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { useAgentKnowledge, useAgentKnowledgeMutations, useAgents, useKnowledgeFiles, type KnowledgeItem } from '@/hooks/use-agents';
import { useAPI } from '@/hooks/use-api';
import { Plus, Trash2, Loader2, X, FileText, Upload, BookOpen, Pencil, AlertTriangle } from 'lucide-react';
import { toast } from 'sonner';
import { cn } from './shared';

function KnowledgeFilesSection({ agentId }: { agentId: number }) {
  const { data: allCollections = [] } = useKnowledgeFiles();
  const { data: agents = [] } = useAgents();
  const { fetchAPI } = useAPI();
  // Each agent only has (and can search) the collections assigned to it
  const mine = agents.find((a) => a.id === agentId)?.knowledge_collections ?? [];
  const taken = new Set(agents.flatMap((a) => a.knowledge_collections ?? []));
  const collections = allCollections.filter((c) => mine.includes(c.collection));
  const unassigned = allCollections.filter((c) => !taken.has(c.collection));
  const [adopt, setAdopt] = useState('');
  const [open, setOpen] = useState(false);
  const [filter, setFilter] = useState('');
  const [editing, setEditing] = useState<{ collection: string; name: string } | null>(null);
  const [content, setContent] = useState('');
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [target, setTarget] = useState('');
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);
  const [newCollection, setNewCollection] = useState('');
  const [creating, setCreating] = useState(false);
  const qc = useQueryClient();

  const total = collections.reduce((n, c) => n + c.files.length, 0);
  const targetCollection = target || collections[0]?.collection || '';

  const setMine = async (next: string[]) => {
    await fetchAPI(`/api/agents/${agentId}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ knowledge_collections: next }),
    });
    qc.invalidateQueries({ queryKey: ['agents'] });
  };

  const attach = async () => {
    if (!adopt) return;
    try {
      await setMine([...mine, adopt]);
      toast.success(`«${adopt}» ahora es de este agente`);
      setTarget(adopt);
      setAdopt('');
    } catch (err: any) {
      toast.error(err.message || 'No se pudo asignar');
    }
  };

  const detach = async (name: string) => {
    try {
      await setMine(mine.filter((m) => m !== name));
      toast.success(`El agente ya no consulta «${name}» (sus archivos siguen guardados)`);
    } catch (err: any) {
      toast.error(err.message || 'No se pudo quitar');
    }
  };

  const createCollection = async () => {
    const name = newCollection.trim();
    if (!name) return;
    setCreating(true);
    try {
      const res = await fetchAPI('/api/knowledge-collections', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name }),
      });
      await setMine([...mine, res.collection]);
      toast.success(`Colección «${res.collection}» creada para este agente`);
      setNewCollection('');
      setTarget(res.collection);
      qc.invalidateQueries({ queryKey: ['knowledge-files'] });
    } catch (err: any) {
      toast.error(err.message || 'No se pudo crear la colección');
    } finally {
      setCreating(false);
    }
  };

  const upload = async (files: FileList | null) => {
    if (!files || files.length === 0) return;
    setUploading(true);
    let ok = 0;
    for (const f of Array.from(files)) {
      try {
        const body = new FormData();
        body.append('file', f);
        await fetchAPI(`/api/knowledge-files/${targetCollection}`, { method: 'POST', body });
        ok += 1;
      } catch (err: any) {
        toast.error(`${f.name}: ${err.message || 'no se pudo subir'}`);
      }
    }
    setUploading(false);
    if (ok) toast.success(ok === 1 ? 'Archivo agregado' : `${ok} archivos agregados`);
    qc.invalidateQueries({ queryKey: ['knowledge-files'] });
  };

  const remove = async (collection: string, name: string) => {
    try {
      await fetchAPI(`/api/knowledge-files/${collection}/${name}`, { method: 'DELETE' });
      toast.success('Archivo borrado');
      qc.invalidateQueries({ queryKey: ['knowledge-files'] });
    } catch (err: any) {
      toast.error(err.message || 'No se pudo borrar');
    } finally {
      setConfirmDelete(null);
    }
  };

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
          Archivos de búsqueda de este agente ({total} en {collections.length} {collections.length === 1 ? 'colección' : 'colecciones'})
        </span>
        <span className="text-xs text-zinc-500">{open ? 'Ocultar' : 'Ver'}</span>
      </button>
      {open && (
        <div className="px-3 pb-3 space-y-2">
          <p className="text-xs text-zinc-500">
            Documentos que ESTE agente consulta con su herramienta <span className="font-mono">search_knowledge</span> (no van
            completos en el prompt). Cada colección pertenece a un solo agente y ningún otro puede leerla. Los cambios se aplican al instante.
          </p>
          <div className="flex items-center gap-1.5 flex-wrap">
            {mine.length === 0 && <span className="text-xs text-zinc-500">Este agente aún no tiene colecciones: crea una o asígnale una libre.</span>}
            {mine.map((m) => (
              <span key={m} className="inline-flex items-center gap-1 text-xs bg-zinc-800 border border-zinc-700 rounded px-2 py-0.5 text-zinc-200">
                <span className="font-mono">{m}</span>
                <button onClick={() => detach(m)} className="text-zinc-500 hover:text-red-400" title="Quitar del agente (no borra los archivos)">
                  <X className="w-3 h-3" />
                </button>
              </span>
            ))}
          </div>
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
              <div className="flex items-center gap-2 flex-wrap">
                <input
                  value={newCollection}
                  onChange={(e) => setNewCollection(e.target.value)}
                  onKeyDown={(e) => { if (e.key === 'Enter') createCollection(); }}
                  placeholder="Nueva colección (ej. ventas)"
                  className="bg-zinc-800 border border-zinc-700 rounded px-2 py-1 text-xs text-zinc-100 placeholder-zinc-500 w-48"
                />
                <button
                  onClick={createCollection}
                  disabled={creating || !newCollection.trim()}
                  className="px-3 py-1 text-xs bg-zinc-700 hover:bg-zinc-600 disabled:opacity-50 rounded text-zinc-100 transition-colors"
                >
                  Crear colección
                </button>
                {unassigned.length > 0 && (
                  <>
                    <select
                      value={adopt}
                      onChange={(e) => setAdopt(e.target.value)}
                      className="bg-zinc-800 border border-zinc-700 rounded px-2 py-1 text-xs text-zinc-100"
                    >
                      <option value="">Asignar una colección libre…</option>
                      {unassigned.map((c) => <option key={c.collection} value={c.collection}>{c.collection} ({c.files.length})</option>)}
                    </select>
                    <button
                      onClick={attach}
                      disabled={!adopt}
                      className="px-3 py-1 text-xs bg-zinc-700 hover:bg-zinc-600 disabled:opacity-50 rounded text-zinc-100 transition-colors"
                    >
                      Asignar
                    </button>
                  </>
                )}
              </div>
              <div className="flex items-center gap-2 flex-wrap">
                {collections.length > 1 && (
                  <select
                    value={targetCollection}
                    onChange={(e) => setTarget(e.target.value)}
                    className="bg-zinc-800 border border-zinc-700 rounded px-2 py-1 text-xs text-zinc-100"
                  >
                    {collections.map((c) => <option key={c.collection} value={c.collection}>{c.collection}</option>)}
                  </select>
                )}
                {targetCollection && (
                <label className="px-3 py-1 text-xs bg-blue-600 hover:bg-blue-700 rounded text-white cursor-pointer transition-colors flex items-center gap-1">
                  {uploading ? <Loader2 className="w-3 h-3 animate-spin" /> : <Upload className="w-3 h-3" />}
                  {uploading ? 'Subiendo…' : `Agregar archivos a ${targetCollection}`}
                  <input
                    type="file"
                    multiple
                    disabled={uploading}
                    className="hidden"
                    accept=".pdf,.docx,.xlsx,.pptx,.md,.txt,.csv,.json,.html,.htm,.xml,.yaml,.yml"
                    onChange={(e) => { upload(e.target.files); e.target.value = ''; }}
                  />
                </label>
                )}
                <span className="text-xs text-zinc-500">PDF, Word, Excel, texto… hasta 20 MB; se convierten a Markdown.</span>
              </div>
              <input
                value={filter}
                onChange={(e) => setFilter(e.target.value)}
                placeholder="Filtrar archivos…"
                className="w-full bg-zinc-800 border border-zinc-700 rounded px-3 py-1.5 text-sm text-zinc-100 placeholder-zinc-500 focus:outline-none focus:border-zinc-500"
              />
              <div className="max-h-80 overflow-y-auto space-y-1">
                {collections.filter((c) => c.files.length === 0).map((c) => (
                  <p key={`empty-${c.collection}`} className="text-xs text-zinc-500 py-1 border-b border-zinc-800">
                    <span className="font-mono text-zinc-300">{c.collection}</span> · vacía: agrégale archivos con el botón azul
                  </p>
                ))}
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
                        {confirmDelete === `${c.collection}/${f.name}` ? (
                          <button
                            onClick={() => remove(c.collection, f.name)}
                            className="px-2 py-0.5 text-xs bg-red-600 hover:bg-red-700 rounded text-white flex-shrink-0"
                          >
                            ¿Borrar?
                          </button>
                        ) : (
                          <button
                            onClick={() => setConfirmDelete(`${c.collection}/${f.name}`)}
                            className="p-1 text-zinc-500 hover:text-red-400 transition-colors flex-shrink-0"
                            title="Borrar"
                          >
                            <Trash2 className="w-3.5 h-3.5" />
                          </button>
                        )}
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

      <KnowledgeFilesSection agentId={agentId} />

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
