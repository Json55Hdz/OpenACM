# Skills System

Skills are markdown files that change how OpenACM **thinks and behaves** — not what it can do. When an active skill is relevant to the current message, its content is injected into the system prompt before the LLM call, giving it domain expertise, specialized behavior, or a custom persona.

---

## Skills vs Tools

| | Skills | Tools |
|--|--------|-------|
| What they are | Markdown instructions | Python async functions |
| What they do | Change LLM behavior | Execute code and actions |
| How they're stored | `.md` files + SQLite | `.py` modules + registry |
| Runtime effect | Injected into system prompt | Called by LLM as function |
| Created with | `create_skill` tool, Skills page, or a `.md` file | A `@tool` module or a plugin |

---

## Skill File Format

Skills live in `skills/{category}/` as markdown files.

```markdown
---
name: blender-modeling
description: Expert 3D modeling guidance for Blender
category: custom
---

# Blender 3D Modeling Expert

You are now a Blender expert. When the user asks about 3D modeling:

## Key Behaviors
- Always suggest using the correct Blender shortcut keys
- Use `bpy` Python API when scripting is needed
- Prefer modifier-based workflows over manual editing
- Always mention the Blender version compatibility

## Common Workflows
- Creating objects: Add menu (Shift+A) → choose primitive
- Sculpting: Tab to switch to Sculpt Mode, use dynamic topology
- Rigging: Armature objects, parent with automatic weights
...
```

The frontmatter (`---`) is optional but recommended. Only simple `key: value` lines for `name`, `description` and `category` are read; without it the skill takes its name from the file name and its category from the folder.

---

## Shipped Skills

The repository ships these skill files in `skills/`:

| Name | Category | Description |
|------|----------|-------------|
| `agent-creator` | agents | Expertise in designing and creating autonomous agents |
| `blender-modeling` | custom | 3D modeling guidance for Blender (`bpy`) |
| `file-generator` | custom | Best practices for generating various file formats |
| `video-capture` | custom | Screen recording and video automation workflows |
| `flutter-app-creator` | development | Flutter/Dart app scaffolding and development |
| `unity-mpc-skill` | development | Unity game development via Unity MCP |

On startup every `skills/<category>/*.md` file that is not yet in the database is added to it. (Files placed directly in `skills/` — not in a category folder — are not synced.)

`core/skill_manager_default_skills.py` also defines six default skills — `security-auditor`, `code-reviewer`, `api-designer`, `rag-optimizer`, `fastapi-expert`, `database-architect` — which are written to disk and marked `is_builtin` **only when the skills table is completely empty** at startup. Built-in skills can be deactivated but not deleted.

---

## Creating Skills

### Via Chat
```
You: Create a skill called "python-expert" that makes you an expert Python developer focused on clean code, type hints, and modern Python 3.12+ features
```

OpenACM will call `create_skill` and write the markdown.

### Via Dashboard
Go to **Skills** → **New Skill** and fill in the form.

### Manually
Create a `.md` file in `skills/{category}/`:

```bash
skills/
  custom/
    my-skill.md
  development/
    python-expert.md
  agents/
    research-specialist.md
```

OpenACM syncs the `skills/` directory to the database on startup. New files are automatically discovered.

---

## Activating Skills

A skill has an **active** flag. Turn it on or off:

1. **Via dashboard** — toggle the skill on the Skills page
2. **Via chat** — `toggle_skill("python-expert")` flips it
3. **Via API** — `POST /api/skills/{id}/toggle`

Being active doesn't mean a skill is sent on every request — see matching below.

---

## Matching (when a skill is injected)

For each message, the SkillManager looks at the **active** skills and injects only the relevant ones:

- The six default skills have built-in keyword lists (e.g. `code-reviewer` matches "review", "refactor", "revisa"…; `database-architect` matches "sql", "schema", "database"…).
- Any skill is injected when the message mentions its name (e.g. "blender-modeling" or "blender modeling").
- If nothing matches, no skill content is added.

Each injected skill is capped at 1,200 characters, wrapped in a "Specialized Context (for this query only)" block. The matched skills are shown in the chat UI with a badge (`skill.active` event).

### Agent, worker and flow skills

Besides global skills, an **agent** can enable specific global skills and have its own private skills (Agents → Skills tab, or `POST /api/agents/{id}/skills/generate`); swarm **workers** can have private skills too; and each agent **flow** can have one skill that explains to the agent when and how to use that flow (see [Agent Flows](./28-agent-flows.md)).

---

## Skill Categories

| Category | Purpose |
|----------|---------|
| `agents` | Multi-agent system skills |
| `ai` | AI/ML related skills |
| `custom` | User-created general skills |
| `development` | Programming language/framework expertise |
| `generated` | Skills generated by OpenACM for agents, workers and flows |
| `security` | Security-focused behaviors |

---

## Writing Effective Skills

### Do
- Be specific about behaviors and response patterns
- Include example questions and ideal responses
- Describe what to prioritize and what to avoid
- Include domain-specific terminology the LLM should know
- Add workflow checklists for complex tasks

### Don't
- Duplicate OpenACM's core identity (already in base context)
- Describe tools — the LLM already knows about its tools
- Make the skill too long — 500 words max is a good target
- Contradict OpenACM's core rules (always use tools, etc.)

### Example: Good Skill

```markdown
# Python Expert

When writing Python code:

## Style Requirements
- Always use type hints (Python 3.10+ syntax: `str | None` not `Optional[str]`)
- Prefer `pathlib.Path` over `os.path`
- Use f-strings, never `.format()` or `%`
- Add docstrings to all public functions
- Follow PEP 8 with 88-char line length (Black formatter style)

## Code Patterns
- Use `dataclasses` or `pydantic` for data models
- Use `asyncio` for I/O operations
- Use `contextlib.suppress()` instead of `try/except/pass`
- Prefer list comprehensions for simple transformations

## Before Writing Code
1. Confirm the Python version target
2. Check if a standard library solution exists before adding dependencies
3. Write the type signature first
```

---

## Skill Lifecycle

```
File created in skills/<category>/ ──► Synced to DB on next startup (is_builtin=false)
create_skill / Skills page         ──► Written to skills/<category>/ + DB immediately
     │
     ▼
Skill marked active (dashboard, chat or API)
     │
     ▼
Message matches the skill (keywords or name)
     │
     ▼
Brain injects skill content (≤1,200 chars) into the system prompt
     │
     ▼
LLM call made with skill context → skill badge shown in chat UI
```

---

## Combining Skills

Multiple skills can be active simultaneously. All matching skill contents are concatenated into the system prompt. Be aware of potential conflicts — two skills with contradictory instructions will confuse the LLM.

**Good combination:** `python-expert` + `security-focused` — complementary domains

**Bad combination:** `formal-tone` + `casual-pirate-persona` — contradictory

---

## Skill API

| Endpoint | Description |
|----------|-------------|
| `GET /api/skills` | List all skills |
| `POST /api/skills` | Create a skill |
| `PUT /api/skills/{id}` | Update a skill |
| `DELETE /api/skills/{id}` | Delete a skill |
| `POST /api/skills/{id}/toggle` | Enable/disable |
| `GET /api/skills/active` | List currently active skills |
| `POST /api/skills/generate` | AI-generated skill from description |
