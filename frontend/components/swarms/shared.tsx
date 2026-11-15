

// ─── Types ────────────────────────────────────────────────────────────────────

export interface Swarm {
  id: number;
  name: string;
  goal: string;
  status: 'draft' | 'clarifying' | 'planning' | 'planned' | 'running' | 'paused' | 'idle' | 'completed' | 'failed';
  global_model: string | null;
  worker_count: number;
  task_count: number;
  created_at: string;
}

export interface Worker {
  id: number;
  swarm_id: number;
  name: string;
  role: string;
  description: string;
  system_prompt: string;
  model: string | null;
  allowed_tools: string;
  status: 'idle' | 'busy' | 'done' | 'failed';
  workspace_path: string;
}

export interface Task {
  id: number;
  worker_id: number | null;
  worker_name: string | null;
  title: string;
  description: string;
  depends_on: string;
  status: 'pending' | 'running' | 'completed' | 'failed' | 'waiting';
  result: string | null;
}

export interface SwarmMessage {
  id: number;
  from_worker_name: string | null;
  to_worker_name: string | null;
  message_type: string;
  content: string;
  created_at: string;
}

export interface SwarmDetailData extends Swarm {
  shared_context: string;
  context_files: string;
  clarification_questions: string;
  clarification_answers: string;
  workers: Worker[];
  tasks: Task[];
}

export interface LiveEvent {
  type: string;
  ts: number;
  // task events
  task_id?: number;
  task_title?: string;
  worker_name?: string;
  reason?: string;
  // worker_progress
  channel_id?: string;
  iteration?: number;
  tools_called?: string[];
  // worker_thought — actual LLM text
  content?: string;
  pct_used?: number;
  // misc
  [key: string]: unknown;
}

// ─── Status helpers ───────────────────────────────────────────────────────────

export const WORKER_DOT: Record<string, string> = {
  idle:   'dot-idle',
  busy:   'dot-accent acm-pulse',
  done:   'dot-ok',
  failed: 'dot-err',
};

export const SWARM_DOT: Record<string, string> = {
  running:    'dot-accent acm-pulse',
  completed:  'dot-ok',
  failed:     'dot-err',
  paused:     'dot-warn',
  draft:      'dot-idle',
  clarifying: 'dot-warn acm-pulse',
  planning:   'dot-accent acm-pulse',
  planned:    'dot-warn',
  idle:       'dot-idle',
};

export const TASK_DOT: Record<string, string> = {
  pending:   'dot-idle',
  running:   'dot-accent acm-pulse',
  completed: 'dot-ok',
  failed:    'dot-err',
  waiting:   'dot-warn',
};

// ─── Create Swarm Modal ───────────────────────────────────────────────────────
