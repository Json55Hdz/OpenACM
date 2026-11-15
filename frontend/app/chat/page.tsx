'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { AppLayout } from '@/components/layout/app-layout';
import { useChatStore } from '@/stores/chat-store';
import { useAPI, useConversations, useConversationHistory, useChatCommand, useClearConversation, useCurrentModel, useSystemInfo } from '@/hooks/use-api';
import { useAgents } from '@/hooks/use-agents';
import { Send, Paperclip, X, MoreVertical, Plus, Loader2, MessageSquare, HelpCircle, Cpu, BarChart3, Download, SquareTerminal, Mic, MicOff, FileText, Music, Trash2, ShieldCheck, ChevronDown, ChevronLeft, ChevronRight, Folder, FolderOpen, ScrollText } from 'lucide-react';
import { toast } from 'sonner';
import { TerminalPanel } from '@/components/terminal/terminal-panel';
import { useTerminalStore } from '@/stores/terminal-store';
import { useAuthStore } from '@/stores/auth-store';
import { ChannelIcon, RouterLearningIndicator, MemoryRecallIndicator, SkillActiveIndicator, ContextBadge, TypingIndicator } from '@/components/chat/indicators';
import { ValidationBubble, ToolConfirmationBubble, ToolConfirmationModal } from '@/components/chat/confirmations';
import { ReasoningBubble, CompactionNoteBubble, MessageBubble } from '@/components/chat/chat-messages';
import { cn } from '@/components/chat/shared';

const CHAT_FOLDERS_STORAGE_KEY = 'openacm_chat_open_folders';


interface Conversation {
  channel_id: string;
  user_id: string;
  title: string;
  last_message: string;
  last_timestamp: string;
  message_count: number;
  channel_type?: 'whatsapp' | 'telegram' | 'discord' | 'web' | 'console' | string;
  is_agent?: boolean;
  agent_id?: number | null;
  agent_name?: string | null;
  customer_name?: string | null;
  show_in_chat?: boolean;
}

