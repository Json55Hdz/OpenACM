'use client';

import { useEffect, useRef, useState } from 'react';
import { AppLayout } from '@/components/layout/app-layout';
import { useChatStore } from '@/stores/chat-store';
import { useWebSocket } from '@/hooks/use-websocket';
import { useConversations, useConversationHistory } from '@/hooks/use-api';
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
  Wrench
} from 'lucide-react';
import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';
import { toast } from 'sonner';

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
  attachments?: Array<{ name: string; type: string }>;
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
            <div className="mt-2 space-y-1">
              {attachments.map((att, idx) => (
                <div key={idx} className="flex items-center gap-2 text-xs bg-slate-700/50 px-2 py-1 rounded">
                  <Paperclip size={12} />
                  <span className="truncate">{att.name}</span>
                </div>
              ))}
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
  } = useChatStore();

  const { sendMessage } = useWebSocket();
  const { data: conversations } = useConversations();
  const { data: history, isFetching: isLoadingHistory } = useConversationHistory(currentTarget.channel, currentTarget.user);

  const [inputValue, setInputValue] = useState('');
  const [isSidebarOpen, setIsSidebarOpen] = useState(true);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
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
        setMessages(
          history.map((msg: { role: string; content: string }) => ({
            content: msg.content,
            role: msg.role as 'user' | 'assistant' | 'error',
          }))
        );
      }
      // If history is empty, messages were already cleared by setTarget
    }
  }, [history, currentTarget.channel, currentTarget.user, setMessages]);
  
  // Auto-scroll to bottom
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isWaitingResponse]);
  
  const handleSend = () => {
    if (!inputValue.trim() && currentAttachments.length === 0) return;
    
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
  
  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (!files) return;
    
    Array.from(files).forEach(file => {
      const attachment = {
        id: `file-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`,
        name: file.name,
        type: file.type,
      };
      addAttachment(attachment);
    });
    
    // Reset input
    e.target.value = '';
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
              <button className="p-2 text-slate-400 hover:text-white">
                <MoreVertical size={20} />
              </button>
            </div>
          </div>
          
          {/* Messages Area */}
          <div className="flex-1 overflow-y-auto p-4 space-y-4">
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
          
          {/* Input Area */}
          <div className="p-4 border-t border-slate-800 bg-slate-900/50">
            {/* Attachments */}
            {currentAttachments.length > 0 && (
              <div className="flex flex-wrap gap-2 mb-3">
                {currentAttachments.map((att) => (
                  <div 
                    key={att.id}
                    className="flex items-center gap-2 px-3 py-1.5 bg-slate-800 rounded-lg text-sm text-slate-300"
                  >
                    <Paperclip size={14} />
                    <span className="truncate max-w-[150px]">{att.name}</span>
                    <button
                      onClick={() => removeAttachment(att.id)}
                      className="text-slate-500 hover:text-red-400"
                    >
                      <X size={14} />
                    </button>
                  </div>
                ))}
              </div>
            )}
            
            <div className="flex items-end gap-2">
              <button
                onClick={() => fileInputRef.current?.click()}
                className="p-3 text-slate-400 hover:text-white hover:bg-slate-800 rounded-lg transition-colors"
              >
                <Paperclip size={20} />
              </button>
              <input
                ref={fileInputRef}
                type="file"
                multiple
                className="hidden"
                onChange={handleFileSelect}
              />
              
              <div className="flex-1 relative">
                <textarea
                  value={inputValue}
                  onChange={(e) => setInputValue(e.target.value)}
                  onKeyDown={handleKeyDown}
                  placeholder="Type a message..."
                  rows={1}
                  className="w-full px-4 py-3 bg-slate-800 border border-slate-700 rounded-lg text-white placeholder-slate-500 resize-none focus:outline-none focus:border-blue-500"
                  style={{ minHeight: '48px', maxHeight: '120px' }}
                />
              </div>
              
              <button
                onClick={handleSend}
                disabled={(!inputValue.trim() && currentAttachments.length === 0) || isWaitingResponse}
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
              Press Enter to send, Shift + Enter for a new line
            </p>
          </div>
        </div>
      </div>
    </AppLayout>
  );
}
