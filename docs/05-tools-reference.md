# Tools Reference

OpenACM ships with 70+ built-in tools. Tools are Python async functions decorated with `@tool`. They receive injected context (`_sandbox`, `_event_bus`, `_brain`, `_user_id`, `_channel_id`, `_channel_type`, `_confirm_callback`) alongside their declared parameters.

Which tools are available depends on what is enabled: the `browser_agent` tool can be turned off with `features.browser_agent: false`, and plugin tools (Home Assistant, Content Automation) exist only while their plugin is enabled. Tools from connected MCP servers are added at runtime. Run `/tools` in the console or open the **Tools** page to see the live list with risk levels.

> The **Risk** shown below is the tool's `risk_level` annotation (low / medium / high). It is informational — the approval prompt of the `confirmation` security mode applies to shell commands run through `run_command`. See [Security](./12-security.md).

---

## Tool Categories

| Category | Tools | Description |
|----------|-------|-------------|
| `general` | `run_command`, `run_python`, `send_file_to_chat`, `create_agent`, `list_agents`, `delete_agent`, `create_or_update_agent_flow`, `stitch_generate_ui` | Core execution and agent management |
| `system` | `system_info`, `add_resurrection_path`, `save_user_profile`, cron tools, platform tools | OS info and platform self-management |
| `file` | `read_file`, `write_file`, `list_directory`, `search_files`, `edit_file`, `read_file_range`, `grep_in_files`, `get_file_outline`, `run_linter` | File system and code editing |
| `web` | `web_search`, `get_webpage`, `browser_agent` | Web search and browsing |
| `media` | `take_screenshot` | Screen capture |
| `ai` | `remember_note`, `search_memory`, `save_customer_name` | Long-term memory (RAG) and customer memory |
| `google` | 8 tools | Gmail, Calendar, Drive, YouTube |
| `meta` | `create_skill`, `toggle_skill`, `list_skills`, `delete_skill` | Manage skills |
| `swarm` | `create_swarm`, `start_swarm`, `stop_swarm`, `delete_swarm`, `list_swarms` | Multi-agent swarms |
| `iot` | 8 tools | Smart home control via the Home Assistant plugin |
| `content` / `social` | 12 tools | Content Automation plugin (social posts, memes, videos) |
| `custom_flow` | `flow_<id>` | An agent's active flows (only inside that agent) |
| `mcp` | dynamic | MCP server tools |

---

## System Tools

### `run_command`
Execute any OS command in the system shell.

**Risk:** High | **Sandbox:** Yes

```python
run_command(
    command: str,                  # The shell command to execute
    timeout: int = 0,              # Max seconds to wait (0 = no limit). Ignored when background=True
    working_directory: str = None, # Optional working directory
    background: bool = False,      # Fire-and-forget (servers, tunnels, watchers)
)
```

**Notes:**
- Goes through the security policy first: always-blocked patterns, `blocked_patterns`, `blocked_paths`, and the execution mode (`confirmation` asks you, `auto` only allows whitelisted executables, `yolo` runs everything)
- Always use non-interactive flags: `--yes`, `-y`, `-f` where applicable
- Use `background=True` for long-running processes (dev servers, tunnels, file watchers)
- Output is truncated to `security.max_output_length` (50,000 chars by default)
- Output streams in real time into the conversation's terminal panel in the dashboard

**Examples:**
```
"list all files in my downloads folder"
→ run_command("ls ~/Downloads")

"start a local web server"
→ run_command("python -m http.server 8000", background=True)
```

---

### `run_python`
Execute Python code in a persistent interactive (Jupyter) kernel.

**Risk:** High

```python
run_python(
    code: str,            # Python code to execute (can be multiple lines)
    reset: bool = False,  # Restart the kernel (clears variables) before execution
)
```

**Notes:**
- State persists between calls — imports, variables, and functions survive
- Has access to all installed packages
- Matplotlib plots are captured automatically and sent to the chat as images

---

### `system_info`
Get information about the host system.

**Risk:** Low

```python
system_info(
    detail: str = "summary"  # "summary", "cpu", "memory", "disk", "network", "processes", "full"
)
```

---

## File Tools

