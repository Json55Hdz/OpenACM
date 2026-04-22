# Dev Mode Plugin — Implementation Plan

> **Status**: Planning · Not implemented  
> **Goal**: A first-party OpenACM plugin that mirrors every Claude Code tool and slash command as native OpenACM tools + skills, giving the LLM full programmer-grade capabilities from within any chat channel.

---

## 1. Overview

Claude Code gives the AI a rich set of developer tools (file system, shell, git, web, code intelligence, task management). OpenACM can expose the same surface through its plugin system, so a developer asking "refactor this file" or "run the tests and show me what broke" gets exactly the same power they'd have in the CLI — but integrated with channels, memory, swarms, cron, and the full OpenACM UI.

The plugin registers:
- **26 tools** covering every Claude Code tool category
- **10 skills** that replicate key Claude Code slash commands
- **1 FastAPI router** for read-only queries the frontend needs (file tree, git status, diagnostics)
- **1 frontend page** (`/dev`) — a developer dashboard
- **1 LLM context extension** — tells the AI it's in programmer mode and what it can do

---

## 2. File Structure

```
src/openacm/plugins/dev_mode/
├── __init__.py                  ← Plugin class, registers everything
├── tools/
│   ├── __init__.py
│   ├── filesystem.py            ← read_file, write_file, edit_file, glob_files, grep_files
│   ├── execution.py             ← bash_exec, monitor_process, powershell_exec
│   ├── web.py                   ← web_fetch, web_search
│   ├── git.py                   ← git_status, git_diff, git_log, git_commit, git_ops
│   ├── notebook.py              ← notebook_read, notebook_edit
│   ├── planning.py              ← todo_write, task_create, task_list, task_update, create_plan
│   └── code_intel.py            ← get_diagnostics, go_to_definition, find_references
├── skills/
│   ├── dev-mode.md              ← Core programmer mode context (always active when plugin on)
│   ├── code-review.md           ← /review equivalent
│   ├── security-review.md       ← /security-review equivalent
│   ├── batch-changes.md         ← /batch equivalent
│   ├── project-init.md          ← /init equivalent
│   ├── debug-session.md         ← /debug equivalent
│   ├── simplify-code.md         ← /simplify equivalent
│   ├── generate-docs.md         ← documentation generation
│   ├── test-runner.md           ← run, analyze, and fix failing tests
│   └── git-workflow.md          ← smart git commit/branch/PR helper
└── router.py                    ← /api/dev/* endpoints for frontend

frontend/app/dev/
└── page.tsx                     ← Dev dashboard page

frontend/components/dev/
├── file-tree.tsx                ← Interactive file explorer
├── git-panel.tsx                ← Git status / diff viewer
├── todo-panel.tsx               ← Active todos from LLM session
└── diagnostics-panel.tsx        ← Code errors/warnings from LSP
```

---

## 3. Tool Catalog

All tools follow the `@tool(name, description, parameters, risk_level, category)` pattern.  
Risk levels: `low` (auto-run) · `medium` (prompt in normal mode, auto in yolo) · `high` (always prompt unless yolo + explicit allow).

### 3.1 Filesystem Tools → `filesystem.py`

#### `dev_read_file`
```python
name        = "dev_read_file"
description = "Read a file from the workspace. Supports offset/limit for large files."
risk_level  = "low"
category    = "file"
parameters  = {
    "path":   { "type": "string", "description": "Absolute or workspace-relative path" },
    "offset": { "type": "integer", "description": "Line number to start reading from" },
    "limit":  { "type": "integer", "description": "Max number of lines to return" }
}
required    = ["path"]
```
Maps to: `Read` in Claude Code.

---

#### `dev_write_file`
```python
name        = "dev_write_file"
description = "Create or fully overwrite a file. Use dev_edit_file for targeted changes."
risk_level  = "medium"
category    = "file"
parameters  = {
    "path":    { "type": "string" },
    "content": { "type": "string", "description": "Full file content to write" }
}
required    = ["path", "content"]
```
Maps to: `Write` in Claude Code.

