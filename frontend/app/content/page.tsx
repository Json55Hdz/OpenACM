'use client';

import { useState, useEffect, useCallback } from 'react';
import {
  Sparkles,
  CheckCircle,
  XCircle,
  Trash2,
  RefreshCw,
  Image as ImageIcon,
  FileText,
  Video,
  Share2,
  MessageSquare,
  Settings,
  ChevronDown,
  ChevronUp,
  AlertCircle,
  X,
} from 'lucide-react';
import { useAuthStore } from '@/stores/auth-store';
import { AppLayout } from '@/components/layout/app-layout';

// ── Types ──────────────────────────────────────────────────────────────────

interface ContentItem {
  id: number;
  platform: 'facebook' | 'reddit';
  content_type: 'post' | 'meme' | 'video';
  title: string;
  body: string;
  media_paths: string;
  metadata: string;
  status: 'pending' | 'approved' | 'rejected' | 'published' | 'failed';
  swarm_id: number | null;
  created_at: string;
  approved_at: string | null;
  rejected_at: string | null;
  published_at: string | null;
  publish_error: string | null;
}

interface SocialCredential {
  id: number;
  platform: string;
  is_active: number;
  verified_at: string | null;
  created_at: string;
}

// ── Helpers ────────────────────────────────────────────────────────────────

const PLATFORM_ICONS: Record<string, React.ReactNode> = {
  facebook: <Share2 size={12} />,
  reddit:   <MessageSquare size={12} />,
};

const CONTENT_TYPE_ICONS: Record<string, React.ReactNode> = {
  post:  <FileText size={12} />,
  meme:  <ImageIcon size={12} />,
  video: <Video size={12} />,
};

// Status dot class + mono label color
const STATUS_DOT: Record<string, { dot: string; color: string }> = {
  pending:   { dot: 'dot dot-warn acm-pulse', color: 'var(--acm-warn)' },
  approved:  { dot: 'dot dot-ok',             color: 'var(--acm-ok)' },
  rejected:  { dot: 'dot dot-err',            color: 'var(--acm-err)' },
  published: { dot: 'dot dot-ok',             color: 'var(--acm-ok)' },
  failed:    { dot: 'dot dot-err',            color: 'var(--acm-err)' },
};

function formatDate(iso: string | null) {
  if (!iso) return '—';
  return new Date(iso).toLocaleString();
}

// ── Credential Modal ───────────────────────────────────────────────────────

