'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import {
  ChevronLeft, ChevronRight, Download, Expand, FileSpreadsheet, FileText, Loader2, Pause, Play, Presentation, X,
  ZoomIn, ZoomOut, File as FileIcon, Volume2,
} from 'lucide-react';

export type MediaKind = 'image' | 'audio' | 'video' | 'pdf' | 'text' | 'markdown' | 'csv' | 'office' | 'other';

export interface MediaFile {
  /** Name shown to the user (and used to detect the type). */
  name: string;
  /** Id of the stored file when it differs from the name (uploads). */
  fileId?: string;
}

const EXT: Record<MediaKind, string[]> = {
  image: ['png', 'jpg', 'jpeg', 'gif', 'webp', 'svg', 'bmp', 'avif'],
  audio: ['mp3', 'wav', 'ogg', 'oga', 'opus', 'm4a', 'aac', 'flac', 'weba'],
  video: ['mp4', 'm4v', 'webm', 'mov', 'ogv'],
  pdf: ['pdf'],
  markdown: ['md', 'markdown'],
  csv: ['csv', 'tsv'],
  text: ['txt', 'log', 'json', 'yaml', 'yml', 'xml', 'ini', 'toml', 'py', 'js', 'ts', 'tsx', 'jsx', 'css', 'html', 'sql', 'sh'],
  office: ['doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx', 'odt', 'ods', 'odp', 'rtf'],
  other: [],
};

export function mediaKind(name: string): MediaKind {
  const ext = name.split('.').pop()?.toLowerCase() ?? '';
  return (Object.keys(EXT) as MediaKind[]).find((k) => EXT[k].includes(ext)) ?? 'other';
}

/** Kinds the viewer can show on its own (everything else is download-only). */
const VIEWABLE: MediaKind[] = ['image', 'audio', 'video', 'pdf', 'text', 'markdown', 'csv'];
const TEXT_PREVIEW_LIMIT = 400_000;

function urls(f: MediaFile, token: string | null) {
  const id = encodeURIComponent(f.fileId || f.name);
  const t = token ? `token=${encodeURIComponent(token)}` : '';
  return {
    src: `/api/media/${id}${t ? `?${t}` : ''}`,
    download: `/api/media/${id}?download=true${t ? `&${t}` : ''}`,
  };
}

function fmtTime(s: number) {
  if (!isFinite(s)) return '0:00';
  const m = Math.floor(s / 60);
  return `${m}:${String(Math.floor(s % 60)).padStart(2, '0')}`;
}

// ── Audio player ─────────────────────────────────────────────────────────────

const SPEEDS = [1, 1.25, 1.5, 2, 0.75];