### `read_file`
Read the contents of a file.

**Risk:** Medium

```python
read_file(
    path: str,            # Absolute or relative file path
    max_lines: int = 500  # 0 = read the entire file
)
```

### `write_file`
Create or overwrite a file (parent directories are created automatically).

**Risk:** High

```python
write_file(
    path: str,            # File path to write
    content: str,         # File content
    append: bool = False  # Append instead of overwrite
)
```

### `list_directory`
List files and directories at a path.

**Risk:** Low

```python
list_directory(
    path: str = ".",          # Directory path
    show_hidden: bool = False # Include hidden files
)
```

### `search_files`
Find files by name pattern in a directory tree.

**Risk:** Low

```python
search_files(
    directory: str,       # Root directory to search from
    pattern: str,         # File name pattern (e.g. "*.py", "config*")
    max_results: int = 50
)
```

### `send_file_to_chat`
Upload a local file so the user can download it from the chat. **Always included in tool selection.**

**Risk:** Low

```python
send_file_to_chat(
    path: str             # Path to the file to send
)
```

**Notes:**
- Must be called after generating a file — the file must exist on disk
- Returns an `/api/media/...` link; the dashboard renders image previews, and Telegram/Discord/WhatsApp receive the file as an attachment
- Always call this after generating any output file the user requested

---

## Code Editing Tools

Surgical editing tools for working on source code without rewriting whole files.

### `edit_file`
Replace an **exact** string in a file. Fails with a clear error if `old_string` is not found or matches more than once.

**Risk:** High

```python
edit_file(
    path: str,
    old_string: str,   # Must match character-for-character, including indentation
    new_string: str,
)
```

### `read_file_range`
Read a range of lines with line numbers (use it before `edit_file`).

**Risk:** Low

```python
read_file_range(
    path: str,
    start_line: int,     # 1-indexed
    end_line: int = -1,  # inclusive; -1 = end of file
)
```

### `grep_in_files`
Regex search inside files, with context lines.

**Risk:** Low

```python
grep_in_files(
    pattern: str,               # Python regex
    directory: str = ".",
    file_pattern: str = "*",    # e.g. "*.py"
    context_lines: int = 2,
    case_sensitive: bool = True,
    max_results: int = 30,
)
```

### `get_file_outline`
Structural outline of a source file (classes, functions, methods with line numbers). Python is parsed with the AST; JavaScript/TypeScript and other languages use regex.

**Risk:** Low

```python
get_file_outline(path: str)
```

### `run_linter`
Run a linter and return diagnostics — `ruff` for Python, `eslint` (if available) for JavaScript/TypeScript.

**Risk:** Medium

```python
run_linter(
    path: str,
    fix: bool = False   # Auto-fix safe issues (ruff --fix)
)
```

---

## Web Tools

### `web_search`
Search the web with DuckDuckGo.

**Risk:** Medium

```python
web_search(
    query: str,
    max_results: int = 5
)
```

### `get_webpage`
Fetch a URL and return its readable text (HTML stripped).

**Risk:** Medium

```python
get_webpage(
    url: str,
    max_length: int = 5000   # Max characters returned
)
```

### `browser_agent`
Control a persistent, headless Chromium browser (Playwright). The browser stays open between calls, so multi-step navigation works.

**Risk:** High

```python
browser_agent(
    action: str,        # "goto", "read_page", "click", "fill", "screenshot", "extract_html"
    url: str = "",      # for "goto"
    selector: str = "", # CSS selector for "click", "fill", "extract_html"
    value: str = "",    # text for "fill"
)
```

**Example:**
```
"find the price of the first result for 'mechanical keyboard' on example-shop.com"
→ browser_agent(action="goto", url="https://example-shop.com")
→ browser_agent(action="fill", selector="input[name=q]", value="mechanical keyboard")
→ browser_agent(action="click", selector="button[type=submit]")
→ browser_agent(action="read_page")
```

Disable it for deployments that don't need it with `features.browser_agent: false`.

---

## Media Tools

### `take_screenshot`
Capture the screen and save it as a media file.

**Risk:** Medium

```python
take_screenshot(
    monitor: int = 0    # 0 = all monitors, 1 = primary, 2 = second…
)
```