---

#### `dev_edit_file`
```python
name        = "dev_edit_file"
description = "Replace an exact string in a file. Fails if old_string not found or not unique."
risk_level  = "medium"
category    = "file"
parameters  = {
    "path":        { "type": "string" },
    "old_string":  { "type": "string", "description": "Exact text to find and replace" },
    "new_string":  { "type": "string", "description": "Replacement text" },
    "replace_all": { "type": "boolean", "description": "Replace every occurrence (default false)" }
}
required    = ["path", "old_string", "new_string"]
```
Maps to: `Edit` in Claude Code.

---

#### `dev_glob`
```python
name        = "dev_glob"
description = "Find files matching a glob pattern, sorted by modification time."
risk_level  = "low"
category    = "file"
parameters  = {
    "pattern": { "type": "string", "description": "Glob pattern, e.g. src/**/*.tsx" },
    "path":    { "type": "string", "description": "Root directory to search in (defaults to workspace)" }
}
required    = ["pattern"]
```
Maps to: `Glob` in Claude Code. Implementation: `pathlib.Path.glob` / `fnmatch`.

---

#### `dev_grep`
```python
name        = "dev_grep"
description = "Search file contents using ripgrep. Supports regex, file type filters, and context lines."
risk_level  = "low"
category    = "file"
parameters  = {
    "pattern":     { "type": "string", "description": "Regex pattern to search" },
    "path":        { "type": "string", "description": "File or directory to search in" },
    "glob":        { "type": "string", "description": "Glob filter, e.g. *.ts" },
    "type":        { "type": "string", "description": "File type filter, e.g. py, js, rust" },
    "output_mode": { "type": "string", "enum": ["content", "files_with_matches", "count"] },
    "context":     { "type": "integer", "description": "Lines of context around each match" },
    "ignore_case": { "type": "boolean" },
    "head_limit":  { "type": "integer", "description": "Max results to return" }
}
required    = ["pattern"]
```
Maps to: `Grep` in Claude Code. Implementation: subprocess `rg` (ripgrep) or Python `re` fallback.

---

### 3.2 Execution Tools → `execution.py`

#### `dev_bash`
```python
name        = "dev_bash"
description = "Execute a shell command in the workspace. Captures stdout, stderr, and exit code."
risk_level  = "high"
category    = "system"
parameters  = {
    "command":     { "type": "string", "description": "Shell command to execute" },
    "timeout":     { "type": "integer", "description": "Max execution time in seconds (default 120)" },
    "cwd":         { "type": "string",  "description": "Working directory (defaults to workspace root)" },
    "background":  { "type": "boolean", "description": "Run detached and return immediately" }
}
required    = ["command"]
```
Maps to: `Bash` in Claude Code.  
Uses existing sandbox plumbing (`_sandbox`, `_confirm_callback`).

---

#### `dev_powershell`
```python
name        = "dev_powershell"
description = "Execute a PowerShell command. Available on Windows; uses pwsh on Linux/macOS."
risk_level  = "high"
category    = "system"
parameters  = {
    "command": { "type": "string" },
    "timeout": { "type": "integer", "description": "Max seconds (default 120)" }
}
required    = ["command"]
```
Maps to: `PowerShell` in Claude Code.

---

#### `dev_monitor`
```python
name        = "dev_monitor"
description = "Run a command and stream its output until a condition is met or duration expires."
risk_level  = "high"
category    = "system"
parameters  = {
    "command":      { "type": "string" },
    "until_pattern":{ "type": "string", "description": "Stop when this regex matches a line" },
    "duration":     { "type": "integer", "description": "Max seconds to watch (default 60)" }
}
required    = ["command"]
```
Maps to: `Monitor` in Claude Code.

---

### 3.3 Web Tools → `web.py`

