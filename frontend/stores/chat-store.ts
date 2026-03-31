import { create } from 'zustand';

interface Message {
  id: string;
  content: string;
  role: 'user' | 'assistant' | 'error' | 'system';
  timestamp: Date;
  attachments?: Attachment[];
  badge?: string;
  toolCall?: {
    tool: string;
    arguments: string;
    result?: string;
    status: 'running' | 'completed' | 'error';
  };
}

interface Attachment {
  id: string;
  name: string;
  type: string;
  previewUrl?: string;  // blob URL for local image preview
}

interface ChatTarget {
  channel: string;
  user: string;
  title: string;
}

interface ChatState {
  messages: Message[];
  currentTarget: ChatTarget;
  isWaitingResponse: boolean;
  thinkingLabel: string | null;
  currentAttachments: Attachment[];
  showToolLogs: boolean;
  ws: WebSocket | null;
  wsConnected: boolean;
  isRouterLearning: boolean;
  activeSkillNames: string[];

  addMessage: (message: Omit<Message, 'id' | 'timestamp'>) => void;
  setMessages: (messages: Array<Omit<Message, 'id' | 'timestamp'>>) => void;
  clearMessages: () => void;
  setTarget: (target: ChatTarget) => void;
  setWaitingResponse: (waiting: boolean) => void;
  setThinkingLabel: (label: string | null) => void;
  addAttachment: (attachment: Attachment) => void;
  removeAttachment: (id: string) => void;
  clearAttachments: () => void;
  setShowToolLogs: (show: boolean) => void;
  setWs: (ws: WebSocket | null) => void;
  setWsConnected: (connected: boolean) => void;
  setRouterLearning: (learning: boolean) => void;
  setActiveSkillNames: (names: string[]) => void;
}

export const useChatStore = create<ChatState>((set, get) => ({
  messages: [],
  currentTarget: { channel: 'web', user: 'web', title: 'Web Local' },
  isWaitingResponse: false,
  thinkingLabel: null,
  currentAttachments: [],
  showToolLogs: true,
  ws: null,
  wsConnected: false,
  isRouterLearning: false,
  activeSkillNames: [],

  addMessage: (message) => {
    const newMessage: Message = {
      ...message,
      id: `${Date.now()}-${Math.random().toString(36).substr(2, 9)}`,
      timestamp: new Date(),
    };
    set((state) => ({ messages: [...state.messages, newMessage] }));
  },

  setMessages: (messages) => {
    const now = Date.now();
    const stamped = messages.map((m, i) => ({
      ...m,
      id: `${now}-${i}-${Math.random().toString(36).substr(2, 9)}`,
      timestamp: new Date(),
    }));
    set({ messages: stamped });
  },

  clearMessages: () => set({ messages: [] }),

  setTarget: (target) => {
    const current = get().currentTarget;
    // Same conversation — don't clear messages
    if (current.channel === target.channel && current.user === target.user) {
      set({ currentTarget: target });
      return;
    }
    set({ currentTarget: target, messages: [] });
  },
  
  setWaitingResponse: (waiting) => set({ isWaitingResponse: waiting }),
  setThinkingLabel: (label) => set({ thinkingLabel: label }),
  
  addAttachment: (attachment) => 
    set((state) => ({ currentAttachments: [...state.currentAttachments, attachment] })),
  
  removeAttachment: (id) =>
    set((state) => ({ 
      currentAttachments: state.currentAttachments.filter(a => a.id !== id) 
    })),
  
  clearAttachments: () => set({ currentAttachments: [] }),
  
  setShowToolLogs: (show) => set({ showToolLogs: show }),
  
  setWs: (ws) => set({ ws }),
  
  setWsConnected: (connected) => set({ wsConnected: connected }),
  setRouterLearning: (learning) => set({ isRouterLearning: learning }),
  setActiveSkillNames: (names) => set({ activeSkillNames: names }),
}));
