# Multi-Agent Swarms

OpenACM includes a full multi-agent swarm system that lets you launch a coordinated team of specialist AI workers to tackle complex, multi-step projects — all running in parallel, each with its own isolated workspace and optional model override.

---

## Overview

A **swarm** is a self-organizing team of AI agents (workers) that:

- Is planned automatically by an orchestrator agent from a plain-language goal
- Runs all tasks in parallel (up to 3 simultaneous workers by default)
- Communicates peer-to-peer via built-in swarm tools
- Has a fully isolated workspace separate from normal chat workspaces
- Emits granular events on every state change for real-time UI updates
- Produces a final synthesis summary once all tasks are complete

Typical use cases:

- Building a software project (researcher + architect + developer + reviewer)
- Analyzing a corpus of documents simultaneously
- Generating multi-section reports with parallel writers
- Research pipelines with fact-checkers and summarizers

---

## Creating a Swarm

### From the Chat (Brain)

Ask the Brain in natural language:

> "Create a swarm to build a REST API for a todo app with auth"

The Brain calls the `create_swarm` tool, which plans the team and tasks automatically. You can also say:

> "Start it immediately" → sets `auto_start: true`

### From the Dashboard

1. Go to **Swarms** in the sidebar
2. Click **New Swarm**
3. Fill in:
   - **Goal** — detailed description of what the team should accomplish
   - **Name** — optional display name
   - **Global Model** — LiteLLM model string applied to all workers (e.g. `anthropic/claude-opus-4-6`)
   - **Context Files** — drag and drop any files the team needs to understand the project
4. Click **Create** — planning happens automatically

---

## Planning

When a swarm is created, an orchestrator LLM call:

1. Designs a team of 3–6 specialist workers with names, roles, and descriptions
2. Assigns a task to each worker with a title, description, and dependencies
3. Stores workers and tasks in the database with status `planned`

The result is visible in the Workers and Tasks tabs before execution starts.

---

## Execution

Clicking **Start** (or `auto_start: true`) triggers `_run_swarm`:

1. Tasks with no unmet dependencies are collected as "ready"
2. All ready tasks fire **in parallel** (throttled to 3 concurrent workers via `asyncio.Semaphore`)
3. Each worker gets its own `Brain` instance with:
   - An isolated workspace at `workspace/swarms/{id}/workers/{name}/`
   - Its own model override (worker-specific > swarm global > system default)
   - Swarm communication tools injected into its tool registry
4. Task results are saved to `swarm_tasks.result` and to the Activity Feed
5. Completed task titles unlock dependent tasks in the next round
6. Rounds continue until no pending tasks remain
7. A final synthesis is produced by the orchestrator and saved as a `synthesis` activity entry

### Parallel Execution

Workers truly run concurrently via `asyncio.gather`. The semaphore prevents SQLite lock contention by limiting simultaneous DB writes to 3 at a time. Increase `MAX_PARALLEL` in `swarm_manager.py` if using PostgreSQL or a more concurrent backend.

---

## Per-Worker Model Selection

Each worker can use a different LLM:

- Set a **Global Model** at swarm creation time → all workers use it
- In the Workers tab, click the pencil icon on any worker card → type a LiteLLM model string → Save
- Per-worker model overrides the global model

Model strings follow LiteLLM format: `provider/model-name`, e.g.:
- `anthropic/claude-opus-4-6`
- `openai/gpt-4o`
- `groq/llama-3.3-70b-versatile`
- `ollama/qwen2.5:32b`

---

## Workspace Isolation

Each swarm worker writes to its own directory:

```
workspace/
  swarms/
    {swarm_id}/
      workers/
        {worker_name}/
          task_{task_id}_result.md
          ... (any files the worker creates)
```

This is completely separate from normal chat workspaces (`workspace/`). Workers cannot accidentally read or overwrite each other's outputs unless they explicitly use swarm messaging to share content.

---

## Worker Communication

Workers can communicate peer-to-peer using three injected tools:

### `swarm_send_message`
Send a direct message to a specific teammate by name.

```
to_worker: "Reviewer"
message: "Here is my draft for review: ..."
```

### `swarm_broadcast`
Send a message visible to all workers in the swarm.

```
message: "I found a critical dependency — everyone should use lodash ^4.17"
```

### `swarm_read_messages`
Read all messages sent directly to you plus broadcasts and user feedback.

Messages are stored in `swarm_messages` and appear in the Activity Feed in real time.

### `swarm_create_task`
Create a new task dynamically — useful when a worker discovers additional work or when reacting to user feedback.

```
title: "Add rate limiting"
description: "The API endpoint needs rate limiting per the user's request"
assign_to: "BackendDev"  # optional
```

---

## Activity Feed

The **Activity** tab inside a swarm detail shows a unified chronological timeline:

| Type | Color | Description |
|------|-------|-------------|
| `task_result` | Green | Worker output when a task completes (collapsible) |
| `task_failed` | Red | Error output when a task fails |
| `synthesis` | Amber | Final orchestrator summary (collapsible) |
| `broadcast` | Violet | Worker broadcast to all teammates |
| `message` | Gray | Direct worker-to-worker message with arrow |
| `user` | Blue | Feedback you sent to the swarm |

Long outputs (task results, synthesis) are collapsed to 300 characters with a "show full output" toggle.

---

## User Feedback

You can send messages to a running (or paused) swarm from the input box at the bottom of the swarm detail page:

1. The message is stored as a `user` type entry in `swarm_messages`
2. The orchestrator worker is automatically invoked with the feedback
3. The orchestrator can call `swarm_create_task` to spawn new work
4. If new pending tasks are created and the swarm is not already running, status resets to `planned` so you can restart

Workers that call `swarm_read_messages` will see your feedback in their context on the next execution round.

---

## Swarm States

| Status | Meaning |
|--------|---------|
| `draft` | Just created, not yet planned |
| `planning` | Orchestrator is designing the team |
| `planned` | Ready to start, workers and tasks exist |
| `running` | Actively executing tasks |
| `paused` | Execution stopped (can resume with Start) |
| `completed` | All tasks done, synthesis produced |
| `failed` | Unrecoverable error during execution |

---

## API Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/swarms` | List all swarms |
| `POST` | `/api/swarms` | Create a swarm (multipart with optional files) |
| `GET` | `/api/swarms/{id}` | Get swarm detail with workers and tasks |
| `DELETE` | `/api/swarms/{id}` | Delete swarm and all data |
| `POST` | `/api/swarms/{id}/plan` | Trigger planning |
| `POST` | `/api/swarms/{id}/start` | Start or resume execution |
| `POST` | `/api/swarms/{id}/stop` | Pause execution |
| `PUT` | `/api/swarms/{id}/workers/{wid}` | Update worker (e.g. change model) |
| `GET` | `/api/swarms/{id}/messages` | Get full activity feed |
| `POST` | `/api/swarms/{id}/message` | Send user feedback to swarm |
| `WS` | `/ws/swarms/{id}` | WebSocket for real-time events |

### Create Swarm (multipart)

```
POST /api/swarms
Content-Type: multipart/form-data

name=My Swarm
goal=Build a REST API with auth and tests
global_model=anthropic/claude-opus-4-6
files[]=spec.pdf
files[]=architecture.md
```

### Send User Feedback

```
POST /api/swarms/{id}/message
Content-Type: application/json

{ "message": "Please add rate limiting to all endpoints" }
```

---

## Events

The swarm engine emits named events on every state change. All are broadcast to WebSocket clients connected to `/ws/swarms/{id}` and can also be consumed server-side via the event bus.

| Event | Trigger |
|-------|---------|
| `swarm:updated` | Swarm status changes |
| `swarm:running` | Execution started |
| `swarm:round` | New parallel execution round |
| `swarm:worker_thinking` | Worker begins a task |
| `swarm:worker_done` | Worker completes a task |
| `swarm:worker_error` | Worker task fails |
| `swarm:worker_status` | Worker status changes |
| `swarm:task_updated` | Task status changes |
| `swarm:message` | Peer-to-peer message sent |
| `swarm:task_created` | New task created dynamically |
| `swarm:user_message` | User feedback received |
| `swarm:orchestrator_reacted` | Orchestrator processed feedback |
| `swarm:synthesizing` | Final synthesis starting |
| `swarm:completed` | All tasks done |
| `swarm:failed` | Execution error |
| `swarm:paused` | Execution paused |
| `swarm:plan_ready` | Planning complete |
| `swarm:stalled` | No ready tasks, possible dependency deadlock |

---

## Database Schema

Four tables added in migration 7:

```sql
swarms          (id, name, goal, status, global_model, shared_context, context_files, ...)
swarm_workers   (id, swarm_id, name, role, description, system_prompt, model, status, workspace_path, ...)
swarm_tasks     (id, swarm_id, worker_id, title, description, depends_on, status, result, ...)
swarm_messages  (id, swarm_id, from_worker_id, to_worker_id, content, message_type, created_at)
```

`message_type` values: `user`, `message`, `broadcast`, `task_result`, `task_failed`, `synthesis`

---

## Brain Tools

The normal chat Brain has three swarm tools:

| Tool | Description |
|------|-------------|
| `create_swarm` | Create and plan a swarm from a goal description |
| `start_swarm` | Start execution of a planned/paused swarm by ID |
| `list_swarms` | List all swarms and their current status |

Example prompts:
- *"Create a swarm to write a marketing campaign for a fitness app, start it automatically"*
- *"List my swarms"*
- *"Start swarm 3"*