#### `dev_web_fetch`
```python
name        = "dev_web_fetch"
description = "Fetch the content of a URL and return it as markdown or plain text."
risk_level  = "low"
category    = "web"
parameters  = {
    "url":        { "type": "string" },
    "max_tokens": { "type": "integer", "description": "Truncate response to this many tokens" }
}
required    = ["url"]
```
Maps to: `WebFetch` in Claude Code.

---

#### `dev_web_search`
```python
name        = "dev_web_search"
description = "Search the web and return a ranked list of results with title, URL, and snippet."
risk_level  = "low"
category    = "web"
parameters  = {
    "query":       { "type": "string" },
    "num_results": { "type": "integer", "description": "Results to return (default 5, max 10)" }
}
required    = ["query"]
```
Maps to: `WebSearch` in Claude Code. Uses existing search infrastructure (Brave / SerpAPI).

---

### 3.4 Git Tools → `git.py`

No direct Claude Code equivalent — these are extracted from typical Claude Code Bash patterns and promoted to first-class tools for safety and structured output.

#### `dev_git_status`
```python
name       = "dev_git_status"
risk_level = "low"
parameters = { "path": { "type": "string" } }
```

#### `dev_git_diff`
```python
name       = "dev_git_diff"
risk_level = "low"
parameters = {
    "path":   { "type": "string" },
    "staged": { "type": "boolean" },
    "ref":    { "type": "string", "description": "Commit or branch to diff against" }
}
```

#### `dev_git_log`
```python
name       = "dev_git_log"
risk_level = "low"
parameters = {
    "n":      { "type": "integer", "description": "Number of commits (default 20)" },
    "branch": { "type": "string" },
    "path":   { "type": "string", "description": "Filter to changes in this path" }
}
```

#### `dev_git_commit`
```python
name       = "dev_git_commit"
risk_level = "medium"
parameters = {
    "message": { "type": "string" },
    "files":   { "type": "array", "items": { "type": "string" }, "description": "Files to stage (empty = all modified)" },
    "amend":   { "type": "boolean" }
}
```

#### `dev_git_ops`
```python
name        = "dev_git_ops"
description = "General-purpose git command for operations not covered by specific tools (checkout, branch, merge, push, pull, stash...)."
risk_level  = "high"
parameters  = {
    "args": { "type": "string", "description": "Everything after 'git', e.g. 'checkout -b feature/x'" }
}
```

---

### 3.5 Notebook Tools → `notebook.py`

#### `dev_notebook_read`
```python
name        = "dev_notebook_read"
description = "Read a Jupyter notebook, returning all cells with their outputs."
risk_level  = "low"
category    = "file"
parameters  = { "path": { "type": "string" } }
required    = ["path"]
```

#### `dev_notebook_edit`
```python
name        = "dev_notebook_edit"
description = "Modify a cell in a Jupyter notebook by index."
risk_level  = "medium"
category    = "file"
parameters  = {
    "path":       { "type": "string" },
    "cell_index": { "type": "integer" },
    "content":    { "type": "string", "description": "New cell content" },
    "cell_type":  { "type": "string", "enum": ["code", "markdown"], "description": "Default: preserve existing type" }
}
required    = ["path", "cell_index", "content"]
```
Maps to: `NotebookEdit` in Claude Code.

---

### 3.6 Planning & Task Tools → `planning.py`

#### `dev_todo_write`
```python
name        = "dev_todo_write"
description = "Replace the session todo list with a new set of items. Use to track multi-step plans."
risk_level  = "low"
parameters  = {
    "todos": {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {
                "content":  { "type": "string" },
                "status":   { "type": "string", "enum": ["pending", "in_progress", "completed"] },
                "priority": { "type": "string", "enum": ["high", "medium", "low"] }
            }
        }
    }
}
required    = ["todos"]
```
Maps to: `TodoWrite` in Claude Code. Persisted in session memory; rendered in the frontend todo panel.

---