function AudioPlayer({ src, name, large }: { src: string; name: string; large?: boolean }) {
  const ref = useRef<HTMLAudioElement>(null);
  const [playing, setPlaying] = useState(false);
  const [time, setTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [speed, setSpeed] = useState(1);
  const [failed, setFailed] = useState(false);

  const toggle = () => {
    const a = ref.current;
    if (!a) return;
    if (a.paused) a.play().catch(() => setFailed(true)); else a.pause();
  };
  const cycleSpeed = () => {
    const next = SPEEDS[(SPEEDS.indexOf(speed) + 1) % SPEEDS.length];
    setSpeed(next);
    if (ref.current) ref.current.playbackRate = next;
  };

  return (
    <div className="flex items-center gap-3 px-3 py-2.5 bg-[var(--acm-card)]" style={{ minWidth: large ? 320 : 240 }}>
      <audio
        ref={ref}
        src={src}
        preload="metadata"
        onPlay={() => setPlaying(true)}
        onPause={() => setPlaying(false)}
        onEnded={() => setPlaying(false)}
        onTimeUpdate={(e) => setTime(e.currentTarget.currentTime)}
        onLoadedMetadata={(e) => setDuration(e.currentTarget.duration)}
        onError={() => setFailed(true)}
      />
      <button
        onClick={toggle}
        aria-label={playing ? 'Pausar' : 'Reproducir'}
        className="w-9 h-9 rounded-full flex items-center justify-center flex-shrink-0 bg-[var(--acm-accent)] text-[var(--acm-base)]"
        disabled={failed}
      >
        {playing ? <Pause size={15} /> : <Play size={15} className="ml-0.5" />}
      </button>
      <div className="flex-1 min-w-0">
        <div className="mono text-[11px] truncate text-[var(--acm-fg-3)] mb-1">{failed ? 'No se pudo reproducir este audio' : name}</div>
        <input
          type="range"
          min={0}
          max={duration || 0}
          step={0.1}
          value={time}
          aria-label="Posición del audio"
          onChange={(e) => { const v = Number(e.target.value); setTime(v); if (ref.current) ref.current.currentTime = v; }}
          className="w-full accent-[var(--acm-accent)]"
          style={{ height: 14 }}
        />
        <div className="flex justify-between mono text-[10px] text-[var(--acm-fg-4)]">
          <span>{fmtTime(time)}</span><span>{fmtTime(duration)}</span>
        </div>
      </div>
      <button onClick={cycleSpeed} aria-label="Velocidad" className="mono text-[11px] px-1.5 py-1 rounded border border-[var(--acm-border)] text-[var(--acm-fg-3)] flex-shrink-0">
        {speed}x
      </button>
    </div>
  );
}

// ── Text-like previews ───────────────────────────────────────────────────────

function TextPreview({ src, kind }: { src: string; kind: MediaKind }) {
  const [text, setText] = useState<string | null>(null);
  const [error, setError] = useState(false);
  useEffect(() => {
    let alive = true;
    fetch(src)
      .then((r) => (r.ok ? r.text() : Promise.reject()))
      .then((t) => { if (alive) setText(t); })
      .catch(() => { if (alive) setError(true); });
    return () => { alive = false; };
  }, [src]);

  if (error) return <div className="p-6 text-[13px] text-[var(--acm-fg-3)]">No se pudo cargar el contenido.</div>;
  if (text === null) return <div className="p-6"><Loader2 className="animate-spin text-[var(--acm-fg-4)]" size={18} /></div>;

  const cut = text.length > TEXT_PREVIEW_LIMIT;
  const body = cut ? text.slice(0, TEXT_PREVIEW_LIMIT) : text;
  return (
    <div className="p-4 text-[13px] text-[var(--acm-fg-2)] overflow-auto" style={{ maxHeight: '100%' }}>
      {kind === 'markdown' ? (
        <div className="prose-sm"><ReactMarkdown remarkPlugins={[remarkGfm]}>{body}</ReactMarkdown></div>
      ) : kind === 'csv' ? (
        <CsvTable text={body} />
      ) : (
        <pre className="mono text-[12px] whitespace-pre-wrap" style={{ overflowWrap: 'anywhere' }}>{body}</pre>
      )}
      {cut && <p className="mt-3 text-[11px] text-[var(--acm-fg-4)]">Vista parcial: descarga el archivo para ver todo.</p>}
    </div>
  );
}

function CsvTable({ text }: { text: string }) {
  const sep = text.split('\n', 1)[0].includes('\t') ? '\t' : ',';
  const rows = text.split(/\r?\n/).filter(Boolean).slice(0, 500).map((l) => l.split(sep));
  return (
    <div className="overflow-x-auto">
      <table className="text-[12px] border-collapse">
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>
              {r.map((c, j) => (
                <td key={j} className={`border border-[var(--acm-border)] px-2 py-1 ${i === 0 ? 'font-semibold bg-[var(--acm-elev)]' : ''}`}>{c}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ── Lightbox ─────────────────────────────────────────────────────────────────

function Lightbox({
  files, index, token, onIndex, onClose,
}: { files: MediaFile[]; index: number; token: string | null; onIndex: (i: number) => void; onClose: () => void }) {
  const f = files[index];
  const kind = mediaKind(f.name);
  const { src, download } = urls(f, token);
  const [zoom, setZoom] = useState(1);
  const dialogRef = useRef<HTMLDivElement>(null);

  useEffect(() => { setZoom(1); }, [index]);

  const go = useCallback((d: number) => onIndex((index + d + files.length) % files.length), [index, files.length, onIndex]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
      else if (e.key === 'ArrowRight' && files.length > 1) go(1);
      else if (e.key === 'ArrowLeft' && files.length > 1) go(-1);
      else if (kind === 'image' && (e.key === '+' || e.key === '=')) setZoom((z) => Math.min(5, z + 0.5));
      else if (kind === 'image' && e.key === '-') setZoom((z) => Math.max(1, z - 0.5));
    };
    window.addEventListener('keydown', onKey);
    const prev = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    dialogRef.current?.focus();
    return () => { window.removeEventListener('keydown', onKey); document.body.style.overflow = prev; };
  }, [go, onClose, files.length, kind]);

  const iconBtn = 'w-9 h-9 flex items-center justify-center rounded-full bg-white/10 hover:bg-white/20 text-white transition-colors';

  return (
    <div
      ref={dialogRef}
      role="dialog"
      aria-modal="true"
      aria-label={f.name}
      tabIndex={-1}
      className="fixed inset-0 z-[100] flex flex-col bg-black/90 outline-none"
      onClick={onClose}
    >
      <div className="flex items-center gap-2 px-3 py-2 text-white" onClick={(e) => e.stopPropagation()}>
        <span className="mono text-[12px] truncate flex-1">{f.name}{files.length > 1 ? `  (${index + 1}/${files.length})` : ''}</span>
        {kind === 'image' && (
          <>
            <button className={iconBtn} aria-label="Alejar" onClick={() => setZoom((z) => Math.max(1, z - 0.5))}><ZoomOut size={16} /></button>
            <button className={iconBtn} aria-label="Acercar" onClick={() => setZoom((z) => Math.min(5, z + 0.5))}><ZoomIn size={16} /></button>
          </>
        )}
        <a className={iconBtn} href={download} download={f.name} aria-label="Descargar"><Download size={16} /></a>
        <button className={iconBtn} aria-label="Cerrar" onClick={onClose}><X size={18} /></button>
      </div>

      <div className="relative flex-1 min-h-0 flex items-center justify-center" onClick={(e) => e.stopPropagation()}>
        {files.length > 1 && (
          <>
            <button className={`${iconBtn} absolute left-2 z-10`} aria-label="Anterior" onClick={() => go(-1)}><ChevronLeft size={20} /></button>
            <button className={`${iconBtn} absolute right-2 z-10`} aria-label="Siguiente" onClick={() => go(1)}><ChevronRight size={20} /></button>
          </>
        )}

        {kind === 'image' && (
          <div className="w-full h-full overflow-auto flex" onClick={onClose}>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={src}
              alt={f.name}
              onClick={(e) => { e.stopPropagation(); setZoom((z) => (z > 1 ? 1 : 2)); }}
              draggable={false}
              style={{
                margin: 'auto', cursor: zoom > 1 ? 'zoom-out' : 'zoom-in',
                maxWidth: zoom === 1 ? '100%' : 'none', maxHeight: zoom === 1 ? '100%' : 'none',
                width: zoom === 1 ? undefined : `${zoom * 100}%`, objectFit: 'contain',
              }}
            />
          </div>
        )}
        {kind === 'video' && (
          <video src={src} controls autoPlay playsInline className="max-w-full max-h-full bg-black" />
        )}
        {kind === 'audio' && (
          <div className="rounded-[10px] overflow-hidden border border-[var(--acm-border)]"><AudioPlayer src={src} name={f.name} large /></div>
        )}
        {kind === 'pdf' && (
          <iframe src={src} title={f.name} className="w-full h-full bg-white border-0 max-w-[1100px]" />
        )}
        {(kind === 'text' || kind === 'markdown' || kind === 'csv') && (
          <div className="w-full max-w-[1000px] h-full bg-[var(--acm-base)] rounded-[8px] overflow-hidden">
            <TextPreview src={src} kind={kind} />
          </div>
        )}
      </div>
    </div>
  );
}

// ── Inline items ─────────────────────────────────────────────────────────────

const DOC_ICON: Partial<Record<MediaKind, typeof FileText>> = {
  pdf: FileText, text: FileText, markdown: FileText, csv: FileSpreadsheet, office: FileText,
};

function officeIcon(name: string) {
  const ext = name.split('.').pop()?.toLowerCase() ?? '';
  if (['xls', 'xlsx', 'ods'].includes(ext)) return FileSpreadsheet;
  if (['ppt', 'pptx', 'odp'].includes(ext)) return Presentation;
  return FileText;
}

function Item({ file, token, onOpen }: { file: MediaFile; token: string | null; onOpen: () => void }) {
  const kind = mediaKind(file.name);
  const { src, download } = urls(file, token);
  const Icon = kind === 'office' ? officeIcon(file.name) : (DOC_ICON[kind] ?? FileIcon);
  const viewable = VIEWABLE.includes(kind);

  return (
    <div className="rounded-[6px] overflow-hidden border border-[var(--acm-border)] bg-[var(--acm-elev)] max-w-full">
      {kind === 'image' && (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={src}
          alt={file.name}
          loading="lazy"
          onClick={onOpen}
          className="max-w-full sm:max-w-xs max-h-64 object-contain bg-[var(--acm-base)] block cursor-zoom-in"
        />
      )}
      {kind === 'video' && (
        <div className="relative bg-black">
          <video src={src} controls preload="metadata" playsInline className="block max-w-full sm:max-w-md max-h-72" />
          <button
            onClick={onOpen}
            aria-label="Pantalla grande"
            className="absolute top-2 right-2 w-8 h-8 flex items-center justify-center rounded-full bg-black/60 text-white"
          >
            <Expand size={14} />
          </button>
        </div>
      )}
      {kind === 'audio' && <AudioPlayer src={src} name={file.name} />}

      <div className="flex items-center gap-2 px-3 py-2 text-[11px]">
        {kind === 'audio' ? <Volume2 size={12} className="text-[var(--acm-fg-4)] flex-shrink-0" /> : <Icon size={13} className="text-[var(--acm-fg-4)] flex-shrink-0" />}
        <span className="mono truncate text-[var(--acm-fg-3)] flex-1">{file.name}</span>
        {viewable && !['image', 'video', 'audio'].includes(kind) && (
          <button onClick={onOpen} className="btn-secondary !py-[4px] !px-[8px] !text-[11px] flex-shrink-0">Ver</button>
        )}
        <a href={download} download={file.name} className="btn-primary !py-[4px] !px-[8px] !text-[11px] flex-shrink-0">
          <Download size={10} />
          Descargar
        </a>
      </div>
    </div>
  );
}

/** Every file of a message: shown inline by type, with a full-screen viewer to enlarge, play or read it. */
export function MediaGallery({ files, token, className }: { files: MediaFile[]; token: string | null; className?: string }) {
  const [open, setOpen] = useState<number | null>(null);
  const viewable = files.map((f, i) => ({ f, i })).filter(({ f }) => VIEWABLE.includes(mediaKind(f.name)));
  const list = viewable.map(({ f }) => f);
  const toViewer = (fileIndex: number) => {
    const at = viewable.findIndex(({ i }) => i === fileIndex);
    if (at >= 0) setOpen(at);
  };
  const close = useCallback(() => setOpen(null), []);
  if (files.length === 0) return null;

  return (
    <div className={className ?? 'space-y-2'}>
      {files.map((f, i) => (
        <Item key={`${f.fileId ?? f.name}-${i}`} file={f} token={token} onOpen={() => toViewer(i)} />
      ))}
      {open !== null && list[open] && (
        <Lightbox files={list} index={open} token={token} onIndex={setOpen} onClose={close} />
      )}
    </div>
  );
}