export default function ChatPage() {
  const {
    messages,
    addMessage,
    setMessages,
    currentTarget,
    setTarget,
    isWaitingResponse,
    thinkingLabel,
    currentAttachments,
    addAttachment,
    removeAttachment,
    clearAttachments,
    showToolLogs,
    setShowToolLogs,
    isRouterLearning,
    activeSkillNames,
    memoryRecall,
  } = useChatStore();

  const wsConnected = useChatStore((s) => s.wsConnected);
  const sendMessage = useChatStore((s) => s.sendMessageFn);
  const cancelMessage = useChatStore((s) => s.cancelMessageFn);
  const ctxStats = useChatStore((s) => {
    const key = `${s.currentTarget.channel}:${s.currentTarget.user}`;
    return s.contextStats[key] ?? null;
  });
  const pendingOnboardingGreeting = useChatStore((s) => s.pendingOnboardingGreeting);
  const setPendingOnboardingGreeting = useChatStore((s) => s.setPendingOnboardingGreeting);
  const { data: conversations } = useConversations();
  const { data: history, isFetching: isLoadingHistory } = useConversationHistory(currentTarget.channel, currentTarget.user);
  const chatCommand = useChatCommand();
  const clearConversation = useClearConversation();
  const { data: modelData } = useCurrentModel();
  const { data: systemInfo } = useSystemInfo();
  const { data: registeredAgents } = useAgents();
  const { fetchAPI } = useAPI();
  const queryClient = useQueryClient();

  const { isOpen: isTerminalOpen, toggleOpen: toggleTerminal } = useTerminalStore();

  const [inputValue, setInputValue] = useState('');
  const [isSidebarOpen, setIsSidebarOpen] = useState(true);
  const [deletingKey, setDeletingKey] = useState<string | null>(null);
  const [debugMode] = useState(() =>
    typeof window !== 'undefined' && localStorage.getItem('openacm_debug_mode') === 'true'
  );

  // Tool Logs switch mirrors the server setting that also gates external channels
  useEffect(() => {
    fetchAPI('/api/config/verbose_channels')
      .then((d: any) => { if (typeof d?.enabled === 'boolean') setShowToolLogs(d.enabled); })
      .catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const [isRecording, setIsRecording] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [isCompacting, setIsCompacting] = useState(false);
  const [activeConfirmation, setActiveConfirmation] = useState<{
    confirmId: string;
    tool: string;
    command: string;
  } | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);
  // Track which confirmation IDs have already been shown as a modal
  const shownConfirmIdsRef = useRef<Set<string>>(new Set());
  // Track which conversation we last loaded history for
  const loadedKeyRef = useRef('');
  // Only show reconnecting overlay after first successful connection
  const hasConnectedRef = useRef(false);
  useEffect(() => { if (wsConnected) hasConnectedRef.current = true; }, [wsConnected]);
  const showReconnecting = hasConnectedRef.current && !wsConnected;

  // Pop a modal for any new toolConfirmation message that hasn't been shown yet
  useEffect(() => {
    for (let i = messages.length - 1; i >= 0; i--) {
      const msg = messages[i];
      if (msg.toolConfirmation) {
        const { confirmId, tool, command } = msg.toolConfirmation;
        if (!shownConfirmIdsRef.current.has(confirmId)) {
          shownConfirmIdsRef.current.add(confirmId);
          setActiveConfirmation({ confirmId, tool, command });
        }
        break;
      }
    }
  }, [messages]);

  // Load conversation history when a new conversation is selected
  useEffect(() => {
    const key = `${currentTarget.channel}:${currentTarget.user}`;
    // Only load once per conversation switch (avoid re-running on live messages)
    if (loadedKeyRef.current === key) return;

    if (history && Array.isArray(history)) {
      loadedKeyRef.current = key;
      // If we already have in-memory messages for this conversation (restored from
      // the per-conversation cache), keep them — they have usage/token data.
      if (useChatStore.getState().messages.length > 0) return;
      if (history.length > 0) {
        const visible = history
          .filter((msg: { role: string; content: string }) => {
            // Skip system prompts, tool results, and assistant-only-tool-call messages
            if (msg.role === 'system') return false;
            if (msg.role === 'tool') return false;
            // Skip assistant messages that have no visible text (were just tool-call planners)
            if (msg.role === 'assistant' && (!msg.content || !msg.content.trim())) return false;
            return true;
          })
          .map((msg: { role: string; content: string }) => {
            // Parse [IMAGE:filename] markers back into attachment objects
            const attachments: Array<{ id: string; name: string; type: string }> = [];
            const content = msg.content.replace(/\[IMAGE:([^\]]+)\]/g, (_, fileId) => {
              const ext = fileId.split('.').pop()?.toLowerCase() ?? '';
              const imgExts = new Set(['png', 'jpg', 'jpeg', 'gif', 'webp']);
              attachments.push({
                id: fileId,
                name: fileId,
                type: imgExts.has(ext) ? `image/${ext === 'jpg' ? 'jpeg' : ext}` : 'application/octet-stream',
              });
              return '';
            }).trim();
            return {
              content,
              role: (msg.role === 'assistant' ? 'assistant' : 'user') as 'user' | 'assistant',
              ...(attachments.length > 0 ? { attachments } : {}),
            };
          });
        setMessages(visible);
      }
    }
  }, [history, currentTarget.channel, currentTarget.user, setMessages]);

  // Consume pending onboarding greeting — add it once history has been loaded
  // (or immediately if there's no history to load). Clear after showing.
  useEffect(() => {
    if (pendingOnboardingGreeting === null) return;
    if (isLoadingHistory) return; // wait for history to settle first
    addMessage({ content: pendingOnboardingGreeting, role: 'assistant' });
    setPendingOnboardingGreeting(null);
  }, [pendingOnboardingGreeting, isLoadingHistory, addMessage, setPendingOnboardingGreeting]);

  // Auto-scroll to bottom
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isWaitingResponse]);

  const executeCommand = async (command: string) => {
    if (command.startsWith('/compact')) setIsCompacting(true);
    try {
      const result = await chatCommand.mutateAsync({
        command,
        userId: currentTarget.user,
        channelId: currentTarget.channel,
      });
      if (result.text) {
        addMessage({ content: result.text, role: 'system' });
      }
      // Handle special data payloads
      if (result.data?.export) {
        const blob = new Blob([result.data.export], { type: 'text/plain' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'conversation.txt';
        a.click();
        URL.revokeObjectURL(url);
      }
      // If it was a clear/new/reset command, also clear local messages
      if (command.startsWith('/new') || command.startsWith('/clear') || command.startsWith('/reset')) {
        setMessages([]);
      }
      if (command.startsWith('/compact') && result.data?.compact) {
        setIsCompacting(false);
      }
    } catch {
      toast.error('Command failed');
    } finally {
      setIsCompacting(false);
    }
  };

  const handleSend = () => {
    if (!inputValue.trim() && currentAttachments.length === 0) return;

    // Intercept slash commands — send via REST, not WebSocket
    if (inputValue.trim().startsWith('/')) {
      const cmd = inputValue.trim();
      setInputValue('');
      addMessage({ content: cmd, role: 'user' });
      executeCommand(cmd);
      return;
    }

    const attachmentIds = currentAttachments.map(a => a.id);

    // Add user message to local state
    addMessage({
      content: inputValue,
      role: 'user',
      attachments: currentAttachments,
    });

    // Send via WebSocket (sendMessage is injected by the global WS hook in app-layout)
    const sent = sendMessage ? sendMessage(inputValue, attachmentIds) : false;

    if (sent) {
      setInputValue('');
      clearAttachments();
    } else {
      toast.error('Could not send message. Check your connection.');
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const uploadFile = async (file: File): Promise<{ id: string; name: string; type: string; previewUrl?: string } | null> => {
    const token = useAuthStore.getState().token;
    const formData = new FormData();
    formData.append('file', file);
    try {
      const res = await fetch('/api/chat/upload', {
        method: 'POST',
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        body: formData,
      });
      if (!res.ok) throw new Error(`Upload failed: ${res.status}`);
      const data = await res.json();
      return {
        id: data.file_id,
        name: file.name,
        type: file.type,
        previewUrl: file.type.startsWith('image/') ? URL.createObjectURL(file) : undefined,
      };
    } catch (err) {
      toast.error(`Failed to upload ${file.name}`);
      return null;
    }
  };

  const handleFileSelect = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (!files) return;
    setIsUploading(true);
    for (const file of Array.from(files)) {
      const att = await uploadFile(file);
      if (att) addAttachment(att);
    }
    setIsUploading(false);
    e.target.value = '';
  };

  const handlePaste = async (e: React.ClipboardEvent) => {
    const items = Array.from(e.clipboardData.items);
    const imageItem = items.find(i => i.type.startsWith('image/'));
    if (!imageItem) return;
    e.preventDefault();
    const file = imageItem.getAsFile();
    if (!file) return;
    const named = new File([file], `paste-${Date.now()}.png`, { type: file.type });
    setIsUploading(true);
    const att = await uploadFile(named);
    if (att) addAttachment(att);
    setIsUploading(false);
  };

  const handleMicClick = async () => {
    if (isRecording) {
      mediaRecorderRef.current?.stop();
      setIsRecording(false);
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const recorder = new MediaRecorder(stream);
      mediaRecorderRef.current = recorder;
      audioChunksRef.current = [];

      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) audioChunksRef.current.push(e.data);
      };

      recorder.onstop = async () => {
        stream.getTracks().forEach(t => t.stop());
        const blob = new Blob(audioChunksRef.current, { type: 'audio/webm' });
        const file = new File([blob], `voice-${Date.now()}.webm`, { type: 'audio/webm' });
        setIsUploading(true);
        const att = await uploadFile(file);
        if (att) {
          addAttachment(att);
          toast.success('Voice message ready — press Send');
        }
        setIsUploading(false);
      };

      recorder.start();
      setIsRecording(true);
      toast('Recording... press mic again to stop', { icon: '🎤' });
    } catch {
      toast.error('Could not access microphone');
    }
  };

  const selectConversation = (conv: Conversation) => {
    const newKey = `${conv.channel_id}:${conv.user_id}`;
    if (loadedKeyRef.current !== newKey) {
      loadedKeyRef.current = '';
    }
    setTarget({
      channel: conv.channel_id,
      user: conv.user_id,
      title: conv.title || `${conv.channel_id} - ${conv.user_id}`,
    });
  };

  const [openFolders, setOpenFolders] = useState<Record<string, boolean>>({});
  const [folderPages, setFolderPages] = useState<Record<string, number>>({});
  const PAGE_SIZE = 10;

  useEffect(() => {
    try {
      const stored = localStorage.getItem(CHAT_FOLDERS_STORAGE_KEY);
      if (stored) {
        setOpenFolders(JSON.parse(stored));
      }
    } catch {
      // ignore
    }
  }, []);

  const isFolderOpen = (key: string) => {
    return openFolders[key] ?? true;
  };

  const toggleFolder = (key: string) => {
    setOpenFolders((prev) => {
      const current = prev[key] ?? true;
      const next = {
        ...prev,
        [key]: !current,
      };
      try {
        localStorage.setItem(CHAT_FOLDERS_STORAGE_KEY, JSON.stringify(next));
      } catch {
        // ignore
      }
      return next;
    });
  };

  const getFolderPage = (key: string) => {
    return folderPages[key] ?? 1;
  };

  const setFolderPage = (key: string, page: number) => {
    setFolderPages((prev) => ({
      ...prev,
      [key]: page,
    }));
  };

  const startNewConversation = () => {
    const newUserId = `web_${Date.now()}`;
    loadedKeyRef.current = '';
    setTarget({
      channel: 'web',
      user: newUserId,
      title: 'New Conversation',
    });
    // Optimistically add the new conversation to the sidebar immediately
    queryClient.setQueryData(['conversations'], (old: Conversation[] | undefined) => {
      const entry: Conversation = {
        channel_id: 'web',
        user_id: newUserId,
        title: 'New Conversation',
        last_message: '',
        last_timestamp: new Date().toISOString(),
        message_count: 0,
        channel_type: 'web',
        is_agent: false,
      };
      return [entry, ...(old ?? [])];
    });
  };

  const handleDeleteConversation = async (conv: Conversation, e: React.MouseEvent) => {
    e.stopPropagation();
    const key = `${conv.channel_id}-${conv.user_id}`;
    setDeletingKey(key);
    try {
      await clearConversation.mutateAsync({ channelId: conv.channel_id, userId: conv.user_id });
      // If we deleted the currently active conversation, start a new one
      if (currentTarget.channel === conv.channel_id && currentTarget.user === conv.user_id) {
        startNewConversation();
      }
    } catch {
      toast.error('Failed to delete conversation');
    } finally {
      setDeletingKey(null);
    }
  };

  const conversationList: Conversation[] = conversations || [];
  const normalConversations = useMemo(
    () => conversationList.filter((c) => !c.is_agent),
    [conversationList]
  );
  const agentConversations = useMemo(
    () => conversationList.filter((c) => !!c.is_agent),
    [conversationList]
  );

  // Group agent conversations: ONE FOLDER PER AGENT (honoring show_in_chat)
  const agentGroups = useMemo(() => {
    const map = new Map<string, { id: number | null; name: string; convs: Conversation[] }>();
    const hiddenAgentIds = new Set<number>();

    // 1. Seed with registered agents
    if (registeredAgents && registeredAgents.length > 0) {
      for (const ag of registeredAgents) {
        if (ag.show_in_chat === false || (ag.show_in_chat as unknown) === 0) {
          hiddenAgentIds.add(ag.id);
          continue;
        }
        map.set(`agent_${ag.id}`, { id: ag.id, name: ag.name, convs: [] });
      }
    }

    // 2. Map every agent conversation into its respective agent group
    for (const conv of agentConversations) {
      if (conv.show_in_chat === false) continue;
      if (conv.agent_id && hiddenAgentIds.has(conv.agent_id)) continue;

      if (conv.agent_id && map.has(`agent_${conv.agent_id}`)) {
        map.get(`agent_${conv.agent_id}`)!.convs.push(conv);
      } else if (conv.agent_id) {
        const name = conv.agent_name || `Agent #${conv.agent_id}`;
        map.set(`agent_${conv.agent_id}`, { id: conv.agent_id, name, convs: [conv] });
      } else {
        const key = 'agent_other';
        if (!map.has(key)) {
          map.set(key, { id: null, name: conv.agent_name || 'Other Agents', convs: [] });
        }
        map.get(key)!.convs.push(conv);
      }
    }

    return Array.from(map.entries()).map(([key, data]) => ({
      key,
      ...data,
    }));
  }, [registeredAgents, agentConversations]);

  const totalPagesDirect = Math.max(1, Math.ceil(normalConversations.length / PAGE_SIZE));
  const safePageDirect = Math.min(getFolderPage('direct'), totalPagesDirect);
  const paginatedDirect = normalConversations.slice((safePageDirect - 1) * PAGE_SIZE, safePageDirect * PAGE_SIZE);

  const activeConv = conversationList.find(
    (c) => c.channel_id === currentTarget.channel && c.user_id === currentTarget.user
  );


  const renderConversationItem = (conv: Conversation) => {
    const convKey = `${conv.channel_id}-${conv.user_id}`;
    const isActive = currentTarget.channel === conv.channel_id && currentTarget.user === conv.user_id;
    const isDeleting = deletingKey === convKey;
    const isDeletable = conv.channel_id !== 'console';
    return (
      <div
        key={convKey}
        className={cn(
          "group relative w-full text-left px-[10px] py-[8px] rounded-[6px] transition-colors cursor-pointer",
          isActive
            ? "border-l-2 border-l-[var(--acm-accent)] bg-[var(--acm-elev)] pl-[8px]"
            : "border-l-2 border-l-transparent hover:bg-[var(--acm-card)]"
        )}
        onClick={() => selectConversation(conv)}
      >
        <div className="flex items-center gap-2">
          <ChannelIcon channelType={conv.channel_type} />
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-1.5">
              <p className={cn(
                "text-[12.5px] font-medium truncate",
                isActive ? "text-[var(--acm-fg)]" : "text-[var(--acm-fg-2)]"
              )}>
                {conv.title || `${conv.channel_id} - ${conv.user_id}`}
              </p>
              {conv.message_count === 0 && (
                <span className="shrink-0 mono text-[10px] px-1.5 py-0.5 bg-[oklch(0.84_0.16_82/0.1)] text-[var(--acm-accent)] rounded-full border border-[oklch(0.84_0.16_82/0.3)]">
                  New
                </span>
              )}
            </div>
            <p className="mono text-[10px] text-[var(--acm-fg-4)] truncate mt-[1px]">
              {conv.last_message || 'No messages yet'}
            </p>
          </div>
          {conv.message_count > 0 && (
            <span className="mono text-[10px] text-[var(--acm-fg-4)] group-hover:hidden">
              {conv.message_count}
            </span>
          )}
          {isDeletable && (
            <button
              onClick={(e) => handleDeleteConversation(conv, e)}
              disabled={isDeleting}
              className={cn(
                "hidden group-hover:flex items-center justify-center w-6 h-6 rounded-[4px] transition-colors shrink-0",
                "text-[var(--acm-fg-4)] hover:text-[var(--acm-err)] hover:bg-[oklch(0.68_0.13_22/0.1)]",
                isDeleting && "!flex"
              )}
              title="Delete conversation"
            >
              {isDeleting
                ? <Loader2 size={12} className="animate-spin" />
                : <Trash2 size={12} />
              }
            </button>
          )}
        </div>
      </div>
    );
  };

  return (
    <AppLayout>
      <div className="h-screen flex bg-[var(--acm-base)]">
        {/* Sidebar - Conversation List */}
        <div className={cn(
          "fixed lg:static inset-y-0 left-0 w-72 bg-[var(--acm-base)] border-r border-[var(--acm-border)] z-30 transition-transform duration-300",
          isSidebarOpen ? "translate-x-0" : "-translate-x-full lg:translate-x-0 lg:w-0 lg:overflow-hidden lg:border-r-0"
        )}>
          <div className="flex flex-col h-full">
            {/* Sidebar header */}
            <div className="px-[16px] py-[14px] border-b border-[var(--acm-border)]">
              <div className="flex items-center justify-between mb-3">
                <span className="label text-[var(--acm-fg-3)]">Conversations</span>
                <button
                  onClick={() => setIsSidebarOpen(false)}
                  className="lg:hidden p-1 text-[var(--acm-fg-4)] hover:text-[var(--acm-fg)] transition-colors"
                >
                  <X size={16} />
                </button>
              </div>
              {systemInfo?.messages_encrypted && (
                <div className="flex items-center gap-1.5 px-2.5 py-1.5 mb-3 rounded-[6px] border border-[var(--acm-border)] text-[var(--acm-ok)] text-[11px] mono">
                  <ShieldCheck size={11} className="shrink-0" />
                  <span>Encrypted at rest</span>
                </div>
              )}
              <button
                onClick={startNewConversation}
                className="btn-primary w-full justify-center !text-[12px] !py-[7px]"
              >
                <Plus size={14} />
                New Conversation
              </button>
            </div>

            {/* Conversation list with folders */}
            <div className="flex-1 overflow-y-auto acm-scroll p-[8px] space-y-[8px]">
              {/* Folder: Direct Chats */}
              <div className="rounded-[6px] bg-[var(--acm-card)]/40 p-1 border border-[var(--acm-border)]/50">
                <button
                  type="button"
                  onClick={() => toggleFolder('direct')}
                  className="w-full flex items-center justify-between px-2 py-1.5 text-[11px] font-semibold tracking-wider text-[var(--acm-fg-3)] uppercase hover:text-[var(--acm-fg)] hover:bg-[var(--acm-card)] rounded-[4px] transition-colors"
                >
                  <div className="flex items-center gap-1.5 truncate">
                    {isFolderOpen('direct') ? <ChevronDown size={13} className="shrink-0" /> : <ChevronRight size={13} className="shrink-0" />}
                    {isFolderOpen('direct') ? <FolderOpen size={13} className="text-[var(--acm-accent)] shrink-0" /> : <Folder size={13} className="shrink-0" />}
                    <span className="truncate">Direct Chats</span>
                  </div>
                  <span className="mono text-[10px] px-1.5 py-0.2 rounded-full bg-[var(--acm-card)] border border-[var(--acm-border)] text-[var(--acm-fg-4)] shrink-0 ml-1">
                    {normalConversations.length}
                  </span>
                </button>

                {isFolderOpen('direct') && (
                  <div className="mt-1 space-y-[2px]">
                    {paginatedDirect.length === 0 ? (
                      <p className="mono text-[10px] text-[var(--acm-fg-4)] px-3 py-2 italic">No direct conversations</p>
                    ) : (
                      paginatedDirect.map(renderConversationItem)
                    )}

                    {totalPagesDirect > 1 && (
                      <div className="flex items-center justify-between px-2 pt-2 pb-1 border-t border-[var(--acm-border)]/40 mono text-[10px] text-[var(--acm-fg-4)]">
                        <button
                          type="button"
                          onClick={() => setFolderPage('direct', Math.max(1, safePageDirect - 1))}
                          disabled={safePageDirect <= 1}
                          className="p-1 rounded hover:bg-[var(--acm-card)] hover:text-[var(--acm-fg)] disabled:opacity-30 disabled:pointer-events-none transition-colors"
                          title="Previous page"
                        >
                          <ChevronLeft size={12} />
                        </button>
                        <span>Page {safePageDirect} of {totalPagesDirect}</span>
                        <button
                          type="button"
                          onClick={() => setFolderPage('direct', Math.min(totalPagesDirect, safePageDirect + 1))}
                          disabled={safePageDirect >= totalPagesDirect}
                          className="p-1 rounded hover:bg-[var(--acm-card)] hover:text-[var(--acm-fg)] disabled:opacity-30 disabled:pointer-events-none transition-colors"
                          title="Next page"
                        >
                          <ChevronRight size={12} />
                        </button>
                      </div>
                    )}
                  </div>
                )}
              </div>

              {/* Folders: One folder per agent */}
              {agentGroups.map((group) => {
                const totalPages = Math.max(1, Math.ceil(group.convs.length / PAGE_SIZE));
                const currentPage = Math.min(getFolderPage(group.key), totalPages);
                const paginatedConvs = group.convs.slice((currentPage - 1) * PAGE_SIZE, currentPage * PAGE_SIZE);

                return (
                  <div key={group.key} className="rounded-[6px] bg-[var(--acm-card)]/40 p-1 border border-[var(--acm-border)]/50">
                    <button
                      type="button"
                      onClick={() => toggleFolder(group.key)}
                      className="w-full flex items-center justify-between px-2 py-1.5 text-[11px] font-semibold tracking-wider text-[var(--acm-fg-3)] uppercase hover:text-[var(--acm-fg)] hover:bg-[var(--acm-card)] rounded-[4px] transition-colors"
                    >
                      <div className="flex items-center gap-1.5 truncate">
                        {isFolderOpen(group.key) ? <ChevronDown size={13} className="shrink-0" /> : <ChevronRight size={13} className="shrink-0" />}
                        {isFolderOpen(group.key) ? <FolderOpen size={13} className="text-[#25D366] shrink-0" /> : <Folder size={13} className="shrink-0" />}
                        <span className="truncate">{group.name}</span>
                      </div>
                      <span className="mono text-[10px] px-1.5 py-0.2 rounded-full bg-[var(--acm-card)] border border-[var(--acm-border)] text-[var(--acm-fg-4)] shrink-0 ml-1">
                        {group.convs.length}
                      </span>
                    </button>

                    {isFolderOpen(group.key) && (
                      <div className="mt-1 space-y-[2px]">
                        {paginatedConvs.length === 0 ? (
                          <p className="mono text-[10px] text-[var(--acm-fg-4)] px-3 py-2 italic">No conversations yet</p>
                        ) : (
                          paginatedConvs.map(renderConversationItem)
                        )}

                        {totalPages > 1 && (
                          <div className="flex items-center justify-between px-2 pt-2 pb-1 border-t border-[var(--acm-border)]/40 mono text-[10px] text-[var(--acm-fg-4)]">
                            <button
                              type="button"
                              onClick={() => setFolderPage(group.key, Math.max(1, currentPage - 1))}
                              disabled={currentPage <= 1}
                              className="p-1 rounded hover:bg-[var(--acm-card)] hover:text-[var(--acm-fg)] disabled:opacity-30 disabled:pointer-events-none transition-colors"
                              title="Previous page"
                            >
                              <ChevronLeft size={12} />
                            </button>
                            <span>Page {currentPage} of {totalPages}</span>
                            <button
                              type="button"
                              onClick={() => setFolderPage(group.key, Math.min(totalPages, currentPage + 1))}
                              disabled={currentPage >= totalPages}
                              className="p-1 rounded hover:bg-[var(--acm-card)] hover:text-[var(--acm-fg)] disabled:opacity-30 disabled:pointer-events-none transition-colors"
                              title="Next page"
                            >
                              <ChevronRight size={12} />
                            </button>
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                );
              })}

              {conversationList.length === 0 && (
                <div className="text-center py-10">
                  <MessageSquare size={32} className="mx-auto text-[var(--acm-border-strong)] mb-2" />
                  <p className="mono text-[11px] text-[var(--acm-fg-4)]">No conversations yet</p>
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Main Chat Area */}
        <div className="flex-1 flex flex-col min-w-0 bg-[var(--acm-base)] relative">
          {/* Reconnecting overlay */}
          {showReconnecting && (
            <div className="absolute inset-0 z-50 flex flex-col items-center justify-center bg-[var(--acm-base)]/90 backdrop-blur-sm">
              <Loader2 size={32} className="text-[var(--acm-accent)] animate-spin mb-4" />
              <p className="text-[var(--acm-fg-2)] text-[13.5px] font-semibold">Reconnecting to backend…</p>
              <p className="mono text-[10px] text-[var(--acm-fg-4)] mt-1">Your conversation will resume automatically</p>
            </div>
          )}

          {/* Chat header bar */}
          <div className="h-[52px] flex items-center justify-between px-[16px] border-b border-[var(--acm-border)] bg-[var(--acm-base)] flex-shrink-0">
            <div className="flex items-center gap-3">
              <button
                onClick={() => setIsSidebarOpen(true)}
                className="lg:hidden p-1.5 text-[var(--acm-fg-4)] hover:text-[var(--acm-fg)] transition-colors"
              >
                <MessageSquare size={16} />
              </button>
              {activeConv && <ChannelIcon channelType={activeConv.channel_type} />}
              <div>
                <h3 className="text-[13.5px] font-semibold text-[var(--acm-fg)] leading-tight">{currentTarget.title}</h3>
                <p className="mono text-[10px] text-[var(--acm-fg-4)]">{currentTarget.channel} · {currentTarget.user}</p>
              </div>
            </div>

            <div className="flex items-center gap-[8px]">
              {/* WS status pill */}
              <div className="inline-flex items-center gap-[7px] px-[10px] py-[4px] border border-[var(--acm-border)] rounded-full text-[11px]">
                <span className={cn("dot", wsConnected ? "dot-ok acm-pulse" : "dot-err")} />
                <span className="mono text-[var(--acm-fg-4)]">{wsConnected ? 'connected' : 'offline'}</span>
              </div>

              <button
                onClick={() => {
                  const next = !showToolLogs;
                  setShowToolLogs(next);
                  // same switch for external channels (Telegram etc.), persisted on the server
                  fetchAPI('/api/config/verbose_channels', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ enabled: next }),
                  }).catch(() => {});
                }}
                className={cn(
                  "inline-flex items-center gap-[7px] px-[10px] py-[4px] border rounded-full text-[11px] mono transition-colors",
                  showToolLogs
                    ? "border-[var(--acm-accent)] text-[var(--acm-accent)] bg-[oklch(0.84_0.16_82/0.07)]"
                    : "border-[var(--acm-border)] text-[var(--acm-fg-4)] hover:text-[var(--acm-fg)] hover:border-[var(--acm-border-strong)]"
                )}
              >
                Tool Logs
              </button>
              <button
                onClick={toggleTerminal}
                className={cn(
                  "inline-flex items-center gap-[7px] px-[10px] py-[4px] border rounded-full text-[11px] mono transition-colors",
                  isTerminalOpen
                    ? "border-[var(--acm-accent)] text-[var(--acm-accent)] bg-[oklch(0.84_0.16_82/0.07)]"
                    : "border-[var(--acm-border)] text-[var(--acm-fg-4)] hover:text-[var(--acm-fg)] hover:border-[var(--acm-border-strong)]"
                )}
              >
                <SquareTerminal size={12} />
                Terminal
              </button>
              <button className="p-1.5 text-[var(--acm-fg-4)] hover:text-[var(--acm-fg)] transition-colors">
                <MoreVertical size={16} />
              </button>
            </div>
          </div>

          {/* Messages feed */}
          <div className="flex-1 overflow-y-auto acm-scroll px-[20px] py-[16px] space-y-[16px] relative">
            {/* Floating status badges */}
            {(isRouterLearning || activeSkillNames.length > 0 || memoryRecall) && (
              <div className="sticky top-2 z-10 flex justify-end gap-2 pointer-events-none">
                {memoryRecall && <MemoryRecallIndicator status={memoryRecall.status} count={memoryRecall.count} />}
                {isRouterLearning && <RouterLearningIndicator />}
                {activeSkillNames.length > 0 && <SkillActiveIndicator names={activeSkillNames} />}
              </div>
            )}

            {messages.length === 0 ? (
              <div className="flex flex-col items-center justify-center h-full text-center">
                {isLoadingHistory ? (
                  <>
                    <Loader2 size={28} className="text-[var(--acm-accent)] animate-spin mb-4" />
                    <p className="mono text-[11px] text-[var(--acm-fg-4)]">Loading conversation...</p>
                  </>
                ) : (
                  <>
                    <div className="w-14 h-14 border border-[var(--acm-border)] bg-[var(--acm-card)] rounded-[10px] flex items-center justify-center mb-5 text-[var(--acm-accent)]">
                      <Plus size={24} />
                    </div>
                    <div className="mb-2 flex items-center gap-2">
                      <span className="mono text-[10px] px-[10px] py-[4px] border border-[oklch(0.84_0.16_82/0.3)] bg-[oklch(0.84_0.16_82/0.07)] text-[var(--acm-accent)] rounded-full">
                        New conversation
                      </span>
                    </div>
                    <h3 className="text-[14px] font-semibold text-[var(--acm-fg-2)] mb-2">
                      Ready to start
                    </h3>
                    <p className="mono text-[11px] text-[var(--acm-fg-4)] max-w-xs">
                      This is a fresh conversation. Type your first message below.
                    </p>
                  </>
                )}
              </div>
            ) : (
              messages
                .filter((msg) => msg.reasoning || msg.compactionNote || showToolLogs || (!msg.toolCall && !msg.validation && !msg.toolConfirmation))
                .map((msg) => {
                  if (msg.reasoning) {
                    return <ReasoningBubble key={msg.id} content={msg.reasoning} streaming={msg.reasoningStreaming} />;
                  }
                  if (msg.validation) {
                    return (
                      <ValidationBubble
                        key={msg.id}
                        tool={msg.validation.tool}
                        steps={msg.validation.steps}
                        done={msg.validation.done}
                        passed={msg.validation.passed}
                      />
                    );
                  }
                  if (msg.toolConfirmation) {
                    return (
                      <ToolConfirmationBubble
                        key={msg.id}
                        confirmId={msg.toolConfirmation.confirmId}
                        tool={msg.toolConfirmation.tool}
                        command={msg.toolConfirmation.command}
                      />
                    );
                  }
                  if (msg.compactionNote) {
                    return (
                      <CompactionNoteBubble
                        key={msg.id}
                        summarizedMessages={msg.compactionNote.summarizedMessages}
                      />
                    );
                  }
                  return (
                    <MessageBubble
                      key={msg.id}
                      content={msg.content}
                      role={msg.role}
                      badge={msg.badge}
                      attachments={msg.attachments}
                      toolCall={msg.toolCall}
                      usage={msg.usage}
                      debugMode={debugMode}
                    />
                  );
                })
            )}

            {isWaitingResponse && <TypingIndicator label={thinkingLabel} />}
            <div ref={messagesEndRef} />
          </div>

          {/* Quick command strip */}
          <div className="px-[16px] py-[8px] border-t border-[var(--acm-border)] bg-[var(--acm-base)] flex items-center gap-[6px] flex-wrap">
            <button
              onClick={startNewConversation}
              className="inline-flex items-center gap-[5px] px-[10px] py-[4px] rounded-full border border-[var(--acm-border)] mono text-[11px] text-[var(--acm-fg-4)] hover:text-[var(--acm-fg)] hover:border-[var(--acm-border-strong)] transition-colors"
            >
              <Plus size={11} />
              New
            </button>
            <button
              onClick={() => executeCommand('/help')}
              className="inline-flex items-center gap-[5px] px-[10px] py-[4px] rounded-full border border-[var(--acm-border)] mono text-[11px] text-[var(--acm-fg-4)] hover:text-[var(--acm-fg)] hover:border-[var(--acm-border-strong)] transition-colors"
            >
              <HelpCircle size={11} />
              Help
            </button>
            <button
              onClick={() => executeCommand('/model')}
              className="inline-flex items-center gap-[5px] px-[10px] py-[4px] rounded-full border border-[var(--acm-border)] mono text-[11px] text-[var(--acm-fg-4)] hover:text-[var(--acm-fg)] hover:border-[var(--acm-border-strong)] transition-colors"
            >
              <Cpu size={11} />
              {modelData?.model ? `Model: ${modelData.model}` : 'Model'}
            </button>
            <button
              onClick={() => executeCommand('/stats')}
              className="inline-flex items-center gap-[5px] px-[10px] py-[4px] rounded-full border border-[var(--acm-border)] mono text-[11px] text-[var(--acm-fg-4)] hover:text-[var(--acm-fg)] hover:border-[var(--acm-border-strong)] transition-colors"
            >
              <BarChart3 size={11} />
              Stats
            </button>
            <button
              onClick={() => executeCommand('/export')}
              className="inline-flex items-center gap-[5px] px-[10px] py-[4px] rounded-full border border-[var(--acm-border)] mono text-[11px] text-[var(--acm-fg-4)] hover:text-[var(--acm-fg)] hover:border-[var(--acm-border-strong)] transition-colors"
            >
              <Download size={11} />
              Export
            </button>
            <button
              onClick={() => { addMessage({ content: '/compact', role: 'user' }); executeCommand('/compact'); }}
              disabled={isCompacting}
              className="inline-flex items-center gap-[5px] px-[10px] py-[4px] rounded-full border border-[var(--acm-border)] mono text-[11px] text-[var(--acm-fg-4)] hover:text-[var(--acm-accent)] hover:border-[oklch(0.84_0.16_82/0.4)] transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              title="Summarize old messages to free up context window"
            >
              {isCompacting ? <Loader2 size={11} className="animate-spin" /> : <ScrollText size={11} />}
              {isCompacting ? 'Compacting…' : 'Compact'}
            </button>
            <ContextBadge
              pct={ctxStats?.pct_used ?? null}
              tokens={ctxStats?.estimated_tokens ?? 0}
              window={ctxStats?.context_window ?? 128000}
            />
          </div>

          {/* Terminal Panel */}
          <TerminalPanel />

          {/* Composer */}
          <div className="border-t border-[var(--acm-border)] px-[24px] pt-[14px] pb-[18px] bg-[var(--acm-base)]">
            {/* Attachment previews */}
            {currentAttachments.length > 0 && (
              <div className="flex flex-wrap gap-2 mb-3">
                {currentAttachments.map((att) => (
                  <div
                    key={att.id}
                    className="relative flex items-center gap-2 bg-[var(--acm-card)] border border-[var(--acm-border)] rounded-[6px] overflow-hidden text-[12px] text-[var(--acm-fg-3)]"
                  >
                    {att.previewUrl ? (
                      <div className="relative">
                        {/* eslint-disable-next-line @next/next/no-img-element */}
                        <img src={att.previewUrl} alt={att.name} className="h-14 w-14 object-cover" />
                      </div>
                    ) : (
                      <div className="flex items-center gap-2 px-3 py-1.5">
                        {att.type.startsWith('audio/') ? <Music size={13} className="text-[var(--acm-accent)]" /> : <FileText size={13} className="text-[var(--acm-fg-3)]" />}
                        <span className="mono truncate max-w-[120px] text-[11px]">{att.name}</span>
                      </div>
                    )}
                    <button
                      onClick={() => removeAttachment(att.id)}
                      className="absolute top-0.5 right-0.5 bg-[var(--acm-base)]/80 rounded-full p-0.5 text-[var(--acm-fg-4)] hover:text-[var(--acm-err)] transition-colors"
                    >
                      <X size={11} />
                    </button>
                  </div>
                ))}
              </div>
            )}

            {/* Input card */}
            <div className="border border-[var(--acm-border)] rounded-[8px] bg-[var(--acm-card)] px-[12px] pt-[8px] pb-[10px]">
              {/* Prompt prefix row + textarea */}
              <div className="flex items-start gap-[8px]">
                <span className="mono text-[12px] text-[var(--acm-accent)] pt-[10px] select-none flex-shrink-0">›</span>
                <textarea
                  value={inputValue}
                  onChange={(e) => setInputValue(e.target.value)}
                  onKeyDown={handleKeyDown}
                  onPaste={handlePaste}
                  placeholder="Type a message, or paste an image..."
                  rows={1}
                  className="flex-1 bg-transparent text-[var(--acm-fg)] placeholder-[var(--acm-fg-4)] resize-none focus:outline-none text-[13.5px] leading-relaxed pt-[8px]"
                  style={{ minHeight: '38px', maxHeight: '120px' }}
                />
              </div>

              {/* Toolbar */}
              <div className="flex items-center gap-[4px] mt-[6px] pt-[6px] border-t border-[var(--acm-border)]">
                {/* Attach */}
                <button
                  onClick={() => fileInputRef.current?.click()}
                  disabled={isUploading}
                  className="flex items-center gap-[4px] px-[8px] py-[4px] rounded-[4px] text-[var(--acm-fg-3)] hover:text-[var(--acm-fg)] text-[11.5px] transition-colors disabled:opacity-50"
                  title="Attach file (image, PDF, audio, text...)"
                >
                  {isUploading ? <Loader2 size={13} className="animate-spin" /> : <Paperclip size={13} />}
                  <span className="mono">Attach</span>
                </button>
                <input
                  ref={fileInputRef}
                  type="file"
                  multiple
                  accept="image/*,audio/*,.pdf,.txt,.md,.csv,.json,.yaml,.yml,.xml,.html,.log"
                  className="hidden"
                  onChange={handleFileSelect}
                />

                {/* Voice */}
                <button
                  onClick={handleMicClick}
                  disabled={isUploading}
                  className={cn(
                    "flex items-center gap-[4px] px-[8px] py-[4px] rounded-[4px] text-[11.5px] transition-colors disabled:opacity-50 mono",
                    isRecording
                      ? "text-[var(--acm-err)] acm-pulse"
                      : "text-[var(--acm-fg-3)] hover:text-[var(--acm-fg)]"
                  )}
                  title={isRecording ? "Stop recording" : "Record voice message"}
                >
                  {isRecording ? <MicOff size={13} /> : <Mic size={13} />}
                  <span>{isRecording ? 'Stop' : 'Voice'}</span>
                </button>

                <div className="flex-1" />

                {/* Send / Cancel */}
                {isWaitingResponse ? (
                  <button
                    onClick={() => cancelMessage?.()}
                    className="btn-secondary !py-[5px] !px-[12px] !text-[12px] border-[var(--acm-err)] text-[var(--acm-err)] hover:border-[var(--acm-err)] hover:text-[var(--acm-err)]"
                    title="Cancel"
                  >
                    <X size={12} />
                    Cancel
                  </button>
                ) : (
                  <button
                    onClick={handleSend}
                    disabled={(!inputValue.trim() && currentAttachments.length === 0) || isUploading}
                    className="btn-primary !py-[5px] !px-[12px] !text-[12px]"
                  >
                    <Send size={12} />
                    Send
                  </button>
                )}
              </div>
            </div>

            <p className="mono text-[10px] text-[var(--acm-fg-4)] mt-[8px] text-center">
              Enter to send · Shift+Enter new line · Paste images directly
              <span className="mx-2 text-[var(--acm-border-strong)]">·</span>
              <span>All data stays local</span>
            </p>
          </div>
        </div>
      </div>
      {/* Tool confirmation modal (yolo mode safety gate) */}
      {activeConfirmation && (
        <ToolConfirmationModal
          key={activeConfirmation.confirmId}
          confirmId={activeConfirmation.confirmId}
          tool={activeConfirmation.tool}
          command={activeConfirmation.command}
          onClose={() => setActiveConfirmation(null)}
        />
      )}
    </AppLayout>
  );
}
