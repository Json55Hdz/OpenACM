# Agent Tools & Skills Scoping — Design Spec

## Context

This redoes, against the correct subsystem, the same feature already shipped for OpenACM's **Swarms** worker feature (`docs/superpowers/specs/2026-07-04-worker-tools-and-skills-scoping-design.md`). The user's original "subagent superpowers" request was always about **Agents** (`/agents` — standalone AI agents with their own Telegram/WhatsApp channel, knowledge base, and webhook), not Swarms. The Swarms work stays as-is (a valid, separate feature); this is new, additional work targeting Agents.

This is sub-project 1 of the larger initiative for Agents (a node-based visual builder, import/export, are future sub-projects, not part of this spec).

## Current state (what already exists)

- `agents` table (`src/openacm/storage/database.py:148`): `id, name, description, system_prompt, allowed_tools TEXT DEFAULT 'all', is_active, webhook_secret, telegram_token, created_at, updated_at`.
- `AgentRunner._get_tools()` (`src/openacm/core/agent_runner.py:38-51`) **already fully supports** `"all"` / `"none"` / a JSON array of tool names — no backend change needed for tool selection, only a UI to drive it. `allowed_tools` is saved via the existing `PUT /api/agents/{id}`.
- The frontend (`frontend/app/agents/page.tsx`) only exposes a 2-option dropdown (`TOOLS_OPTIONS`, lines 43-46: `'all'` / `'none'`) — no per-tool checkbox UI exists yet, even though the card badge logic (line 1167) already anticipates a `"Custom"` state for when `allowed_tools` is neither.
- Skills: **zero integration**. No agent-scoped column on `skills`, no join table, no `SkillManager` methods, no API endpoints, no UI.
- Agents run via `AgentRunner.run()` (`agent_runner.py:68-127`), which builds a **fresh `Brain` instance per invocation** — not a persistent per-worker object like Swarms. System prompt assembly happens at `agent_runner.py:96`: `system_prompt = self._build_system_prompt(agent["system_prompt"], knowledge_items)`. `AgentRunner` is constructed in three places, none of which currently pass a `skill_manager`: `app.py:415` (channel startup), `web/routers/agents.py:416` (webhook `/chat`), `web/routers/agents.py:535` (dashboard `/test`).
- The Agents page today opens an editor via a **modal overlay** (`AgentFormModal`, `page.tsx:626+`), toggled by `modal`/`editing` state (`page.tsx:1311-1317`).

## What's new

### 1. UI shape: in-place expand, not a modal, not a separate route

Per the user's explicit correction: selecting an agent from the `/agents` grid does **not** open the existing small modal for this purpose, and does **not** navigate to a new URL/page component. Instead, the agent's card expands **in place** to fill the visible content area (same page, same route), showing everything about that agent — with an **✕** control that collapses it back to the grid of agent cards. The existing `AgentFormModal`'s Config/Knowledge/Channels tabs remain reachable from this expanded view (as tabs, same as today) — the new Tools/Skills sections are two additional tabs alongside them, all within the same expanded-in-place view. This replaces the modal-overlay presentation with an inline expand/collapse of the same underlying tabbed content; no new page route is created.

### 2. Tools tab

Reuses the exact same checkbox-by-category + search UI pattern already built for Swarms (`frontend/hooks/use-worker-config.ts`'s `parseAllowedTools`/`serializeAllowedTools`, generalized to not be worker-specific). Saves via the existing `PUT /api/agents/{id}` with `allowed_tools` set to `"all"` / `"none"` / a JSON array — **no backend change** (mirrors `AgentRunner._get_tools()`'s already-supported formats exactly).

### 3. Skills tab

**Schema (new migration):**
- Add nullable `agent_id INTEGER REFERENCES agents(id) ON DELETE CASCADE` to the existing `skills` table — a **new column, parallel to** the already-shipped `worker_id` (not a modification of it, per explicit decision: safer, doesn't touch anything already in production, reuses the identical proven pattern).
- The existing `idx_skills_name_global` index (`ON skills(name) WHERE worker_id IS NULL`) must be **dropped and recreated** as `ON skills(name) WHERE worker_id IS NULL AND agent_id IS NULL` — otherwise a global skill and an agent-scoped skill could collide on name (the old index's `WHERE` clause doesn't know `agent_id` exists). Add one new index, mirroring `idx_skills_name_per_worker`: `CREATE UNIQUE INDEX idx_skills_name_per_agent ON skills(name, agent_id) WHERE agent_id IS NOT NULL;`.
- New table `agent_skills (agent_id INTEGER, skill_id INTEGER, PRIMARY KEY (agent_id, skill_id), FOREIGN KEY(agent_id) REFERENCES agents(id) ON DELETE CASCADE, FOREIGN KEY(skill_id) REFERENCES skills(id) ON DELETE CASCADE)` — parallel to `worker_skills`; a row means "this global skill is enabled for this agent."
- **Invariant:** a single `skills` row is never both worker-scoped and agent-scoped — `worker_id` and `agent_id` are mutually exclusive (enforced at the application layer, by the fact that `create_skill()` only ever receives one or the other, never both, from any call site).

**SkillManager methods** (mirroring the Swarms ones exactly): `create_agent_skill(agent_id, name, description, content, category="custom")`, `generate_agent_skill(agent_id, name, description, use_cases, llm_router)`, `get_active_skills_prompt_for_agent(agent_id, user_message="")` — same DB-only/no-file-write and cache-isolation constraints as their worker counterparts.

**Database methods:** `get_all_skills()` must now filter `WHERE worker_id IS NULL AND agent_id IS NULL` (extending, not just repeating, the existing filter). New: `get_agent_private_skills(agent_id)`, `get_agent_enabled_global_skill_ids(agent_id)`, `enable_agent_skill(agent_id, skill_id)`, `disable_agent_skill(agent_id, skill_id)` — parallel to the worker equivalents. `create_skill()` gains an `agent_id: int | None = None` param alongside the existing `worker_id` one.

**API endpoints** under the agents router (simpler than Swarms' nested shape, since an Agent is the top-level unit, not nested inside anything): `GET /api/agents/{agent_id}/skills`, `POST` / `DELETE /api/agents/{agent_id}/skills/{skill_id}` (enable/disable a global skill, 400 if `skill_id` is private), `POST /api/agents/{agent_id}/skills/generate`. Existing `POST /api/skills/{id}/toggle` and `DELETE /api/skills/{id}` are reused as-is for an agent's private skills.

### 4. Wiring into execution

`AgentRunner.__init__` gains `skill_manager=None`. In `run()`, right after building `knowledge_items` and before/alongside `_build_system_prompt` (`agent_runner.py:88-96`): fetch `skills_prompt = await self.skill_manager.get_active_skills_prompt_for_agent(agent["id"])` (guarded by `if self.skill_manager:`), and append it to the assembled system prompt the same way `brain_prompt.py` and the Swarms wiring already do (`system_prompt = f"{system_prompt}\n\n{skills_prompt}"` when non-empty). All three `AgentRunner(...)` construction sites (`app.py:415`, `agents.py:416`, `agents.py:535`) pass `skill_manager=self.skill_manager` / `skill_manager=_state.brain.skill_manager` respectively.

## Explicitly out of scope (future sub-projects)

- The node-based visual builder for custom/chained tools.
- Import/export of an agent's full configuration.
- Any change to the existing Config/Knowledge/Channels tabs' own behavior.