#### `dev_task_create`
```python
name        = "dev_task_create"
description = "Create a tracked background task (long-running bash, build, test run)."
risk_level  = "medium"
parameters  = {
    "command":     { "type": "string" },
    "description": { "type": "string" },
    "timeout":     { "type": "integer" }
}
required    = ["command", "description"]
```
Maps to: `TaskCreate` in Claude Code. Backed by cron/subprocess infrastructure.

---

#### `dev_task_list`
```python
name       = "dev_task_list"
risk_level = "low"
parameters = {}
```
Maps to: `TaskList`.

---

#### `dev_task_update`
```python
name       = "dev_task_update"
risk_level = "low"
parameters = {
    "task_id": { "type": "string" },
    "status":  { "type": "string", "enum": ["running", "completed", "failed", "cancelled"] },
    "note":    { "type": "string" }
}
required   = ["task_id", "status"]
```
Maps to: `TaskUpdate`.

---

#### `dev_create_plan`
```python
name        = "dev_create_plan"
description = "Draft a structured multi-step implementation plan and store it for reference."
risk_level  = "low"
parameters  = {
    "title":       { "type": "string" },
    "description": { "type": "string" },
    "steps":       { "type": "array", "items": { "type": "string" } }
}
required    = ["title", "description", "steps"]
```
Maps to: `EnterPlanMode / ExitPlanMode` in Claude Code.

---

### 3.7 Code Intelligence Tools → `code_intel.py`

These depend on IDE MCP integration (`mcp__ide__*`) if available, with fallback to static analysis.

#### `dev_get_diagnostics`
```python
name        = "dev_get_diagnostics"
description = "Get LSP errors and warnings for a file or the whole workspace."
risk_level  = "low"
parameters  = { "path": { "type": "string", "description": "File path (omit for all files)" } }
```
Maps to: `LSP` / `mcp__ide__getDiagnostics` in Claude Code.  
Fallback: run `pyright`, `eslint`, `tsc --noEmit`, `mypy` depending on detected language.

---

#### `dev_go_to_definition`
```python
name        = "dev_go_to_definition"
description = "Find the definition of a symbol at a given file position."
risk_level  = "low"
parameters  = {
    "path":   { "type": "string" },
    "line":   { "type": "integer" },
    "column": { "type": "integer" }
}
required    = ["path", "line", "column"]
```
Maps to: `LSP` in Claude Code (go-to-definition action).

---

#### `dev_find_references`
```python
name        = "dev_find_references"
description = "Find all references to a symbol across the workspace."
risk_level  = "low"
parameters  = {
    "path":   { "type": "string" },
    "line":   { "type": "integer" },
    "column": { "type": "integer" }
}
required    = ["path", "line", "column"]
```
Maps to: `LSP` in Claude Code (find-references action).

---

## 4. Tool Summary Table

| Claude Code Tool | OpenACM Tool(s) | Risk |
|---|---|---|
| `Read` | `dev_read_file` | low |
| `Write` | `dev_write_file` | medium |
| `Edit` | `dev_edit_file` | medium |
| `Glob` | `dev_glob` | low |
| `Grep` | `dev_grep` | low |
| `Bash` | `dev_bash` | high |
| `PowerShell` | `dev_powershell` | high |
| `Monitor` | `dev_monitor` | high |
| `WebFetch` | `dev_web_fetch` | low |
| `WebSearch` | `dev_web_search` | low |
| `NotebookEdit` | `dev_notebook_read` + `dev_notebook_edit` | low / medium |
| `TodoWrite` | `dev_todo_write` | low |
| `TaskCreate/List/Update/Stop` | `dev_task_create/list/update` | low / medium |
| `EnterPlanMode/ExitPlanMode` | `dev_create_plan` | low |
| `LSP` | `dev_get_diagnostics`, `dev_go_to_definition`, `dev_find_references` | low |
| `Agent` | existing Swarms system | — |
| `CronCreate/Delete/List` | existing Cron system | — |
| `SendMessage` | existing Swarm messaging | — |
| `EnterWorktree` | `dev_bash("git worktree add ...")` | high |
| *(no equivalent)* | `dev_git_status/diff/log/commit/ops` | low / medium / high |