function CredentialModal({
  platform,
  onClose,
  onSaved,
  authHeader,
}: {
  platform: 'facebook' | 'reddit';
  onClose: () => void;
  onSaved: () => void;
  authHeader: Record<string, string>;
}) {
  const [fields, setFields] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  const facebookFields = [
    { key: 'page_id',           label: 'Page ID',           placeholder: 'e.g. 123456789' },
    { key: 'page_access_token', label: 'Page Access Token', placeholder: 'EAAxxxxx...' },
  ];
  const redditFields = [
    { key: 'client_id',     label: 'Client ID',       placeholder: 'From reddit.com/prefs/apps' },
    { key: 'client_secret', label: 'Client Secret',   placeholder: '' },
    { key: 'username',      label: 'Reddit Username', placeholder: 'u/yourname' },
    { key: 'password',      label: 'Password',        placeholder: '' },
    { key: 'user_agent',    label: 'User Agent',      placeholder: 'OpenACM/1.0 by u/yourname' },
  ];
  const fieldDefs = platform === 'facebook' ? facebookFields : redditFields;

  const handleSave = async () => {
    setSaving(true);
    setError('');
    try {
      const res = await fetch('/api/social/credentials', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeader },
        body: JSON.stringify({ platform, credentials: fields }),
      });
      if (!res.ok) throw new Error(await res.text());
      onSaved();
      onClose();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/60 z-50 flex items-center justify-center p-4">
      <div
        className="w-full max-w-md rounded-xl overflow-hidden shadow-2xl"
        style={{ background: 'var(--acm-base)', border: '1px solid var(--acm-border)' }}
      >
        {/* Modal header */}
        <div
          className="flex items-center justify-between px-6 py-5"
          style={{ borderBottom: '1px solid var(--acm-border)' }}
        >
          <h2 className="text-base font-bold capitalize" style={{ color: 'var(--acm-fg)' }}>
            {platform} Credentials
          </h2>
          <button
            onClick={onClose}
            style={{ color: 'var(--acm-fg-4)' }}
            onMouseEnter={e => (e.currentTarget.style.color = 'var(--acm-fg)')}
            onMouseLeave={e => (e.currentTarget.style.color = 'var(--acm-fg-4)')}
          >
            <X size={18} />
          </button>
        </div>

        <div className="px-6 py-5 space-y-4">
          {fieldDefs.map((f) => (
            <div key={f.key}>
              <label className="label block mb-2">{f.label}</label>
              <input
                type={
                  f.key.toLowerCase().includes('password') ||
                  f.key.includes('secret') ||
                  f.key.includes('token')
                    ? 'password'
                    : 'text'
                }
                className="acm-input"
                placeholder={f.placeholder}
                value={fields[f.key] || ''}
                onChange={(e) => setFields((p) => ({ ...p, [f.key]: e.target.value }))}
              />
            </div>
          ))}

          {error && (
            <p className="text-[12px]" style={{ color: 'var(--acm-err)' }}>
              {error}
            </p>
          )}

          <div className="flex gap-2 pt-1">
            <button onClick={onClose} className="btn-secondary flex-1">
              Cancel
            </button>
            <button
              onClick={handleSave}
              disabled={saving}
              className="btn-primary flex-1 justify-center"
            >
              {saving ? 'Saving...' : 'Save'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

// ── Content Card ───────────────────────────────────────────────────────────

function ContentCard({
  item,
  onApprove,
  onReject,
  onDelete,
}: {
  item: ContentItem;
  onApprove: (id: number) => void;
  onReject: (id: number) => void;
  onDelete: (id: number) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  let mediaPaths: string[] = [];
  try { mediaPaths = JSON.parse(item.media_paths || '[]'); } catch { /* */ }
  let meta: Record<string, any> = {};
  try { meta = JSON.parse(item.metadata || '{}'); } catch { /* */ }

  const { dot, color } = STATUS_DOT[item.status] ?? { dot: 'dot dot-idle', color: 'var(--acm-fg-4)' };

  return (
    <div className="acm-card p-4 space-y-3">
      {/* Header */}
      <div className="flex items-start gap-3">
        {/* Thumbnail placeholder */}
        <div
          className="w-14 h-14 rounded-lg shrink-0 flex items-center justify-center"
          style={{ background: 'var(--acm-elev)' }}
        >
          {CONTENT_TYPE_ICONS[item.content_type] && (
            <span style={{ color: 'var(--acm-fg-4)' }}>
              {CONTENT_TYPE_ICONS[item.content_type]}
            </span>
          )}
        </div>

        <div className="flex-1 min-w-0">
          {/* Pills row */}
          <div className="flex items-center gap-1.5 flex-wrap mb-1.5">
            {/* Status dot + mono label */}
            <span className="flex items-center gap-1.5">
              <span className={dot} />
              <span
                className="mono text-[10px] font-semibold tracking-widest uppercase"
                style={{ color }}
              >
                {item.status}
              </span>
            </span>

            <span
              className="mono text-[10px] px-1.5 py-0.5 rounded border flex items-center gap-1 capitalize"
              style={{ borderColor: 'var(--acm-border)', color: 'var(--acm-fg-3)', background: 'var(--acm-elev)' }}
            >
              {PLATFORM_ICONS[item.platform]}
              {item.platform}
            </span>
            <span
              className="mono text-[10px] px-1.5 py-0.5 rounded border flex items-center gap-1 capitalize"
              style={{ borderColor: 'var(--acm-border)', color: 'var(--acm-fg-3)', background: 'var(--acm-elev)' }}
            >
              {CONTENT_TYPE_ICONS[item.content_type]}
              {item.content_type}
            </span>
          </div>

          <h3 className="text-sm font-semibold truncate" style={{ color: 'var(--acm-fg)' }}>
            {item.title}
          </h3>
          <p className="text-[11px] mt-0.5" style={{ color: 'var(--acm-fg-4)' }}>
            {formatDate(item.created_at)}
          </p>
        </div>

        <button
          onClick={() => setExpanded(!expanded)}
          className="p-1 shrink-0 transition-colors"
          style={{ color: 'var(--acm-fg-4)' }}
          onMouseEnter={e => (e.currentTarget.style.color = 'var(--acm-fg-2)')}
          onMouseLeave={e => (e.currentTarget.style.color = 'var(--acm-fg-4)')}
        >
          {expanded ? <ChevronUp size={15} /> : <ChevronDown size={15} />}
        </button>
      </div>

      {/* Body preview */}
      {item.body && (
        <p
          className={`text-sm whitespace-pre-wrap ${expanded ? '' : 'line-clamp-2'}`}
          style={{ color: 'var(--acm-fg-2)' }}
        >
          {item.body}
        </p>
      )}

      {/* Expanded details */}
      {expanded && (
        <div
          className="space-y-3 pt-3"
          style={{ borderTop: '1px solid var(--acm-border)' }}
        >
          {mediaPaths.length > 0 && (
            <div>
              <p className="text-[11px] mb-1.5" style={{ color: 'var(--acm-fg-4)' }}>
                Media ({mediaPaths.length})
              </p>
              <div className="flex flex-wrap gap-1.5">
                {mediaPaths.map((p, i) => (
                  <code
                    key={i}
                    className="mono text-[11px] px-2 py-0.5 rounded break-all"
                    style={{
                      background: 'var(--acm-elev)',
                      color: 'var(--acm-fg-3)',
                      border: '1px solid var(--acm-border)',
                    }}
                  >
                    {p.split(/[\\/]/).pop()}
                  </code>
                ))}
              </div>
            </div>
          )}

          {Object.keys(meta).length > 0 && (
            <div>
              <p className="text-[11px] mb-1.5" style={{ color: 'var(--acm-fg-4)' }}>Metadata</p>
              <pre
                className="mono text-[11px] p-2.5 rounded overflow-auto max-h-32"
                style={{
                  background: 'var(--acm-elev)',
                  color: 'var(--acm-fg-3)',
                  border: '1px solid var(--acm-border)',
                }}
              >
                {JSON.stringify(meta, null, 2)}
              </pre>
            </div>
          )}

          {item.publish_error && (
            <div
              className="flex items-start gap-2 text-[12px] rounded-lg p-2.5"
              style={{
                color: 'var(--acm-err)',
                background: 'oklch(0.68 0.13 22 / 0.1)',
                border: '1px solid oklch(0.68 0.13 22 / 0.25)',
              }}
            >
              <AlertCircle size={12} className="mt-0.5 shrink-0" />
              {item.publish_error}
            </div>
          )}

          {item.swarm_id && (
            <p className="text-[11px]" style={{ color: 'var(--acm-fg-4)' }}>
              Generated by swarm #{item.swarm_id}
            </p>
          )}
        </div>
      )}

      {/* Actions */}
      {item.status === 'pending' && (
        <div className="flex gap-2 pt-1">
          <button
            onClick={() => onApprove(item.id)}
            className="btn-primary flex-1 justify-center"
            style={{ fontSize: '12px', padding: '6px 10px' }}
          >
            <CheckCircle size={13} />
            Approve &amp; Publish
          </button>
          <button
            onClick={() => onReject(item.id)}
            className="btn-secondary flex-1 justify-center"
            style={{ fontSize: '12px', padding: '6px 10px' }}
          >
            <XCircle size={13} />
            Reject
          </button>
        </div>
      )}

      {item.status !== 'pending' && (
        <div className="flex justify-end">
          <button
            onClick={() => onDelete(item.id)}
            className="flex items-center gap-1 text-[12px] transition-colors"
            style={{ color: 'var(--acm-fg-4)' }}
            onMouseEnter={e => (e.currentTarget.style.color = 'var(--acm-err)')}
            onMouseLeave={e => (e.currentTarget.style.color = 'var(--acm-fg-4)')}
          >
            <Trash2 size={12} />
            Delete
          </button>
        </div>
      )}
    </div>
  );
}

// ── Setup Guide ────────────────────────────────────────────────────────────

function SetupGuide() {
  return (
    <div
      className="acm-card p-6 space-y-5 text-sm"
      style={{ color: 'var(--acm-fg-2)' }}
    >
      <h2 className="text-base font-semibold" style={{ color: 'var(--acm-fg)' }}>
        How to set up Social Media
      </h2>

      <div>
        <h3
          className="font-semibold mb-2 mono text-[12px] tracking-widest uppercase"
          style={{ color: 'var(--acm-accent)' }}
        >
          Facebook Page
        </h3>
        <ol className="list-decimal list-inside space-y-1 text-[12px]" style={{ color: 'var(--acm-fg-3)' }}>
          <li>Go to <strong style={{ color: 'var(--acm-fg-2)' }}>developers.facebook.com</strong> → Create App → Business</li>
          <li>Add product: <strong style={{ color: 'var(--acm-fg-2)' }}>Facebook Login</strong> and <strong style={{ color: 'var(--acm-fg-2)' }}>Pages API</strong></li>
          <li>In App Settings → Basic, get your <strong style={{ color: 'var(--acm-fg-2)' }}>App ID</strong></li>
          <li>
            Use Graph API Explorer to get a <strong style={{ color: 'var(--acm-fg-2)' }}>Page Access Token</strong> with permissions:{' '}
            <code className="mono text-[11px] px-1 rounded" style={{ background: 'var(--acm-elev)', color: 'var(--acm-fg-3)' }}>pages_manage_posts</code>,{' '}
            <code className="mono text-[11px] px-1 rounded" style={{ background: 'var(--acm-elev)', color: 'var(--acm-fg-3)' }}>pages_read_engagement</code>
          </li>
          <li>Convert to a long-lived token (60-day expiry)</li>
          <li>Save credentials using the button above</li>
        </ol>
      </div>

      <div>
        <h3
          className="font-semibold mb-2 mono text-[12px] tracking-widest uppercase"
          style={{ color: 'var(--acm-accent)' }}
        >
          Reddit
        </h3>
        <ol className="list-decimal list-inside space-y-1 text-[12px]" style={{ color: 'var(--acm-fg-3)' }}>
          <li>Go to <strong style={{ color: 'var(--acm-fg-2)' }}>reddit.com/prefs/apps</strong></li>
          <li>Click <strong style={{ color: 'var(--acm-fg-2)' }}>create another app...</strong></li>
          <li>Choose type: <strong style={{ color: 'var(--acm-fg-2)' }}>script</strong> (for personal use)</li>
          <li>
            Fill name, description, redirect URI (can be{' '}
            <code className="mono text-[11px] px-1 rounded" style={{ background: 'var(--acm-elev)', color: 'var(--acm-fg-3)' }}>http://localhost</code>)
          </li>
          <li>Note the <strong style={{ color: 'var(--acm-fg-2)' }}>client_id</strong> (under the app name) and <strong style={{ color: 'var(--acm-fg-2)' }}>client_secret</strong></li>
          <li>Save credentials using the button above</li>
        </ol>
      </div>

      <div
        className="rounded-lg p-3"
        style={{
          background: 'var(--acm-elev)',
          border: '1px solid var(--acm-border)',
        }}
      >
        <p className="text-[12px]" style={{ color: 'var(--acm-fg-3)' }}>
          <strong style={{ color: 'var(--acm-fg-2)' }}>Auto-posting swarm:</strong> Once credentials are set, create a swarm template in the Cron page
          with action type{' '}
          <code className="mono text-[11px] px-1 rounded" style={{ background: 'var(--acm-card)', color: 'var(--acm-fg-3)' }}>run_swarm_template</code>.
          The swarm will automatically capture your sessions, generate content, queue it for approval here, and post when you approve.
        </p>
      </div>
    </div>
  );
}

// ── Main Page ──────────────────────────────────────────────────────────────

const STATUS_TABS = ['pending', 'approved', 'rejected', 'published', 'all'];

export default function ContentPage() {
  const token = useAuthStore((s) => s.token);
  const authHeader: Record<string, string> = token ? { Authorization: `Bearer ${token}` } : {};

  const [items, setItems] = useState<ContentItem[]>([]);
  const [pendingCount, setPendingCount] = useState(0);
  const [credentials, setCredentials] = useState<SocialCredential[]>([]);
  const [loading, setLoading] = useState(true);
  const [statusFilter, setStatusFilter] = useState<string>('pending');
  const [showSetup, setShowSetup] = useState(false);
  const [credModal, setCredModal] = useState<'facebook' | 'reddit' | null>(null);
  const [actionLoading, setActionLoading] = useState<number | null>(null);
  const [verifyResult, setVerifyResult] = useState<Record<string, { ok: boolean; message: string } | null>>({});
  const [verifying, setVerifying] = useState<string | null>(null);

  const handleVerify = async (platform: 'facebook' | 'reddit') => {
    setVerifying(platform);
    setVerifyResult(p => ({ ...p, [platform]: null }));
    try {
      const res = await fetch(`/api/social/credentials/${platform}/verify`, {
        method: 'POST',
        headers: authHeader,
      });
      const data = await res.json();
      setVerifyResult(p => ({ ...p, [platform]: data }));
    } catch (e: any) {
      setVerifyResult(p => ({ ...p, [platform]: { ok: false, message: e.message } }));
    } finally {
      setVerifying(null);
    }
  };

  const fetchAll = useCallback(async () => {
    setLoading(true);
    try {
      const [queueRes, credRes] = await Promise.all([
        fetch(`/api/content/queue?status=${statusFilter}&limit=50`, { headers: authHeader }),
        fetch('/api/social/credentials', { headers: authHeader }),
      ]);
      if (queueRes.ok) {
        const data = await queueRes.json();
        setItems(data.items || []);
        setPendingCount(data.pending_count || 0);
      }
      if (credRes.ok) {
        setCredentials(await credRes.json());
      }
    } finally {
      setLoading(false);
    }
  }, [statusFilter, token]);

  useEffect(() => { fetchAll(); }, [fetchAll]);

  const handleApprove = async (id: number) => {
    setActionLoading(id);
    try {
      await fetch(`/api/content/queue/${id}/approve`, { method: 'POST', headers: authHeader });
      await fetchAll();
    } finally {
      setActionLoading(null);
    }
  };

  const handleReject = async (id: number) => {
    setActionLoading(id);
    try {
      await fetch(`/api/content/queue/${id}/reject`, { method: 'POST', headers: authHeader });
      await fetchAll();
    } finally {
      setActionLoading(null);
    }
  };

  const handleDelete = async (id: number) => {
    setActionLoading(id);
    try {
      await fetch(`/api/content/queue/${id}`, { method: 'DELETE', headers: authHeader });
      await fetchAll();
    } finally {
      setActionLoading(null);
    }
  };

  const hasFacebook = credentials.some((c) => c.platform === 'facebook');
  const hasReddit   = credentials.some((c) => c.platform === 'reddit');

  return (
    <AppLayout>
      <div className="p-6 space-y-6 max-w-4xl mx-auto" style={{ minHeight: '100%' }}>

        {/* Page header */}
        <header>
          <span className="acm-breadcrumb">Publishing</span>
          <div className="flex items-end justify-between flex-wrap gap-3">
            <div>
              <h1 className="text-2xl font-bold flex items-center gap-2" style={{ color: 'var(--acm-fg)' }}>
                <Sparkles size={22} style={{ color: 'var(--acm-accent)' }} />
                Auto Content
              </h1>
              <p className="text-sm mt-1" style={{ color: 'var(--acm-fg-3)' }}>
                AI-generated posts waiting for your approval before publishing
              </p>
            </div>

            <div className="flex items-center gap-2">
              {pendingCount > 0 && (
                <span
                  className="mono text-[11px] font-bold rounded-full px-2 py-0.5"
                  style={{
                    background: 'var(--acm-accent)',
                    color: 'oklch(0.18 0.015 80)',
                  }}
                >
                  {pendingCount} pending
                </span>
              )}
              <button
                onClick={fetchAll}
                className="btn-secondary"
                style={{ padding: '7px 10px' }}
                title="Refresh"
              >
                <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
              </button>
              <button
                onClick={() => setShowSetup(!showSetup)}
                className="btn-secondary"
                style={{ fontSize: '12px' }}
              >
                <Settings size={13} />
                Setup
              </button>
            </div>
          </div>
        </header>

        {/* Setup guide */}
        {showSetup && <SetupGuide />}

        {/* Credentials status */}
        <div className="flex gap-3 flex-wrap">
          {[
            { platform: 'facebook' as const, label: 'Facebook', has: hasFacebook },
            { platform: 'reddit'   as const, label: 'Reddit',   has: hasReddit },
          ].map(({ platform, label, has }) => (
            <div
              key={platform}
              className="flex items-center gap-2 px-3 py-2 rounded-lg text-[13px]"
              style={{
                border: `1px solid ${has ? 'oklch(0.75 0.09 160 / 0.3)' : 'var(--acm-border)'}`,
                background: has ? 'oklch(0.75 0.09 160 / 0.07)' : 'var(--acm-elev)',
              }}
            >
              <span style={{ color: has ? 'var(--acm-ok)' : 'var(--acm-fg-4)' }}>
                {PLATFORM_ICONS[platform]}
              </span>
              <span style={{ color: has ? 'var(--acm-fg-2)' : 'var(--acm-fg-3)' }}>
                {label}
              </span>

              {has ? (
                <>
                  <span className="dot dot-ok" />
                  <button
                    onClick={() => handleVerify(platform)}
                    disabled={verifying === platform}
                    className="text-[11px] underline transition-opacity opacity-60 hover:opacity-100"
                    style={{ color: 'var(--acm-fg-3)' }}
                  >
                    {verifying === platform ? 'Testing...' : 'Test'}
                  </button>
                  <button
                    onClick={() => setCredModal(platform)}
                    className="text-[11px] underline transition-opacity opacity-50 hover:opacity-100"
                    style={{ color: 'var(--acm-fg-3)' }}
                  >
                    Edit
                  </button>
                </>
              ) : (
                <>
                  <span className="dot dot-idle" />
                  <button
                    onClick={() => setCredModal(platform)}
                    className="text-[11px] underline"
                    style={{ color: 'var(--acm-accent)' }}
                  >
                    Connect
                  </button>
                </>
              )}

              {verifyResult[platform] && (
                <span
                  className="text-[11px] mono"
                  style={{
                    color: verifyResult[platform]!.ok ? 'var(--acm-ok)' : 'var(--acm-err)',
                  }}
                >
                  {verifyResult[platform]!.ok ? '✓' : '✗'} {verifyResult[platform]!.message}
                </span>
              )}
            </div>
          ))}
        </div>

        {/* Status filter tabs */}
        <div
          className="flex gap-1 rounded-lg p-1 w-fit flex-wrap"
          style={{ background: 'var(--acm-elev)' }}
        >
          {STATUS_TABS.map((s) => {
            const isActive = s === 'all' ? statusFilter === '' : statusFilter === s;
            return (
              <button
                key={s}
                onClick={() => setStatusFilter(s === 'all' ? '' : s)}
                className="px-3 py-1.5 rounded-md text-[12px] font-medium capitalize transition-colors relative"
                style={{
                  background: isActive ? 'var(--acm-card)' : 'transparent',
                  color: isActive ? 'var(--acm-fg)' : 'var(--acm-fg-4)',
                  border: isActive ? '1px solid var(--acm-border)' : '1px solid transparent',
                }}
              >
                {s}
                {s === 'pending' && pendingCount > 0 && (
                  <span
                    className="ml-1.5 mono text-[10px] font-bold rounded-full px-1.5 py-px"
                    style={{
                      background: 'var(--acm-accent)',
                      color: 'oklch(0.18 0.015 80)',
                    }}
                  >
                    {pendingCount}
                  </span>
                )}
              </button>
            );
          })}
        </div>

        {/* Content list */}
        {loading ? (
          <div
            className="flex items-center gap-2 py-12 justify-center text-sm"
            style={{ color: 'var(--acm-fg-4)' }}
          >
            <RefreshCw size={15} className="animate-spin" />
            Loading...
          </div>
        ) : items.length === 0 ? (
          <div className="text-center py-16 space-y-3">
            <div
              className="w-14 h-14 rounded-2xl mx-auto flex items-center justify-center"
              style={{ background: 'var(--acm-elev)' }}
            >
              <Sparkles size={24} style={{ color: 'var(--acm-fg-4)' }} />
            </div>
            <p className="text-sm" style={{ color: 'var(--acm-fg-3)' }}>
              {statusFilter === 'pending' || !statusFilter
                ? 'No content pending approval. The auto-content swarm will add items here when it runs.'
                : `No ${statusFilter} content.`}
            </p>
          </div>
        ) : (
          <div className="grid gap-3">
            {items.map((item) => (
              <ContentCard
                key={item.id}
                item={item}
                onApprove={handleApprove}
                onReject={handleReject}
                onDelete={handleDelete}
              />
            ))}
          </div>
        )}

        {/* Credential modal */}
        {credModal && (
          <CredentialModal
            platform={credModal}
            onClose={() => setCredModal(null)}
            onSaved={fetchAll}
            authHeader={authHeader}
          />
        )}
      </div>
    </AppLayout>
  );
}
