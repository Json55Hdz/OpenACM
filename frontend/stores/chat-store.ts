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
  // Inline tool confirmation request
  toolConfirmation?: {
    confirmId: string;
    tool: string;
    command: string;
  };
  // Conversation compaction note
  compactionNote?: {
    summary: string;
    summarizedMessages: number;
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
  // Per-conversation caches: key = "channel:userId"
  savedMessages: Record<string, Message[]>;
  savedWaiting: Record<string, boolean>;
  savedThinkingLabel: Record<string, string | null>;
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

  // forKey: if provided and different from currentTarget, add to savedMessages instead
  addMessage: (message: Omit<Message, 'id' | 'timestamp'>, forKey?: string) => void;
  setMessages: (messages: Array<Omit<Message, 'id' | 'timestamp'>>) => void;
  // Update the most recent running tool call message for the given tool in-place
  updateToolCall: (tool: string, result: string, status: 'completed' | 'error') => void;
  upsertValidationStep: (tool: string, step: ValidationStep, done?: boolean, passed?: boolean) => void;
  clearMessages: () => void;
  setTarget: (target: ChatTarget) => void;
  setWaitingResponse: (waiting: boolean) => void;
  setThinkingLabel: (label: string | null) => void;
  // Reset waiting state — forKey resets a background conversation instead of current
  resetWaiting: (forKey?: string) => void;
  addAttachment: (attachment: Attachment) => void;
  removeAttachment: (id: string) => void;
  clearAttachments: () => void;
  setShowToolLogs: (show: boolean) => void;
  setWs: (ws: WebSocket | null) => void;
  setWsConnected: (connected: boolean) => void;
  setRouterLearning: (learning: boolean) => void;
  setActiveSkillNames: (names: string[]) => void;
  setMemoryRecall: (state: { status: 'searching' | 'found' | 'empty' | 'saving' | 'saved'; count: number } | null) => void;
  // Pending onboarding greeting — set by WS handler, consumed by /chat page
  pendingOnboardingGreeting: string | null;
  setPendingOnboardingGreeting: (content: string | null) => void;
  // Stable sendMessage/cancelMessage functions injected by the global WS hook
  sendMessageFn: ((msg: string, attachments?: string[]) => boolean) | null;
  setSendMessageFn: (fn: ((msg: string, attachments?: string[]) => boolean) | null) => void;
  cancelMessageFn: (() => void) | null;
  setCancelMessageFn: (fn: (() => void) | null) => void;
}

export const useChatStore = create<ChatState>((set, get) => ({
  messages: [],
  savedMessages: {},
  savedWaiting: {},
  savedThinkingLabel: {},
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
  pendingOnboardingGreeting: null,
  sendMessageFn: null,
  cancelMessageFn: null,

  addMessage: (message, forKey) => {
    const state = get();
    const currentKey = `${state.currentTarget.channel}:${state.currentTarget.user}`;
    const targetKey = forKey ?? currentKey;

    const newMessage: Message = {
      ...message,
      id: `${Date.now()}-${Math.random().toString(36).substr(2, 9)}`,
      timestamp: new Date(),
    };

    if (targetKey === currentKey) {
      set((s) => ({ messages: [...s.messages, newMessage] }));
    } else {
      // Response arrived for a different conversation — store it there
      set((s) => ({
        savedMessages: {
          ...s.savedMessages,
          [targetKey]: [...(s.savedMessages[targetKey] ?? []), newMessage],
        },
      }));
    }
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

  updateToolCall: (tool, result, status) => {
    set((state) => {
      const idx = [...state.messages].findLastIndex(
        (m) => m.toolCall?.tool === tool && m.toolCall.status === 'running',
      );
      if (idx === -1) return state; // no matching running call found, ignore
      const updated = [...state.messages];
      updated[idx] = {
        ...updated[idx],
        toolCall: { ...updated[idx].toolCall!, result, status },
      };
      return { messages: updated };
    });
  },

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
    const state = get();
    const oldKey = `${state.currentTarget.channel}:${state.currentTarget.user}`;
    const newKey = `${target.channel}:${target.user}`;

    // Same conversation — just update title etc., no save/restore
    if (oldKey === newKey) {
      set({ currentTarget: target });
      return;
    }

    // Save current state under the old key, restore saved state for new key
    const savedMessages = { ...state.savedMessages, [oldKey]: state.messages };
    const savedWaiting = { ...state.savedWaiting, [oldKey]: state.isWaitingResponse };
    const savedThinkingLabel = { ...state.savedThinkingLabel, [oldKey]: state.thinkingLabel };

    set({
      currentTarget: target,
      messages: savedMessages[newKey] ?? [],
      savedMessages,
      isWaitingResponse: savedWaiting[newKey] ?? false,
      thinkingLabel: savedThinkingLabel[newKey] ?? null,
      savedWaiting,
      savedThinkingLabel,
    });
  },

  setWaitingResponse: (waiting) => set({ isWaitingResponse: waiting }),
  setThinkingLabel: (label) => set({ thinkingLabel: label }),

  resetWaiting: (forKey) => {
    const state = get();
    const currentKey = `${state.currentTarget.channel}:${state.currentTarget.user}`;
    if (!forKey || forKey === currentKey) {
      set({ isWaitingResponse: false, thinkingLabel: null });
    } else {
      set((s) => ({
        savedWaiting: { ...s.savedWaiting, [forKey]: false },
        savedThinkingLabel: { ...s.savedThinkingLabel, [forKey]: null },
      }));
    }
  },

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
  setPendingOnboardingGreeting: (content) => set({ pendingOnboardingGreeting: content }),
  setSendMessageFn: (fn) => set({ sendMessageFn: fn }),
  setCancelMessageFn: (fn) => set({ cancelMessageFn: fn }),
}));
