import { create } from 'zustand';

export interface ValidationStep {
  step: string;
  status: 'running' | 'passed' | 'failed' | 'warning';
  detail: string;
}

export interface MessageUsage {
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  cost: number;
  requests: number;
  model: string;
}

interface Message {
  id: string;
  content: string;
  role: 'user' | 'assistant' | 'error' | 'system';
  timestamp: Date;
  attachments?: Attachment[];
  badge?: string;
  usage?: MessageUsage;
  toolCall?: {
    tool: string;
    arguments: string;
    result?: string;
    status: 'running' | 'completed' | 'error';
  };
  // Live validation progress (tool/skill creation)
  validation?: {
    tool: string;
    steps: ValidationStep[];
    done: boolean;
    passed: boolean;
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
  memoryRecall: { status: 'searching' | 'found' | 'empty' | 'saving' | 'saved'; count: number } | null;

  addMessage: (message: Omit<Message, 'id' | 'timestamp'>) => void;
  setMessages: (messages: Array<Omit<Message, 'id' | 'timestamp'>>) => void;
  upsertValidationStep: (tool: string, step: ValidationStep, done?: boolean, passed?: boolean) => void;
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
  setMemoryRecall: (state: { status: 'searching' | 'found' | 'empty' | 'saving' | 'saved'; count: number } | null) => void;
  // Stable sendMessage/cancelMessage functions injected by the global WS hook
  sendMessageFn: ((msg: string, attachments?: string[]) => boolean) | null;
  setSendMessageFn: (fn: ((msg: string, attachments?: string[]) => boolean) | null) => void;
  cancelMessageFn: (() => void) | null;
  setCancelMessageFn: (fn: (() => void) | null) => void;
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
  memoryRecall: null,
  sendMessageFn: null,
  cancelMessageFn: null,

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

  upsertValidationStep: (tool, step, done = false, passed = false) => {
    set((state) => {
      // Find the existing validation message for this tool, if any
      const idx = state.messages.findLastIndex(
        (m) => m.validation?.tool === tool
      );

      if (idx === -1) {
        // Create a new validation message
        const newMsg: Message = {
          id: `validation-${tool}-${Date.now()}`,
          content: '',
          role: 'system',
          timestamp: new Date(),
          validation: { tool, steps: [step], done, passed },
        };
        return { messages: [...state.messages, newMsg] };
      }

      // Update existing validation message
      const updated = [...state.messages];
      const existing = updated[idx];
      const steps = existing.validation!.steps.filter((s) => s.step !== step.step);
      updated[idx] = {
        ...existing,
        validation: {
          tool,
          steps: [...steps, step],
          done,
          passed,
        },
      };
      return { messages: updated };
    });
  },

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
  setMemoryRecall: (state) => set({ memoryRecall: state }),
  setSendMessageFn: (fn) => set({ sendMessageFn: fn }),
  setCancelMessageFn: (fn) => set({ cancelMessageFn: fn }),
}));