**Returns:** Path to the saved screenshot. Use `send_file_to_chat` to deliver it.

### `stitch_generate_ui`
Generate an HTML UI screen from a description with Google Stitch. Requires `STITCH_API_KEY` in `config/.env`.

**Risk:** Low

```python
stitch_generate_ui(
    prompt: str,                    # Detailed description of the UI
    device: str = "DESKTOP",        # "DESKTOP", "MOBILE", "TABLET"
    model: str = "GEMINI_3_1_PRO",  # or "GEMINI_3_FLASH"
)
```

---

## AI / Memory Tools

### `remember_note`
Store a fact or note in long-term vector memory (RAG).

**Risk:** Low

```python
remember_note(
    note: str           # Text to store in memory
)
```

### `search_memory`
Query long-term vector memory for relevant information.

**Risk:** Low

```python
search_memory(
    query: str,
    max_results: int = 5
)
```

### `save_customer_name`
Remember the customer's name for this conversation — kept even after an agent's memory TTL resets the context, so the agent can keep greeting them by name.

**Risk:** Low

```python
save_customer_name(name: str)
```

### `save_user_profile`
Used once during onboarding: saves the user's name, the assistant's name, behavior instructions, grammatical gender and language, and ends onboarding mode.

**Risk:** Low

```python
save_user_profile(user_name: str, assistant_name: str, behaviors: str, gender: str, language: str)
```

### `add_resurrection_path`
Add a folder to [Code Resurrection](./23-code-resurrection.md) indexing.

**Risk:** Low

```python
add_resurrection_path(path: str)   # absolute path
```

---

## Google Workspace Tools

All Google tools require OAuth2 credentials (`config/google_credentials.json`, see [Gmail Setup](./GMAIL_SETUP.md)).

### `gmail_read`
Read emails from Gmail. **Risk:** Medium

```python
gmail_read(
    query: str = "",       # Gmail search query (e.g. "from:boss@company.com", "is:unread")
    max_results: int = 10
)
```

### `gmail_send`
Send an email via Gmail. **Risk:** High

```python
gmail_send(
    to: str,
    subject: str,
    body: str
)
```

### `calendar_list`
List upcoming Google Calendar events. **Risk:** Low

```python
calendar_list(
    max_results: int = 10,
    days_ahead: int = 7
)
```

### `calendar_create`
Create a Google Calendar event. **Risk:** Medium

```python
calendar_create(
    summary: str,          # Event title
    start_time: str,       # ISO 8601 (e.g. "2026-06-15T14:00:00")
    end_time: str,         # ISO 8601
    description: str = "",
    location: str = ""
)
```

### `drive_list`
List files in Google Drive. **Risk:** Low

```python
drive_list(
    query: str = "",        # e.g. 'name contains "report"', 'mimeType="application/pdf"'
    max_results: int = 20
)
```

### `drive_search`
Search Drive files by name. **Risk:** Low

```python
drive_search(name: str)
```

### `drive_upload`
Upload a local file to Google Drive. **Risk:** Medium

```python
drive_upload(
    file_path: str,
    folder_id: str = ""   # Target folder (default: root)
)
```

### `youtube_search`
Search YouTube for videos. **Risk:** Low

```python
youtube_search(
    query: str,
    max_results: int = 5
)
```

---

## Agent & Flow Tools

### `create_agent`
Create an agent. **Risk:** Low

```python
create_agent(
    name: str,
    description: str,
    system_prompt: str,
    allowed_tools: str = "none"   # "all", "none", or a JSON list of tool names
)
```

### `list_agents`
List all agents with their tool policy and webhook URL. **Risk:** Low

### `delete_agent`
Delete an agent by ID. **Risk:** High

```python
delete_agent(agent_id: int)
```

### `create_or_update_agent_flow`
Create or update one of an agent's [flows](./28-agent-flows.md) by generating its graph directly — this is what the flow editor's chat panel uses.

**Risk:** Low

```python
create_or_update_agent_flow(
    name: str,
    graph_json: dict,        # {"nodes": [...], "edges": [...]}
    description: str = "",
    flow_id: int = None,     # update this flow instead of creating a new one
    agent_id: int = None,    # auto-detected when called inside an agent's chat
)
```

