'use client';

import { useEffect, useRef, useState } from 'react';
import { AppLayout } from '@/components/layout/app-layout';
import { useChatStore } from '@/stores/chat-store';
import { useWebSocket } from '@/hooks/use-websocket';
import { useAPI, useConversations, useConversationHistory, useChatCommand, useClearConversation, useCurrentModel } from '@/hooks/use-api';
import {
  Send,
  Paperclip,
  X,
  MoreVertical,
  Plus,
  Bot,
  User,
  Loader2,
  MessageSquare,
  Wrench,
  HelpCircle,
  Cpu,
  BarChart3,
  Download,
  SquareTerminal,
  RotateCcw,
  Sparkles,
  Mic,
  MicOff,
  FileText,
  Music,
} from 'lucide-react';
import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';
import { toast } from 'sonner';
import { TerminalPanel } from '@/components/terminal/terminal-panel';
import { useTerminalStore } from '@/stores/terminal-store';
import { useAuthStore } from '@/stores/auth-store';

function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

interface Conversation {
  channel_id: string;
  user_id: string;
  title: string;
  last_message: string;
  last_timestamp: string;
  message_count: number;
}

function RouterLearningIndicator() {
  return (
    <div className="flex items-center gap-1.5 px-3 py-1.5 bg-violet-950/80 border border-violet-500/40 rounded-full text-violet-300 text-xs font-medium shadow-lg backdrop-blur-sm animate-pulse">
      <Sparkles size={12} className="text-violet-400" />
      <span>Aprendiendo...</span>
    </div>
  );
}

function SkillActiveIndicator({ names }: { names: string[] }) {
  const label = names
    .map((n) => n.replace(/-/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase()))
    .join(', ');
  return (
    <div className="flex items-center gap-1.5 px-3 py-1.5 bg-emerald-950/80 border border-emerald-500/40 rounded-full text-emerald-300 text-xs font-medium shadow-lg backdrop-blur-sm">
      <span className="relative flex h-2 w-2">
        <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
        <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500" />
      </span>
      <span>Skill: {label}</span>
    </div>
  );
}

function TypingIndicator() {
  return (
    <div className="flex items-center gap-1 px-4 py-3 bg-slate-800 rounded-2xl rounded-tl-sm w-fit">
      <div className="w-2 h-2 bg-slate-400 rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
      <div className="w-2 h-2 bg-slate-400 rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
      <div className="w-2 h-2 bg-slate-400 rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
    </div>
  );
}