**Total new tools: 26**  
**Delegated to existing systems: 5** (Swarms, Cron, MCP)

---

## 5. Skill Catalog

Skills inject markdown context into the LLM system prompt when active. These replicate Claude Code slash commands.

### `dev-mode.md` — Core context (always active with plugin)
```
category: development
```
Tells the LLM:
- It has full filesystem R/W access via `dev_*` tools
- It should always read files before editing them
- It should prefer `dev_edit_file` over `dev_write_file` for targeted changes
- Bash commands run in the workspace root by default
- It should use `dev_todo_write` to track multi-step work
- Git tools exist for structured version control
- Use `dev_get_diagnostics` before declaring code "done"

---

### `code-review.md` — `/review` equivalent
```
category: development
```
Step-by-step review workflow:
1. Read changed files with `dev_git_diff`
2. Check diagnostics with `dev_get_diagnostics`
3. Search for common issues with `dev_grep` (TODO, FIXME, console.log, print, hardcoded secrets)
4. Produce a structured review report (correctness, security, performance, style)

---

### `security-review.md` — `/security-review` equivalent
```
category: security
```
Security-focused analysis:
- OWASP Top 10 checklist
- Grep patterns for: `eval(`, `exec(`, SQL string concatenation, hardcoded credentials, unsafe deserialization
- Dependency vulnerability check via `dev_bash("pip audit")` / `npm audit`

---

### `batch-changes.md` — `/batch` equivalent
```
category: development
```
Protocol for large-scale refactors:
1. Use `dev_glob` to find all affected files
2. Read each file before editing
3. Apply changes with `dev_edit_file` (never `dev_write_file` for refactors)
4. Run diagnostics after each file group
5. Report: files changed, lines affected, errors introduced/fixed

---

### `project-init.md` — `/init` equivalent
```
category: development
```
Analyzes a new project and creates:
- `OPENACM.md` (project context file, equivalent to CLAUDE.md)
- Language/framework detection via `dev_glob` + `dev_read_file`
- Build/test/lint command discovery
- Populates `dev_todo_write` with onboarding steps

---

### `debug-session.md` — `/debug` equivalent
```
category: development
```
Structured debugging protocol:
1. Capture error with `dev_bash` or user-provided stack trace
2. `dev_grep` for the error string in the codebase
3. `dev_read_file` surrounding lines for context
4. Form hypothesis → apply fix → run test → iterate

---

### `simplify-code.md` — `/simplify` equivalent
```
category: development
```
Code quality sweep:
- Flag functions >50 lines
- Flag files >500 lines
- Find duplicate code blocks via `dev_grep`
- Suggest extractions, renames, simplifications without changing behavior

---

### `generate-docs.md` — Documentation generation
```
category: development
```
Generates or updates:
- README.md from project structure
- Docstrings / JSDoc from function signatures
- OpenAPI spec from API route files
- CHANGELOG entry from `dev_git_log`

---

### `test-runner.md` — Test analysis
```
category: development
```
1. Detect test framework (`pytest`, `jest`, `vitest`, `go test`, etc.) via `dev_glob`
2. Run tests with `dev_bash`
3. Parse failures, map to source files with `dev_grep`
4. Propose fixes, re-run, iterate up to 3 rounds

---

### `git-workflow.md` — Smart git helper
```
category: development
```
Opinionated git workflow:
- Always `dev_git_status` before committing
- `dev_git_diff --staged` for review
- Commit message format: `type(scope): description`
- Warns before force-push or amend on published commits

---

## 6. LLM Context Extension

Injected into the system prompt when the plugin is active:

