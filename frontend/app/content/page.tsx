'use client';

import { useState, useEffect, useCallback } from 'react';
import {
  Sparkles,
  CheckCircle,
  XCircle,
  Trash2,
  RefreshCw,
  Clock,
  Image as ImageIcon,
  FileText,
  Video,
  Share2,
  MessageSquare,
  Settings,
  ChevronDown,
  ChevronUp,
  AlertCircle,
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
  facebook: <Share2 size={14} />,
  reddit: <MessageSquare size={14} />,
};

const CONTENT_TYPE_ICONS: Record<string, React.ReactNode> = {
  post: <FileText size={14} />,
  meme: <ImageIcon size={14} />,
  video: <Video size={14} />,
};

const STATUS_COLORS: Record<string, string> = {
  pending: 'text-amber-400 bg-amber-400/10 border-amber-400/30',
  approved: 'text-green-400 bg-green-400/10 border-green-400/30',
  rejected: 'text-red-400 bg-red-400/10 border-red-400/30',
  published: 'text-blue-400 bg-blue-400/10 border-blue-400/30',
  failed: 'text-red-500 bg-red-500/10 border-red-500/30',
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
    { key: 'page_id', label: 'Page ID', placeholder: 'e.g. 123456789' },
    { key: 'page_access_token', label: 'Page Access Token', placeholder: 'EAAxxxxx...' },
  ];
  const redditFields = [
    { key: 'client_id', label: 'Client ID', placeholder: 'From reddit.com/prefs/apps' },
    { key: 'client_secret', label: 'Client Secret', placeholder: '' },
    { key: 'username', label: 'Reddit Username', placeholder: 'u/yourname' },
    { key: 'password', label: 'Password', placeholder: '' },
    { key: 'user_agent', label: 'User Agent', placeholder: 'OpenACM/1.0 by u/yourname' },
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
      <div className="bg-slate-900 border border-slate-700 rounded-xl w-full max-w-md p-6 space-y-4">
        <h2 className="text-lg font-semibold text-white capitalize">
          {platform} Credentials
        </h2>
        {fieldDefs.map((f) => (
          <div key={f.key}>
            <label className="block text-xs text-slate-400 mb-1">{f.label}</label>
            <input
              type={f.key.toLowerCase().includes('password') || f.key.includes('secret') || f.key.includes('token') ? 'password' : 'text'}
              className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-blue-500"
              placeholder={f.placeholder}
              value={fields[f.key] || ''}
              onChange={(e) => setFields((p) => ({ ...p, [f.key]: e.target.value }))}
            />
          </div>
        ))}
        {error && <p className="text-red-400 text-xs">{error}</p>}
        <div className="flex gap-2 pt-2">
          <button
            onClick={onClose}
            className="flex-1 px-4 py-2 rounded-lg border border-slate-700 text-slate-300 hover:bg-slate-800 text-sm"
          >
            Cancel
          </button>
          <button
            onClick={handleSave}
            disabled={saving}
            className="flex-1 px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium disabled:opacity-60"
          >
            {saving ? 'Saving...' : 'Save'}
          </button>
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

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-4 space-y-3">
      {/* Header */}
      <div className="flex items-start gap-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap mb-1">
            <span className={`inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full border font-medium ${STATUS_COLORS[item.status]}`}>
              {item.status}
            </span>
            <span className="inline-flex items-center gap-1 text-xs text-slate-400 capitalize">
              {PLATFORM_ICONS[item.platform]} {item.platform}
            </span>
            <span className="inline-flex items-center gap-1 text-xs text-slate-400 capitalize">
              {CONTENT_TYPE_ICONS[item.content_type]} {item.content_type}
            </span>
          </div>
          <h3 className="text-sm font-semibold text-white truncate">{item.title}</h3>
          <p className="text-xs text-slate-500 mt-0.5">{formatDate(item.created_at)}</p>
        </div>
        <button
          onClick={() => setExpanded(!expanded)}
          className="text-slate-500 hover:text-slate-300 p-1"
        >
          {expanded ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
        </button>
      </div>

      {/* Body preview */}
      {item.body && (
        <p className={`text-sm text-slate-300 whitespace-pre-wrap ${expanded ? '' : 'line-clamp-2'}`}>
          {item.body}
        </p>
      )}

      {/* Expanded details */}
      {expanded && (
        <div className="space-y-2 pt-1 border-t border-slate-800">
          {mediaPaths.length > 0 && (
            <div>
              <p className="text-xs text-slate-500 mb-1">Media ({mediaPaths.length})</p>
              <div className="flex flex-wrap gap-2">
                {mediaPaths.map((p, i) => (
                  <code key={i} className="text-xs bg-slate-800 px-2 py-1 rounded text-slate-300 break-all">
                    {p.split(/[\\/]/).pop()}
                  </code>
                ))}
              </div>
            </div>
          )}
          {Object.keys(meta).length > 0 && (
            <div>
              <p className="text-xs text-slate-500 mb-1">Metadata</p>
              <pre className="text-xs text-slate-400 bg-slate-800 p-2 rounded overflow-auto max-h-32">
                {JSON.stringify(meta, null, 2)}
              </pre>
            </div>
          )}
          {item.publish_error && (
            <div className="flex items-start gap-2 text-red-400 text-xs bg-red-500/10 border border-red-500/20 rounded-lg p-2">
              <AlertCircle size={12} className="mt-0.5 shrink-0" />
              {item.publish_error}
            </div>
          )}
          {item.swarm_id && (
            <p className="text-xs text-slate-500">Generated by swarm #{item.swarm_id}</p>
          )}
        </div>
      )}

      {/* Actions */}
      {item.status === 'pending' && (
        <div className="flex gap-2 pt-1">
          <button
            onClick={() => onApprove(item.id)}
            className="flex-1 flex items-center justify-center gap-1.5 px-3 py-2 rounded-lg bg-green-600/20 hover:bg-green-600/30 border border-green-600/30 text-green-400 text-xs font-medium transition-colors"
          >
            <CheckCircle size={14} /> Approve & Publish
          </button>
          <button
            onClick={() => onReject(item.id)}
            className="flex-1 flex items-center justify-center gap-1.5 px-3 py-2 rounded-lg bg-red-600/20 hover:bg-red-600/30 border border-red-600/30 text-red-400 text-xs font-medium transition-colors"
          >
            <XCircle size={14} /> Reject
          </button>
        </div>
      )}
      {item.status !== 'pending' && (
        <div className="flex justify-end">
          <button
            onClick={() => onDelete(item.id)}
            className="flex items-center gap-1 text-xs text-slate-500 hover:text-red-400 transition-colors"
          >
            <Trash2 size={12} /> Delete
          </button>
        </div>
      )}
    </div>
  );
}