The graph must have exactly one `start` node and at least one `end` node; it is validated before saving.

---

## Scheduling Tools (Cron)

See [Cron Scheduler](./19-cron-scheduler.md).

| Tool | Risk | Parameters |
|------|------|-----------|
| `list_cron_jobs` | Low | — |
| `create_cron_job` | Medium | `name`, `cron_expr`, `action_type` (`analyze_patterns` / `run_skill` / `run_routine` / `custom_command` / `send_message`), `action_payload`, `description`, `enabled=True` |
| `update_cron_job` | Medium | `job_id` + any of `name`, `cron_expr`, `action_type`, `action_payload`, `description` |
| `toggle_cron_job` | Low | `job_id`, `enabled` (omit to flip) |
| `trigger_cron_job` | Medium | `job_id` — runs it now and returns the output |
| `delete_cron_job` | Medium | `job_id` |

---

## Swarm Tools

See [Swarms](./22-swarms.md).

| Tool | Risk | Parameters |
|------|------|-----------|
| `create_swarm` | Medium | `goal`, `name`, `global_model`, `context`, `auto_start=False` |
| `start_swarm` | Medium | `swarm_id` |
| `stop_swarm` | Medium | `swarm_id` |
| `delete_swarm` | High | `swarm_id` |
| `list_swarms` | Low | — |

---

## Platform Tools

Let the agent manage OpenACM itself from chat.

| Tool | Risk | What it does |
|------|------|-------------|
| `get_openacm_config` | Low | Active model, security mode, local router status and other key settings |
| `switch_llm_model(model)` | Low | Change the active model (LiteLLM string such as `anthropic/claude-sonnet-4-6`) |
| `update_security_mode(mode)` | Medium | Set `confirmation`, `auto` or `yolo` |
| `list_mcp_servers` | Low | Configured MCP servers and their status |
| `add_mcp_server(name, transport, command, args, url, api_key, auto_connect)` | Medium | Add an MCP server (`stdio`, `sse` or `streamable_http`) |
| `connect_mcp_server(name)` | Medium | Connect and load its tools |
| `disconnect_mcp_server(name)` | Low | Disconnect and unload its tools |
| `list_routines` | Low | Routines detected from your activity |
| `execute_routine(routine_id)` | Medium | Open the apps of a routine |

---

## Skill Tools

### `create_skill`
Generate a new skill with the LLM. Two phases: a preview first, then `apply=True` after you confirm.

**Risk:** Medium

```python
create_skill(
    name: str,               # kebab-case (e.g. "python-expert")
    description: str,        # 1-2 sentences
    use_cases: str,          # 2-3 example scenarios
    category: str = "custom",# "security", "development", "ai", "custom"
    apply: bool = False      # True only after the user confirmed the preview
)
```

### `toggle_skill`
Activate or deactivate a skill. **Risk:** Low

```python
toggle_skill(name: str)
```

### `list_skills`
List skills and their status. **Risk:** Low

```python
list_skills(show_inactive: bool = True)
```

### `delete_skill`
Permanently delete a custom skill (built-in skills can only be deactivated). **Risk:** High

```python
delete_skill(name: str, confirm: bool = False)   # confirm must be True
```

---

## IoT / Smart Home Tools (Home Assistant plugin)