```markdown
## Developer Mode Active

You have full programmer capabilities via dev_* tools:

**Filesystem**: dev_read_file, dev_write_file, dev_edit_file, dev_glob, dev_grep
**Execution**: dev_bash (shell), dev_powershell (Windows), dev_monitor (streaming)
**Web**: dev_web_fetch, dev_web_search
**Git**: dev_git_status, dev_git_diff, dev_git_log, dev_git_commit, dev_git_ops
**Notebooks**: dev_notebook_read, dev_notebook_edit
**Code Intel**: dev_get_diagnostics, dev_go_to_definition, dev_find_references
**Planning**: dev_todo_write, dev_task_create/list/update, dev_create_plan

Rules:
- Always read a file before editing it.
- Prefer dev_edit_file over dev_write_file for targeted changes.
- Use dev_todo_write to track multi-step tasks; update status as you complete each.
- Run dev_get_diagnostics after significant edits to catch regressions.
- For destructive operations (delete, force-push, overwrite), state the intent and confirm.
- Workspace root is {workspace_root}.
```

---

## 7. Frontend Page — `/dev`

A developer dashboard that surfaces live state from the plugin's tools.

### Layout

```
┌─────────────────────────────────────────────────────────────┐
│  DEV MODE                                  [Tools] [Skills] │
├─────────────────┬───────────────────────────────────────────┤
│  FILE TREE      │  GIT STATUS                               │
│                 │  ┌─ M frontend/app/chat/page.tsx          │
│  ▶ src/         │  ├─ M src/openacm/core/swarm_manager.py  │
│    ▶ openacm/   │  └─ ?? calculation.txt                   │
│      ▶ plugins/ │                                           │
│      ▶ core/    │  DIAGNOSTICS                              │
│  ▶ frontend/    │  ● 0 errors  △ 2 warnings                │
│    ▶ app/       │  ▸ frontend/app/chat/page.tsx:516         │
│    ▶ components/│    React Hook in conditional              │
│                 │                                           │
├─────────────────┴───────────────────────────────────────────┤
│  ACTIVE TODOS                              [Clear]          │
│  ✓ Fix hook violation in MessageBubble                      │
│  ◎ Add tool deduplication                   in_progress     │
│  ○ Write unit tests                          pending        │
└─────────────────────────────────────────────────────────────┘
```

### Components

- **FileTree** (`file-tree.tsx`): Collapsible directory tree from `GET /api/dev/filetree`. Click to open file in chat context.
- **GitPanel** (`git-panel.tsx`): Live `git status` + diff preview from `GET /api/dev/git-status` and `GET /api/dev/git-diff`.
- **DiagnosticsPanel** (`diagnostics-panel.tsx`): Errors/warnings from `GET /api/dev/diagnostics`. Links open file in terminal.
- **TodoPanel** (`todo-panel.tsx`): Current session todos from `GET /api/dev/todos`. Status badges with ok/warn/err dots.

---

## 8. Backend API Router — `router.py`

Read-only endpoints consumed by the frontend dashboard. All write operations go through the AI tools.

```
GET  /api/dev/filetree          → directory tree (depth limited, gitignore aware)
GET  /api/dev/git-status        → parsed git status (staged, unstaged, untracked)
GET  /api/dev/git-diff          → diff of modified files (optional ?staged=true)
GET  /api/dev/diagnostics       → current lint/type errors (calls static analysis)
GET  /api/dev/todos             → current session todo list
POST /api/dev/todos             → overwrite todos (mirrors dev_todo_write tool)
GET  /api/dev/tasks             → running background tasks
```

---

## 9. Plugin Registration — `__init__.py`

