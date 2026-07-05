# Worker Tools & Skills Scoping — Design Spec

## Context

This is sub-project 1 of a larger initiative to give OpenACM's swarm workers ("subagents") much finer per-worker configuration — eventually a full node-based visual builder (custom tools, chained mini-steps, import/export, a full-screen editor). That bigger piece is deliberately out of scope here and will get its own design after this ships.

This spec covers only: letting the user pick exactly which tools and which skills (system + private/custom) a given swarm worker uses, editable any time after the worker exists — not just at swarm-creation time.

**"Subagent" = one worker.** Not a whole swarm. A swarm can have multiple workers; each worker gets its own independent tool/skill configuration.

## Current state (what already exists)

- `swarm_workers.allowed_tools` (TEXT) already exists and is already respected at execution time (`swarm_manager.py:1453-1492`): `"all"`, `"none"`, or a JSON array of tool names. Set today only by the LLM that plans a new swarm — no UI to edit it after creation.
- `PUT /api/swarms/{swarm_id}/workers/{worker_id}` (`swarms.py:358`) already accepts `allowed_tools` as an updatable field. **No backend change needed for tool selection** — only a UI to drive it.
- `skills` table (global only today): `id, name UNIQUE, description, content, category, is_active, is_builtin, created_at, updated_at`. `SkillManager.generate_skill()` already does AI-authored skill content generation (name + description + use_cases → LLM writes markdown). All of this is reused, not replaced.
- `WorkerCard` (`frontend/app/swarms/page.tsx:323`) already supports inline editing of a worker's `model`. This is the natural home for the new "Configure" panel.

## What's new

### 1. Tool selection (no backend changes)

New "Configurar" button on `WorkerCard` opens a panel with a "Herramientas" tab: every tool the `ToolRegistry` exposes, grouped by its existing `category` (iot, files, web, etc.), each with a checkbox, plus a text filter to search by name. Pre-checked according to the worker's current `allowed_tools`:
- `"all"` → every checkbox checked.
- `"none"` → every checkbox unchecked.
- a JSON array → only the listed tool names checked.

Saving calls the existing `PUT /api/swarms/{swarm_id}/workers/{worker_id}` with `allowed_tools` set to a JSON array of the checked tool names (or the literal string `"all"` if every tool ended up checked, `"none"` if none did — keeps the stored value in the same shape the execution path already expects).

### 2. Skills (system + private)

**Schema (new migration, `_SCHEMA_VERSION` 31 → 32):**
- Add nullable `worker_id INTEGER REFERENCES swarm_workers(id) ON DELETE CASCADE` to `skills`. `NULL` = global system skill (today's behavior, unchanged). Non-null = private to that one worker — never returned by the existing global "list all skills" endpoints, never injected into any other worker's or the main assistant's prompt.
- Replace the existing `UNIQUE` constraint on `skills.name` with two **partial unique indexes** (SQLite supports `WHERE` on `CREATE INDEX`) instead of a plain composite `UNIQUE(name, worker_id)` — a composite unique constraint would let two *global* skills share a name, since SQL treats `NULL != NULL` in uniqueness checks:
  - `CREATE UNIQUE INDEX idx_skills_name_global ON skills(name) WHERE worker_id IS NULL;` (preserves today's global-name-uniqueness invariant)
  - `CREATE UNIQUE INDEX idx_skills_name_per_worker ON skills(name, worker_id) WHERE worker_id IS NOT NULL;` (a worker's own skill names must be unique to that worker, but two different workers can each have a skill named the same thing)
- New table `worker_skills (worker_id INTEGER, skill_id INTEGER, PRIMARY KEY (worker_id, skill_id), FOREIGN KEY(worker_id) REFERENCES swarm_workers(id) ON DELETE CASCADE, FOREIGN KEY(skill_id) REFERENCES skills(id) ON DELETE CASCADE)` — presence of a row means "this **global** skill is enabled for this worker." Only ever references global skills (`skill_id` where `skills.worker_id IS NULL`); a worker's own private skills don't need a row here — their applicability is just `is_active` on the skill itself (reusing the column that already exists).

**New behavior:** when a worker's turn runs, its effective skill set = (its own private skills where `is_active = 1`) ∪ (global skills where `is_active = 1` AND a `worker_skills` row exists for this worker). New method on `SkillManager`, e.g. `get_active_skills_prompt_for_worker(worker_id, user_message)`, built the same way the existing global `get_active_skills_prompt()` is, just filtered to this combined set instead of "all active global skills."

**New API endpoints** (under the existing swarms router):
- `GET /api/swarms/{swarm_id}/workers/{worker_id}/skills` → `{ "global_skills": [{...skill, enabled: bool}], "private_skills": [{...skill}] }` — every global skill annotated with whether this worker has it enabled, plus this worker's own private skills.
- `POST /api/swarms/{swarm_id}/workers/{worker_id}/skills/{skill_id}` → enable a global skill for this worker (insert into `worker_skills`; 400 if `skill_id` refers to a private skill).
- `DELETE /api/swarms/{swarm_id}/workers/{worker_id}/skills/{skill_id}` → disable it (delete the `worker_skills` row).
- `POST /api/swarms/{swarm_id}/workers/{worker_id}/skills/generate` → same shape as the existing global `POST /api/skills/generate` (name, description, use_cases → AI writes content), but persists with `worker_id` set instead of `NULL`.
- Existing `POST /api/skills/{id}/toggle` and `DELETE /api/skills/{id}` are reused as-is for a worker's private skills (they already operate on `is_active` / row deletion by id, which works identically for a private skill row).

### 3. UI

`WorkerCard` gets a "Configurar" button opening a panel with two tabs:
- **"Herramientas"** — the checkbox-by-category list from section 1.
- **"Skills"** — the system skills as a checkbox list (checked = enabled for this worker, via the new enable/disable endpoints), visually separated from a "Skills de este worker" section listing its private skills with edit/toggle/delete, and a "+ Nueva skill personalizada" button that reuses the existing AI-generation modal/flow, pointed at the new per-worker generate endpoint.

This is a panel inside the existing `/swarms` page — not yet a dedicated full-screen view. The full-screen "open a worker to see everything" experience is deferred to the node-builder sub-project, where it'll show tools + skills + nodes together.

## Explicitly out of scope (future sub-projects)

- The node-based visual builder for custom/chained tools.
- Import/export of a worker's full configuration.
- A full-screen dedicated worker editor.