// ── Setup Guide ────────────────────────────────────────────────────────────

function SetupGuide() {
  return (
    <div className="bg-slate-900 border border-slate-700 rounded-xl p-6 space-y-4 text-sm text-slate-300">
      <h2 className="text-base font-semibold text-white">How to set up Social Media</h2>

      <div>
        <h3 className="font-medium text-blue-400 mb-1">Facebook Page</h3>
        <ol className="list-decimal list-inside space-y-1 text-slate-400 text-xs">
          <li>Go to <strong className="text-slate-300">developers.facebook.com</strong> → Create App → Business</li>
          <li>Add product: <strong className="text-slate-300">Facebook Login</strong> and <strong className="text-slate-300">Pages API</strong></li>
          <li>In App Settings → Basic, get your <strong className="text-slate-300">App ID</strong></li>
          <li>Use Graph API Explorer to get a <strong className="text-slate-300">Page Access Token</strong> with permissions:
            <code className="ml-1 bg-slate-800 px-1 rounded">pages_manage_posts</code>,
            <code className="ml-1 bg-slate-800 px-1 rounded">pages_read_engagement</code>
          </li>
          <li>Convert to a long-lived token (60-day expiry)</li>
          <li>Save credentials using the button above</li>
        </ol>
      </div>

      <div>
        <h3 className="font-medium text-orange-400 mb-1">Reddit</h3>
        <ol className="list-decimal list-inside space-y-1 text-slate-400 text-xs">
          <li>Go to <strong className="text-slate-300">reddit.com/prefs/apps</strong></li>
          <li>Click <strong className="text-slate-300">create another app...</strong></li>
          <li>Choose type: <strong className="text-slate-300">script</strong> (for personal use)</li>
          <li>Fill name, description, redirect URI (can be <code className="bg-slate-800 px-1 rounded">http://localhost</code>)</li>
          <li>Note the <strong className="text-slate-300">client_id</strong> (under the app name) and <strong className="text-slate-300">client_secret</strong></li>
          <li>Save credentials using the button above</li>
        </ol>
      </div>

      <div className="bg-slate-800/50 border border-slate-700 rounded-lg p-3">
        <p className="text-xs text-slate-400">
          <strong className="text-slate-300">Auto-posting swarm:</strong> Once credentials are set, create a swarm template in the Cron page
          with action type <code className="bg-slate-800 px-1 rounded">run_swarm_template</code>. The swarm will
          automatically capture your sessions, generate content, queue it for approval here, and post when you approve.
        </p>
      </div>
    </div>
  );
}

// ── Main Page ──────────────────────────────────────────────────────────────

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
  const hasReddit = credentials.some((c) => c.platform === 'reddit');

  const STATUS_TABS = ['pending', 'approved', 'rejected', 'published', 'all'];

  return (
    <AppLayout>
    <div className="p-6 space-y-6 max-w-4xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold text-white flex items-center gap-2">
            <Sparkles className="text-amber-400" size={24} />
            Auto Content
          </h1>
          <p className="text-slate-400 text-sm mt-1">
            AI-generated posts waiting for your approval before publishing
          </p>
        </div>
        <div className="flex items-center gap-2">
          {pendingCount > 0 && (
            <span className="text-xs font-bold bg-amber-500 text-black rounded-full px-2 py-1">
              {pendingCount} pending
            </span>
          )}
          <button
            onClick={fetchAll}
            className="p-2 rounded-lg border border-slate-700 text-slate-400 hover:text-white hover:border-slate-500 transition-colors"
          >
            <RefreshCw size={16} className={loading ? 'animate-spin' : ''} />
          </button>
          <button
            onClick={() => setShowSetup(!showSetup)}
            className="flex items-center gap-1.5 px-3 py-2 rounded-lg border border-slate-700 text-slate-300 hover:bg-slate-800 text-sm transition-colors"
          >
            <Settings size={14} /> Setup
          </button>
        </div>
      </div>

      {/* Setup toggle */}
      {showSetup && <SetupGuide />}

      {/* Credentials status */}
      <div className="flex gap-3 flex-wrap">
        {[
          { platform: 'facebook' as const, label: 'Facebook', has: hasFacebook, color: 'blue' },
          { platform: 'reddit' as const, label: 'Reddit', has: hasReddit, color: 'orange' },
        ].map(({ platform, label, has, color }) => (
          <div
            key={platform}
            className={`flex items-center gap-2 px-3 py-2 rounded-lg border text-sm ${
              has
                ? 'border-green-600/30 bg-green-600/10 text-green-400'
                : 'border-slate-700 bg-slate-800/50 text-slate-400'
            }`}
          >
            {PLATFORM_ICONS[platform]}
            <span>{label}</span>
            {has ? (
              <>
                <CheckCircle size={12} />
                <button
                  onClick={() => handleVerify(platform)}
                  disabled={verifying === platform}
                  className="text-xs underline hover:text-white ml-1 opacity-70 hover:opacity-100"
                >
                  {verifying === platform ? 'Testing...' : 'Test'}
                </button>
                <button
                  onClick={() => setCredModal(platform)}
                  className="text-xs underline hover:text-white opacity-50 hover:opacity-100"
                >
                  Edit
                </button>
              </>
            ) : (
              <button
                onClick={() => setCredModal(platform)}
                className="text-xs underline hover:text-white ml-1"
              >
                Connect
              </button>
            )}
            {verifyResult[platform] && (
              <span className={`text-xs ml-1 ${verifyResult[platform]!.ok ? 'text-green-300' : 'text-red-400'}`}>
                {verifyResult[platform]!.ok ? '✓' : '✗'} {verifyResult[platform]!.message}
              </span>
            )}
          </div>
        ))}
      </div>

      {/* Status filter tabs */}
      <div className="flex gap-1 bg-slate-800/50 rounded-lg p-1 w-fit flex-wrap">
        {STATUS_TABS.map((s) => (
          <button
            key={s}
            onClick={() => setStatusFilter(s === 'all' ? '' : s)}
            className={`px-3 py-1.5 rounded-md text-xs font-medium capitalize transition-colors ${
              (s === 'all' ? statusFilter === '' : statusFilter === s)
                ? 'bg-slate-700 text-white'
                : 'text-slate-400 hover:text-slate-200'
            }`}
          >
            {s}
            {s === 'pending' && pendingCount > 0 && (
              <span className="ml-1 bg-amber-500 text-black rounded-full px-1 text-xs">{pendingCount}</span>
            )}
          </button>
        ))}
      </div>

      {/* Content list */}
      {loading ? (
        <div className="flex items-center gap-2 text-slate-400 py-8 justify-center">
          <RefreshCw size={16} className="animate-spin" />
          Loading...
        </div>
      ) : items.length === 0 ? (
        <div className="text-center py-16 space-y-3">
          <Sparkles size={40} className="mx-auto text-slate-600" />
          <p className="text-slate-400">
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