```python
class DevModePlugin(Plugin):
    name        = "dev_mode"
    version     = "1.0.0"
    description = "Full programmer mode — all Claude Code tools as native OpenACM tools"
    author      = "OpenACM"

    def get_tool_modules(self):
        from .tools import filesystem, execution, web, git, notebook, planning, code_intel
        return [filesystem, execution, web, git, notebook, planning, code_intel]

    def get_skills(self):
        # Load from skills/*.md files in this package directory
        return _load_skill_files(Path(__file__).parent / "skills")

    def get_context_extension(self):
        return DEV_MODE_CONTEXT_PROMPT.format(workspace_root=self._workspace_root)

    def get_intent_keywords(self):
        return {
            "file":   ["read", "write", "edit", "open", "create file", "delete", "glob", "find files"],
            "system": ["run", "execute", "bash", "shell", "command", "install", "build", "test", "terminal"],
            "web":    ["search", "fetch", "scrape", "download", "url", "http"],
            "git":    ["commit", "push", "pull", "branch", "diff", "status", "merge", "stash", "rebase"],
        }

    def get_nav_items(self):
        return [{"path": "/dev", "label": "Dev Mode", "icon": "Code2", "section": "main"}]

    def get_api_router(self):
        from .router import router
        return router

    async def on_start(self, *, workspace_root, **_):
        self._workspace_root = workspace_root
```

---

## 10. Intent Routing Considerations

Some tools overlap with existing OpenACM tools (e.g., there may already be a generic `web_search` or `bash_exec` tool). Strategy:

- **Prefix all tools `dev_*`** to avoid name collisions
- **Register intent keywords** that match programming contexts (`"build"`, `"lint"`, `"test"`, `"refactor"`, etc.) so the router directs code-related messages to dev tools
- **Keep existing tools active** — dev_mode adds to, not replaces, the existing toolset
- When Dev Mode skill is active, the LLM is primed to prefer `dev_*` tools for file/exec operations

---

## 11. Security Model

| Risk Level | Behavior in Normal Mode | Behavior in Yolo Mode |
|---|---|---|
| `low` | Auto-execute | Auto-execute |
| `medium` | Confirm prompt in chat | Auto-execute |
| `high` | Confirm prompt (5s modal) | Auto-execute |

High-risk tools: `dev_bash`, `dev_powershell`, `dev_monitor`, `dev_git_ops`  
Medium-risk tools: `dev_write_file`, `dev_edit_file`, `dev_git_commit`, `dev_task_create`

All tool executions are logged to the `tool_executions` table regardless of risk level.

---

## 12. Implementation Phases

### Phase 1 — Core Filesystem + Execution (MVP)
`dev_read_file`, `dev_write_file`, `dev_edit_file`, `dev_glob`, `dev_grep`, `dev_bash`  
+ `dev-mode.md` skill  
+ Plugin registration + nav item

### Phase 2 — Web + Git
`dev_web_fetch`, `dev_web_search`  
`dev_git_status`, `dev_git_diff`, `dev_git_log`, `dev_git_commit`, `dev_git_ops`  
+ `git-workflow.md` skill  
+ `/api/dev/git-status` endpoint + GitPanel frontend component

### Phase 3 — Planning + Tasks
`dev_todo_write`, `dev_task_create/list/update`, `dev_create_plan`  
+ `dev_monitor`, `dev_powershell`  
+ TodoPanel frontend component

### Phase 4 — Full Frontend Dashboard
FileTree + DiagnosticsPanel + full `/dev` page  
+ All remaining skills

### Phase 5 — Code Intelligence
`dev_get_diagnostics`, `dev_go_to_definition`, `dev_find_references`  
+ IDE MCP integration bridge  
+ `dev_notebook_read`, `dev_notebook_edit`

---

## 13. Open Questions

1. **Sandbox**: Should `dev_bash` use the existing OpenACM sandbox (Docker/chroot) or run in the user's workspace directly? Recommend: direct in workspace for dev mode (user opted in), sandbox remains opt-in via config.
2. **Workspace root**: Fixed to `config.workspace_root` or per-session? Per-session would require the LLM to call a `set_workspace(path)` tool.
3. **Existing tool conflicts**: If `web_search` already exists, should `dev_web_search` delegate to it or be independent? Recommend delegation.
4. **Todo persistence**: Todos live in session memory (lost on restart) or in SQLite? SQLite is cleaner for the dashboard.
5. **LSP availability**: `dev_get_diagnostics` runs static CLI tools (pyright, eslint, tsc) as fallback. Does the IDE MCP server need to be connected, or is CLI-only sufficient for v1?
