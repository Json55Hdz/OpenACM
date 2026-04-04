# Skills System

Skills are markdown files that change how OpenACM **thinks and behaves** — not what it can do. When a skill is active, its content is injected into the system prompt before the LLM call, giving it domain expertise, specialized behavior, or a custom persona.

---

## Skills vs Tools

| | Skills | Tools |
|--|--------|-------|
| What they are | Markdown instructions | Python async functions |
| What they do | Change LLM behavior | Execute code and actions |
| How they're stored | `.md` files + SQLite | `.py` files + registry |
| Runtime effect | Injected into system prompt | Called by LLM as function |
| Created with | `create_skill` tool | `create_tool` tool |

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

The YAML frontmatter (`---`) is optional but recommended for organization.

---

## Built-in Skills

OpenACM ships with these built-in skills:

| Name | Category | Description |
|------|----------|-------------|
| `agent-creator` | agents | Expertise in designing and creating autonomous agents |
| `blender-modeling` | custom | Expert 3D modeling and Blender Python scripting |
| `file-generator` | custom | Best practices for generating various file formats |
| `video-capture` | custom | Screen recording and video automation workflows |
| `flutter-app-creator` | development | Flutter/Dart app scaffolding and development |
| `unity-mpc-skill` | development | Unity game development with Model Predictive Control |
| `windows-file-manager` | custom | Windows file system operations and organization |

Built-in skills are seeded from the `skills/` directory on startup and marked as `is_builtin: true` in the database. They can be activated/deactivated but not deleted.

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

Skills can be activated:

1. **Manually via dashboard** — toggle the skill on the Skills page
2. **Via chat** — `toggle_skill("python-expert", active=True)`
3. **Auto-matched** — Brain detects keywords in the message and auto-activates relevant skills

When a skill is active, its full markdown content is appended to the system prompt on every request.

---

## Auto-Matching

The SkillManager can automatically activate skills based on message content. If a message mentions "3D model", "Blender", "mesh", or "render", the `blender-modeling` skill activates automatically for that conversation turn.

The active skill is shown in the chat UI with a purple badge: `✨ blender-modeling`.

---

## Skill Categories

| Category | Purpose |
|----------|---------|
| `agents` | Multi-agent system skills |
| `custom` | User-created general skills |
| `development` | Programming language/framework expertise |
| `generated` | Skills created by OpenACM itself |
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
File created in skills/     ──► Auto-discovered on startup
     │                              │
     ▼                              ▼
DB row created (is_builtin=true)   DB row created (is_builtin=false)
     │
     ▼
User activates skill (dashboard or chat)
     │
     ▼
Brain injects skill content into system prompt
     │
     ▼
LLM call made with skill context
     │
     ▼
Skill active badge shown in chat UI
```

---

## Combining Skills

Multiple skills can be active simultaneously. All active skill contents are concatenated into the system prompt. Be aware of potential conflicts — two skills with contradictory instructions will confuse the LLM.

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