function MessageBubble({
  content,
  role,
  badge,
  attachments,
  toolCall
}: {
  content: string;
  role: 'user' | 'assistant' | 'error' | 'system';
  badge?: string;
  attachments?: Array<{ id?: string; name: string; type: string }>;
  toolCall?: {
    tool: string;
    arguments: string;
    result?: string;
    status: 'running' | 'completed' | 'error';
  };
}) {
  const isUser = role === 'user';
  const isError = role === 'error';
  const isSystem = role === 'system';
  const token = useAuthStore((s) => s.token);
  
  // System/tool messages have different styling
  if (isSystem && toolCall) {
    return (
      <div className="flex gap-3">
        <div className="w-8 h-8 rounded-full flex items-center justify-center flex-shrink-0 bg-amber-600">
          <Wrench size={16} className="text-white" />
        </div>
        
        <div className="flex flex-col max-w-[85%] items-start">
          {badge && (
            <span className="text-xs text-slate-500 mb-1">{badge}</span>
          )}
          
          <div className="px-4 py-3 rounded-2xl bg-amber-900/30 text-amber-200 border border-amber-600/30 rounded-tl-sm">
            <div className="flex items-center gap-2 mb-2">
              {toolCall.status === 'running' && <Loader2 size={14} className="animate-spin" />}
              {toolCall.status === 'completed' && <span className="text-green-400">✓</span>}
              {toolCall.status === 'error' && <span className="text-red-400">✗</span>}
              <span className="font-medium">{toolCall.tool}</span>
            </div>
            
            {toolCall.arguments && (
              <div className="text-xs text-amber-300/70 mb-2">
                <span className="font-mono">{toolCall.arguments}</span>
              </div>
            )}
            
            {toolCall.result && (
              <div className="text-sm text-slate-300 border-t border-amber-600/20 pt-2 mt-2">
                {toolCall.result}
              </div>
            )}
          </div>
        </div>
      </div>
    );
  }
  
  return (
    <div className={cn(
      "flex gap-3",
      isUser ? "flex-row-reverse" : ""
    )}>
      <div className={cn(
        "w-8 h-8 rounded-full flex items-center justify-center flex-shrink-0",
        isUser ? "bg-blue-600" : isError ? "bg-red-600" : "bg-purple-600"
      )}>
        {isUser ? <User size={16} className="text-white" /> : <Bot size={16} className="text-white" />}
      </div>
      
      <div className={cn(
        "flex flex-col max-w-[75%]",
        isUser ? "items-end" : "items-start"
      )}>
        {badge && (
          <span className="text-xs text-slate-500 mb-1">{badge}</span>
        )}
        
        <div className={cn(
          "px-4 py-3 rounded-2xl",
          isUser 
            ? "bg-blue-600 text-white rounded-tr-sm" 
            : isError 
              ? "bg-red-500/20 text-red-200 border border-red-500/30 rounded-tl-sm"
              : "bg-slate-800 text-slate-200 border border-slate-700 rounded-tl-sm"
        )}>
          <p className="whitespace-pre-wrap">{content}</p>
          
          {attachments && attachments.length > 0 && (
            <div className="mt-3 space-y-2">
              {attachments.map((att, idx) => {
                const fileId = att.id || att.name;
                const isMedia = /\.(png|jpg|jpeg|gif|webp)$/i.test(att.name);
                const downloadUrl = `/api/media/${fileId}?download=true&token=${token}`;
                const previewUrl = `/api/media/${fileId}?token=${token}`;
                return (
                  <div key={idx} className="rounded-lg overflow-hidden border border-slate-600">
                    {isMedia && (
                      <img
                        src={previewUrl}
                        alt={att.name}
                        className="max-w-xs max-h-48 object-contain bg-slate-900"
                      />
                    )}
                    <div className="flex items-center gap-2 px-3 py-2 bg-slate-700/60 text-xs">
                      <Paperclip size={12} className="text-slate-400 flex-shrink-0" />
                      <span className="truncate text-slate-300 flex-1">{att.name}</span>
                      <a
                        href={downloadUrl}
                        download={att.name}
                        className="flex items-center gap-1 px-2 py-1 bg-blue-600 hover:bg-blue-500 text-white rounded transition-colors flex-shrink-0"
                      >
                        <Download size={11} />
                        Download
                      </a>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default function ChatPage() {
  const {
    messages,
    addMessage,
    setMessages,
    currentTarget,
    setTarget,
    isWaitingResponse,
    currentAttachments,
    addAttachment,
    removeAttachment,
    clearAttachments,
    showToolLogs,
    setShowToolLogs,
    isRouterLearning,
    activeSkillNames,
  } = useChatStore();

  const { sendMessage } = useWebSocket();
  const { data: conversations } = useConversations();
  const { data: history, isFetching: isLoadingHistory } = useConversationHistory(currentTarget.channel, currentTarget.user);
  const chatCommand = useChatCommand();
  const clearConversation = useClearConversation();
  const { data: modelData } = useCurrentModel();
  const { fetchAPI } = useAPI();

  const { isOpen: isTerminalOpen, toggleOpen: toggleTerminal } = useTerminalStore();

  const [inputValue, setInputValue] = useState('');
  const [isSidebarOpen, setIsSidebarOpen] = useState(true);
  const [isRestarting, setIsRestarting] = useState(false);
  const [isRecording, setIsRecording] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);
  // Track which conversation we last loaded history for
  const loadedKeyRef = useRef('');

  // Load conversation history when a new conversation is selected
  useEffect(() => {
    const key = `${currentTarget.channel}:${currentTarget.user}`;
    // Only load once per conversation switch (avoid re-running on live messages)
    if (loadedKeyRef.current === key) return;

    if (history && Array.isArray(history)) {
      loadedKeyRef.current = key;
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
  
  // Auto-scroll to bottom
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isWaitingResponse]);
  
  const handleRestart = async () => {
    setIsRestarting(true);
    try {
      await fetchAPI('/api/system/restart', { method: 'POST' });
    } catch {
      // Expected — server may close the connection before responding
    }
    // Poll /api/ping until the server is back up, then reload
    const poll = async () => {
      for (let i = 0; i < 60; i++) {
        await new Promise((r) => setTimeout(r, 1000));
        try {
          const res = await fetch('/api/ping');
          if (res.ok) {
            window.location.reload();
            return;
          }
        } catch {
          // Server still down, keep polling
        }
      }
      // Timeout after 60s — reload anyway
      window.location.reload();
    };
    poll();
  };

  const executeCommand = async (command: string) => {
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
    } catch {
      toast.error('Command failed');
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

    // Send via WebSocket
    const sent = sendMessage(inputValue, attachmentIds);

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
    // Reset history tracking so it reloads for the new conversation
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

  const startNewConversation = () => {
    loadedKeyRef.current = '';
    setTarget({
      channel: 'web',
      user: 'web',
      title: 'New Conversation',
    });
  };
  
  const conversationList: Conversation[] = conversations || [];
  
  return (
    <AppLayout>
      {/* Restarting overlay */}
      {isRestarting && (
        <div className="fixed inset-0 z-50 flex flex-col items-center justify-center bg-slate-950/95 backdrop-blur-sm">
          <Loader2 size={48} className="animate-spin text-blue-400 mb-6" />
          <h2 className="text-2xl font-bold text-white mb-2">Restarting OpenACM...</h2>
          <p className="text-slate-400">Waiting for the server to come back up</p>
        </div>
      )}
      <div className="h-screen flex">
        {/* Sidebar - Conversation List */}
        <div className={cn(
          "fixed lg:static inset-y-0 left-0 w-80 bg-slate-900 border-r border-slate-800 z-30 transition-transform duration-300",
          isSidebarOpen ? "translate-x-0" : "-translate-x-full lg:translate-x-0 lg:w-0 lg:overflow-hidden lg:border-r-0"
        )}>
          <div className="flex flex-col h-full">
            {/* Header */}
            <div className="p-4 border-b border-slate-800">
              <div className="flex items-center justify-between mb-4">
                <h2 className="text-lg font-semibold text-white">Conversations</h2>
                <button
                  onClick={() => setIsSidebarOpen(false)}
                  className="lg:hidden p-1 text-slate-400 hover:text-white"
                >
                  <X size={20} />
                </button>
              </div>
              <button
                onClick={startNewConversation}
                className="w-full flex items-center justify-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg transition-colors"
              >
                <Plus size={18} />
                <span>New Conversation</span>
              </button>
            </div>
            
            {/* Conversation List */}
            <div className="flex-1 overflow-y-auto p-2 space-y-1">
              {conversationList.map((conv) => (
                <button
                  key={`${conv.channel_id}-${conv.user_id}`}
                  onClick={() => selectConversation(conv)}
                  className={cn(
                    "w-full text-left p-3 rounded-lg transition-colors",
                    currentTarget.channel === conv.channel_id && currentTarget.user === conv.user_id
                      ? "bg-blue-600/20 border border-blue-600/30"
                      : "hover:bg-slate-800"
                  )}
                >
                  <div className="flex items-center gap-3">
                    <div className="w-10 h-10 bg-slate-800 rounded-full flex items-center justify-center">
                      <MessageSquare size={18} className="text-slate-400" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium text-slate-200 truncate">
                        {conv.title || `${conv.channel_id} - ${conv.user_id}`}
                      </p>
                      <p className="text-xs text-slate-500 truncate">
                        {conv.last_message || 'No messages'}
                      </p>
                    </div>
                    {conv.message_count > 0 && (
                      <span className="text-xs text-slate-500">{conv.message_count}</span>
                    )}
                  </div>
                </button>
              ))}
              
              {conversationList.length === 0 && (
                <div className="text-center py-8">
                  <MessageSquare size={48} className="mx-auto text-slate-600 mb-2" />
                  <p className="text-sm text-slate-500">No conversations yet</p>
                </div>
              )}
            </div>
          </div>
        </div>
        
        {/* Main Chat Area */}
        <div className="flex-1 flex flex-col min-w-0 bg-slate-950">
          {/* Chat Header */}
          <div className="flex items-center justify-between px-4 py-3 border-b border-slate-800 bg-slate-900/50">
            <div className="flex items-center gap-3">
              <button
                onClick={() => setIsSidebarOpen(true)}
                className="lg:hidden p-2 text-slate-400 hover:text-white"
              >
                <MessageSquare size={20} />
              </button>
              <div>
                <h3 className="font-semibold text-white">{currentTarget.title}</h3>
                <p className="text-xs text-slate-500">{currentTarget.channel} • {currentTarget.user}</p>
              </div>
            </div>
            
            <div className="flex items-center gap-2">
              <button
                onClick={() => setShowToolLogs(!showToolLogs)}
                className={cn(
                  "px-3 py-1.5 text-sm rounded-lg transition-colors",
                  showToolLogs
                    ? "bg-blue-600/20 text-blue-400 border border-blue-600/30"
                    : "text-slate-400 hover:bg-slate-800"
                )}
              >
                Tool Logs
              </button>
              <button
                onClick={toggleTerminal}
                className={cn(
                  "px-3 py-1.5 text-sm rounded-lg transition-colors flex items-center gap-1.5",
                  isTerminalOpen
                    ? "bg-emerald-600/20 text-emerald-400 border border-emerald-600/30"
                    : "text-slate-400 hover:bg-slate-800"
                )}
              >
                <SquareTerminal size={14} />
                Terminal
              </button>
              <button className="p-2 text-slate-400 hover:text-white">
                <MoreVertical size={20} />
              </button>
            </div>
          </div>
          
          {/* Messages Area */}
          <div className="flex-1 overflow-y-auto p-4 space-y-4 relative">
            {(isRouterLearning || activeSkillNames.length > 0) && (
              <div className="sticky top-2 z-10 flex justify-end gap-2 pointer-events-none">
                {isRouterLearning && <RouterLearningIndicator />}
                {activeSkillNames.length > 0 && <SkillActiveIndicator names={activeSkillNames} />}
              </div>
            )}
            {messages.length === 0 ? (
              <div className="flex flex-col items-center justify-center h-full text-center">
                {isLoadingHistory ? (
                  <>
                    <Loader2 size={32} className="text-slate-400 animate-spin mb-4" />
                    <p className="text-sm text-slate-500">Loading conversation...</p>
                  </>
                ) : (
                  <>
                    <div className="w-16 h-16 bg-slate-800 rounded-full flex items-center justify-center mb-4">
                      <Bot size={32} className="text-slate-400" />
                    </div>
                    <h3 className="text-lg font-medium text-slate-300 mb-2">
                      Start a conversation
                    </h3>
                    <p className="text-sm text-slate-500 max-w-md">
                      Type a message to start interacting with the AI assistant.
                    </p>
                  </>
                )}
              </div>
            ) : (
              messages
                .filter((msg) => showToolLogs || !msg.toolCall)
                .map((msg) => (
                  <MessageBubble
                    key={msg.id}
                    content={msg.content}
                    role={msg.role}
                    badge={msg.badge}
                    attachments={msg.attachments}
                    toolCall={msg.toolCall}
                  />
                ))
            )}
            
            {isWaitingResponse && <TypingIndicator />}
            <div ref={messagesEndRef} />
          </div>
          
          {/* Command Buttons */}
          <div className="px-4 py-2 border-t border-slate-800 bg-slate-900/30 flex items-center gap-2 flex-wrap">
            <button
              onClick={() => {
                executeCommand('/new');
                clearConversation.mutate({ channelId: currentTarget.channel, userId: currentTarget.user });
              }}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-full bg-slate-800 text-slate-300 hover:bg-slate-700 hover:text-white border border-slate-700 transition-colors"
            >
              <Plus size={13} />
              New
            </button>
            <button
              onClick={() => executeCommand('/help')}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-full bg-slate-800 text-slate-300 hover:bg-slate-700 hover:text-white border border-slate-700 transition-colors"
            >
              <HelpCircle size={13} />
              Help
            </button>
            <button
              onClick={() => executeCommand('/model')}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-full bg-slate-800 text-slate-300 hover:bg-slate-700 hover:text-white border border-slate-700 transition-colors"
            >
              <Cpu size={13} />
              {modelData?.model ? `Model: ${modelData.model}` : 'Model'}
            </button>
            <button
              onClick={() => executeCommand('/stats')}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-full bg-slate-800 text-slate-300 hover:bg-slate-700 hover:text-white border border-slate-700 transition-colors"
            >
              <BarChart3 size={13} />
              Stats
            </button>
            <button
              onClick={() => executeCommand('/export')}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-full bg-slate-800 text-slate-300 hover:bg-slate-700 hover:text-white border border-slate-700 transition-colors"
            >
              <Download size={13} />
              Export
            </button>
            <button
              onClick={handleRestart}
              disabled={isRestarting}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-full bg-red-900/40 text-red-400 hover:bg-red-800/50 hover:text-red-300 border border-red-700/40 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              title="Restart OpenACM — restarts the server process"
            >
              <RotateCcw size={13} />
              Restart
            </button>
          </div>

          {/* Terminal Panel */}
          <TerminalPanel />

          {/* Input Area */}
          <div className="p-4 border-t border-slate-800 bg-slate-900/50">
            {/* Attachments preview */}
            {currentAttachments.length > 0 && (
              <div className="flex flex-wrap gap-2 mb-3">
                {currentAttachments.map((att) => (
                  <div
                    key={att.id}
                    className="relative flex items-center gap-2 bg-slate-800 rounded-lg overflow-hidden text-sm text-slate-300"
                  >
                    {att.previewUrl ? (
                      // Image thumbnail
                      <div className="relative">
                        {/* eslint-disable-next-line @next/next/no-img-element */}
                        <img src={att.previewUrl} alt={att.name} className="h-16 w-16 object-cover" />
                      </div>
                    ) : (
                      <div className="flex items-center gap-2 px-3 py-1.5">
                        {att.type.startsWith('audio/') ? <Music size={14} className="text-violet-400" /> : <FileText size={14} className="text-blue-400" />}
                        <span className="truncate max-w-[120px]">{att.name}</span>
                      </div>
                    )}
                    <button
                      onClick={() => removeAttachment(att.id)}
                      className="absolute top-0.5 right-0.5 bg-slate-900/80 rounded-full p-0.5 text-slate-400 hover:text-red-400"
                    >
                      <X size={12} />
                    </button>
                  </div>
                ))}
              </div>
            )}

            <div className="flex items-end gap-2">
              {/* Attach file */}
              <button
                onClick={() => fileInputRef.current?.click()}
                disabled={isUploading}
                className="p-3 text-slate-400 hover:text-white hover:bg-slate-800 rounded-lg transition-colors disabled:opacity-50"
                title="Attach file (image, PDF, audio, text...)"
              >
                {isUploading ? <Loader2 size={20} className="animate-spin" /> : <Paperclip size={20} />}
              </button>
              <input
                ref={fileInputRef}
                type="file"
                multiple
                accept="image/*,audio/*,.pdf,.txt,.md,.csv,.json,.yaml,.yml,.xml,.html,.log"
                className="hidden"
                onChange={handleFileSelect}
              />

              {/* Mic button */}
              <button
                onClick={handleMicClick}
                disabled={isUploading}
                className={cn(
                  "p-3 rounded-lg transition-colors disabled:opacity-50",
                  isRecording
                    ? "bg-red-600 hover:bg-red-700 text-white animate-pulse"
                    : "text-slate-400 hover:text-white hover:bg-slate-800"
                )}
                title={isRecording ? "Stop recording" : "Record voice message"}
              >
                {isRecording ? <MicOff size={20} /> : <Mic size={20} />}
              </button>

              <div className="flex-1 relative">
                <textarea
                  value={inputValue}
                  onChange={(e) => setInputValue(e.target.value)}
                  onKeyDown={handleKeyDown}
                  onPaste={handlePaste}
                  placeholder="Type a message, or paste an image..."
                  rows={1}
                  className="w-full px-4 py-3 bg-slate-800 border border-slate-700 rounded-lg text-white placeholder-slate-500 resize-none focus:outline-none focus:border-blue-500"
                  style={{ minHeight: '48px', maxHeight: '120px' }}
                />
              </div>

              <button
                onClick={handleSend}
                disabled={(!inputValue.trim() && currentAttachments.length === 0) || isWaitingResponse || isUploading}
                className="p-3 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed text-white rounded-lg transition-colors"
              >
                {isWaitingResponse ? (
                  <Loader2 size={20} className="animate-spin" />
                ) : (
                  <Send size={20} />
                )}
              </button>
            </div>

            <p className="text-xs text-slate-500 mt-2 text-center">
              Enter to send · Shift+Enter new line · Paste images directly
              <span className="mx-2 text-slate-700">·</span>
              <span className="text-slate-600">All data stays local — nothing is shared with OpenACM servers</span>
            </p>
          </div>
        </div>
      </div>
    </AppLayout>
  );
}
