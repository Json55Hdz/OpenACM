"use client";

import { useState, useEffect, useCallback } from "react";
import { Mail, RefreshCw, Settings } from "lucide-react";
import { CategoryTabs } from "./components/CategoryTabs";
import { EmailList } from "./components/EmailList";
import { EmailDetail } from "./components/EmailDetail";
import { CategoryManager } from "./components/CategoryManager";
import { ProcessingProgress } from "./components/ProcessingProgress";
import { PluginSettings } from "./components/PluginSettings";

const API = "/api/gmail-classifier";

interface Category {
  id: number;
  name: string;
  description: string;
  color: string;
  icon: string;
  email_count: number;
}

interface Email {
  id: number;
  gmail_id: string;
  subject: string;
  sender_name: string;
  sender_email: string;
  snippet: string;
  category_id: number;
  category_name: string;
  category_color: string;
  category_icon: string;
  is_read: number;
  is_replied: number;
  received_at: string;
}

interface ProcessStatus {
  running: boolean;
  processed: number;
  total: number;
  errors: number;
  started_at: string | null;
}

export default function GmailClassifierPage() {
  const [categories, setCategories] = useState<Category[]>([]);
  const [emails, setEmails] = useState<Email[]>([]);
  const [totalEmails, setTotalEmails] = useState(0);
  const [selectedCategoryId, setSelectedCategoryId] = useState<number | null>(null);
  const [selectedEmail, setSelectedEmail] = useState<Email | null>(null);
  const [processStatus, setProcessStatus] = useState<ProcessStatus>({
    running: false, processed: 0, total: 0, errors: 0, started_at: null,
  });
  const [sinceDate, setSinceDate] = useState("");
  const [showCategoryManager, setShowCategoryManager] = useState(false);
  const [showSettings, setShowSettings] = useState(false);

  const fetchCategories = useCallback(async () => {
    const res = await fetch(`${API}/categories`);
    if (res.ok) setCategories(await res.json());
  }, []);

  const fetchEmails = useCallback(async () => {
    const params = new URLSearchParams({ page: "1", per_page: "50" });
    if (selectedCategoryId !== null) params.set("category_id", String(selectedCategoryId));
    const res = await fetch(`${API}/emails?${params}`);
    if (res.ok) {
      const data = await res.json();
      setEmails(data.items);
      setTotalEmails(data.total);
    }
  }, [selectedCategoryId]);

  const pollStatus = useCallback(async () => {
    const res = await fetch(`${API}/process/status`);
    if (!res.ok) return;
    const status: ProcessStatus = await res.json();
    setProcessStatus(status);
    if (status.running) {
      setTimeout(pollStatus, 1500);
    } else if (status.total > 0) {
      fetchEmails();
      fetchCategories();
    }
  }, [fetchEmails, fetchCategories]);

  useEffect(() => {
    fetchCategories();
    fetchEmails();
    pollStatus();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    fetchEmails();
  }, [fetchEmails]);

  const handleProcess = async () => {
    if (!sinceDate) {
      alert("Selecciona una fecha de inicio antes de procesar");
      return;
    }
    const formatted = sinceDate.replace(/-/g, "/");
    const res = await fetch(`${API}/process`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ since_date: formatted }),
    });
    if (res.ok) {
      setProcessStatus({ running: true, processed: 0, total: 0, errors: 0, started_at: new Date().toISOString() });
      setTimeout(pollStatus, 1000);
    } else {
      const err = await res.json().catch(() => ({}));
      alert(err.detail || "Error al iniciar el proceso");
    }
  };

  const handleEmailSelect = (email: Email) => {
    setSelectedEmail(email);
    if (!email.is_read) {
      void handleEmailRead(email.id, true);
    }
  };

  const handleEmailRead = async (emailId: number, isRead: boolean) => {
    await fetch(`${API}/emails/${emailId}/read`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ is_read: isRead }),
    });
    setEmails(prev => prev.map(e => e.id === emailId ? { ...e, is_read: isRead ? 1 : 0 } : e));
    setSelectedEmail(prev => prev?.id === emailId ? { ...prev, is_read: isRead ? 1 : 0 } : prev);
  };

  const handleRecategorize = async (emailId: number, categoryId: number) => {
    const res = await fetch(`${API}/emails/${emailId}/category`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ category_id: categoryId }),
    });
    if (res.ok) {
      fetchEmails();
      fetchCategories();
      setSelectedEmail(prev => prev?.id === emailId ? { ...prev, category_id: categoryId } : prev);
    }
  };

  const handleReply = async (emailId: number, body: string): Promise<boolean> => {
    const res = await fetch(`${API}/emails/${emailId}/reply`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ body }),
    });
    if (res.ok) {
      setEmails(prev => prev.map(e => e.id === emailId ? { ...e, is_replied: 1, is_read: 1 } : e));
      setSelectedEmail(prev => prev?.id === emailId ? { ...prev, is_replied: 1, is_read: 1 } : prev);
      return true;
    }
    return false;
  };

  return (
    <div className="flex flex-col h-full bg-white overflow-hidden">
      {/* Toolbar */}
      <div className="flex items-center gap-3 px-4 py-3 border-b bg-gray-50 flex-shrink-0">
        <Mail className="text-blue-600 flex-shrink-0" size={20} />
        <h1 className="font-semibold text-gray-800 text-lg">Gmail Classifier</h1>
        <div className="flex-1" />
        <input
          type="date"
          value={sinceDate}
          onChange={e => setSinceDate(e.target.value)}
          className="text-sm border rounded px-2 py-1 text-gray-700 bg-white"
        />
        <button
          onClick={handleProcess}
          disabled={processStatus.running}
          className="flex items-center gap-1.5 bg-blue-600 text-white text-sm px-3 py-1.5 rounded hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          <RefreshCw size={14} className={processStatus.running ? "animate-spin" : ""} />
          {processStatus.running ? "Procesando..." : "Procesar"}
        </button>
        <button
          onClick={() => setShowSettings(true)}
          className="p-1.5 rounded hover:bg-gray-200 text-gray-600 transition-colors"
          title="Configuración del plugin"
        >
          <Settings size={16} />
        </button>
      </div>

      {/* Progress bar */}
      {(processStatus.running || processStatus.total > 0) && (
        <div className="px-4 py-2 border-b flex-shrink-0">
          <ProcessingProgress
            running={processStatus.running}
            processed={processStatus.processed}
            total={processStatus.total}
          />
        </div>
      )}

      {/* Category tabs */}
      <div className="flex-shrink-0">
        <CategoryTabs
          categories={categories}
          selectedId={selectedCategoryId}
          onSelect={id => {
            setSelectedCategoryId(id);
            setSelectedEmail(null);
          }}
          onManage={() => setShowCategoryManager(true)}
        />
      </div>

      {/* Split view */}
      <div className="flex flex-1 min-h-0">
        <EmailList
          emails={emails}
          selectedId={selectedEmail?.id ?? null}
          onSelect={handleEmailSelect}
        />
        <EmailDetail
          email={selectedEmail}
          categories={categories}
          onReadToggle={handleEmailRead}
          onRecategorize={handleRecategorize}
          onReply={handleReply}
        />
      </div>

      {/* Modals */}
      {showCategoryManager && (
        <CategoryManager
          categories={categories}
          onClose={() => setShowCategoryManager(false)}
          onSaved={() => {
            fetchCategories();
            fetchEmails();
          }}
        />
      )}
      {showSettings && (
        <PluginSettings onClose={() => setShowSettings(false)} />
      )}
    </div>
  );
}