Control smart home devices through a [Home Assistant](https://www.home-assistant.io/) instance — configure the URL and a Long-Lived Access Token from `/plugins` (see [Home Assistant Setup](./HOME_ASSISTANT_SETUP.md)). No per-vendor setup in OpenACM: Home Assistant's own integrations (Tuya, Xiaomi, LG WebOS, and hundreds more) already normalize every device behind one API.

### `ha_devices`
List entities, optionally filtered by domain and/or area.

```python
ha_devices(
    domain: str = "",   # e.g. "light", "switch", "climate", "cover", "media_player", "vacuum"
    area: str = ""      # e.g. "Sala" — see ha_areas()
)
```

### `ha_areas`
List Home Assistant areas/rooms.

### `ha_status`
Get the current state and attributes of one entity — by exact `entity_id` or friendly name.

```python
ha_status(
    entity_id: str       # e.g. "light.sala" or "Luz Sala"
)
```

### `ha_control`
Control one or more entities, or a whole Home Assistant area, in one call.

```python
ha_control(
    action: str,                    # turn_on, turn_off, toggle, set_brightness, set_color_temp,
                                     # set_color, set_temperature, open, close, stop, set_volume
    entity_id: str | list = None,   # single id, list of ids, or omit if using `area`
    area: str = "",                  # area id/slug — only with turn_on/turn_off/toggle
    brightness: int = None,          # 0-100, for set_brightness
    kelvin: int = None,              # 2000-6500, for set_color_temp
    red: int = None, green: int = None, blue: int = None,  # 0-255, for set_color
    temperature: float = None,       # for set_temperature
    volume: float = None,            # 0.0-1.0, for set_volume
)
```

### `ha_scenes` / `ha_activate_scene`
List scenes, and activate one by name.

```python
ha_activate_scene(
    name: str             # e.g. "Modo Noche"
)
```

### `ha_list_services` / `ha_call_service`
For device types `ha_control` doesn't cover (vacuum, fan, lock, alarm panel, humidifier…): discover a domain's services, then call one directly. `ha_call_service` is Medium risk.

```python
ha_list_services(domain: str)                                  # e.g. "vacuum"
ha_call_service(entity_id: str, service: str, data: dict = {}) # e.g. service="return_to_base"
```

**Example:**
```
"Apaga todas las luces de la sala"
→ ha_control(area="sala", action="turn_off")   # one call, whole area

"Apaga las luces, cierra las cortinas, y activa modo noche"
→ ha_control(entity_id=["light.sala", "light.cocina"], action="turn_off")
→ ha_control(entity_id="cover.sala", action="close")
→ ha_activate_scene("Modo Noche")
```

---

## Content & Social Tools (Content Automation plugin)

| Tool | Risk | What it does |
|------|------|-------------|
| `capture_content_moment` | Low | Screenshot the current moment, analyse it with vision and queue post drafts for approval |
| `generate_content_for_moment` | Low | Generate drafts for an already-captured moment |
| `list_content_moments` | Low | List captured moments (optionally by date) |
| `generate_meme` | Low | Meme image, `local` (Pillow) or `api` mode |
| `create_slideshow_video` | Medium | MP4 slideshow from images (ffmpeg) |
| `check_content_deps` | Medium | Check/install Pillow, ffmpeg, praw |
| `queue_content_for_approval` | Low | Manually queue a post |
| `list_pending_approvals` | Low | Posts waiting for approval |
| `save_social_credentials` | Medium | Store Facebook Page / Reddit credentials |
| `verify_social_credentials` | Low | Test stored credentials |
| `post_to_facebook` | High | Publish to a Facebook Page |
| `post_to_reddit` | High | Submit to a subreddit |

Nothing is published automatically — drafts wait for your approval on the **Content** page.

---

## MCP Tools

Tools from connected MCP servers are dynamically registered with the naming pattern:

```
mcp__{server_name}__{tool_name}
```

For example, a server named `filesystem` with a tool `read_file` would be accessible as:

```
mcp__filesystem__read_file
```

MCP tools appear in the Tool Registry and in the `/tools` dashboard page. They are selected via the same semantic similarity system as built-in tools.

See [MCP Integration](./13-mcp.md) for setup instructions.

---

## Tool modules that are not registered by default

`src/openacm/tools/` also contains `tool_creator.py` (`create_tool`, `edit_tool`, `delete_tool`), `list_tools.py` (`list_tools`) and `set_workspace.py` (`set_workspace`). In v0.4.7 these modules are **not** registered at startup (`app.py` does not call `register_module` on them), so the LLM cannot call them. Pinning a working directory is available through the `/workspace` slash command instead.

---

## Creating Custom Tools

Add a module with `@tool`-decorated async functions to `src/openacm/tools/` and register it in `app.py`, or ship it inside a [plugin](./24-plugins.md) (`get_tool_modules()`), which needs no core changes. See [Extending OpenACM](./17-extending.md) for the full guide.
