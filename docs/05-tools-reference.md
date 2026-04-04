# Tools Reference

OpenACM ships with 42+ built-in tools across 10 categories. Tools are Python async functions decorated with `@tool`. They receive injected context (`_sandbox`, `_event_bus`, `_brain`, `_user_id`, `_channel_id`, `_channel_type`) alongside their declared parameters.

---

## Tool Categories

| Category | Tools | Description |
|----------|-------|-------------|
| `system` | 2 | OS command execution |
| `file` | 5 | File system operations |
| `web` | 2 | Web search and browsing |
| `media` | 1 | Screen capture |
| `ai` | 2 | Long-term memory (RAG) |
| `google` | 7 | Gmail, Calendar, Drive, YouTube |
| `blender` | 6 | 3D modeling via Blender |
| `meta` | 5 | Create tools, skills, agents |
| `mcp` | dynamic | MCP server tools |
| `iot` | 9 | Smart home device control |
| `general` | 2 | Always-available (system info, file to chat) |

---

## System Tools

### `run_command`
Execute any OS command in the system shell.

**Risk:** High | **Sandbox:** Yes

```python
run_command(
    command: str,        # The shell command to execute
    background: bool = False,  # Run without waiting for completion (for servers, tunnels)
    timeout: int = 120,  # Seconds before forceful termination
)
```

**Notes:**
- Always use non-interactive flags: `--yes`, `-y`, `-f` where applicable
- Use `background=True` for long-running processes (dev servers, tunnels, file watchers)
- Output is truncated to 50KB
- Returns combined stdout + stderr
- CI=true is auto-injected to suppress interactive prompts

**Examples:**
```
"list all files in my downloads folder"
→ run_command("ls ~/Downloads")

"start a local web server"
→ run_command("python -m http.server 8000", background=True)

"install requests library"
→ run_command("pip install requests -y")
```

---

### `run_python`
Execute Python code in a persistent interactive kernel.

**Risk:** High | **Sandbox:** Yes

```python
run_python(
    code: str,           # Python code to execute
    timeout: int = 60,   # Execution timeout in seconds
)
```

**Notes:**
- State persists between calls in the same session — imports, variables, and functions survive
- Has access to all installed packages
- Can generate files and images
- Supports async code via `asyncio.run()`

**Examples:**
```
"calculate the fibonacci sequence up to 1000"
→ run_python("fibs = [0,1]; [fibs.append(fibs[-1]+fibs[-2]) for _ in range(12)]; print(fibs)")

"generate a bar chart of my file sizes"
→ run_python("""
import matplotlib.pyplot as plt
import os
...
""")
```

---

## File Tools

### `read_file`
Read the contents of a file.

**Risk:** Low

```python
read_file(
    path: str,           # Absolute or relative file path
    max_lines: int = 500 # Limit output lines
)
```

### `write_file`
Create or overwrite a file.

**Risk:** Medium

```python
write_file(
    path: str,           # File path to write
    content: str,        # File content
    mode: str = "w"      # "w" (overwrite) or "a" (append)
)
```

### `list_directory`
List files and directories at a path.

**Risk:** Low

```python
list_directory(
    path: str = ".",     # Directory path
    recursive: bool = False  # Include subdirectories
)
```

### `search_files`
Find files matching a pattern.

**Risk:** Low

```python
search_files(
    pattern: str,        # Glob pattern (e.g., "**/*.py", "*.txt")
    directory: str = "." # Root directory to search from
)
```

### `send_file_to_chat`
Attach a file to the chat response. **Always included in tool selection.**

**Risk:** Low

```python
send_file_to_chat(
    file_path: str,      # Path to the file to send
    display_name: str = "" # Optional display name for the file
)
```

**Notes:**
- Must be called after generating a file — the file must exist on disk
- The frontend automatically renders image previews for `.png`, `.jpg`, `.gif`, `.webp`
- Always call this after generating any output file the user requested

---

## Web Tools

### `web_search`
Search the web and return relevant results.

**Risk:** Low

```python
web_search(
    query: str,          # Search query
    num_results: int = 5 # Number of results to return
)
```

### `get_webpage`
Fetch and parse the content of a webpage.

**Risk:** Low

```python
get_webpage(
    url: str,            # Full URL to fetch
    extract_text: bool = True  # Extract readable text vs raw HTML
)
```

---

## Media Tools

### `take_screenshot`
Capture the current screen.

**Risk:** Medium

```python
take_screenshot(
    region: str = "full",     # "full" or "x,y,width,height"
    save_path: str = ""       # Optional custom save path
)
```

**Returns:** Path to the saved screenshot file (in workspace). Use `send_file_to_chat` to deliver it.

---

## AI / Memory Tools

### `remember_note`
Store a fact or note in long-term vector memory (RAG).

**Risk:** Low

```python
remember_note(
    content: str,        # Text to store in memory
    tags: list = []      # Optional tags for organization
)
```

### `search_memory`
Query long-term vector memory for relevant information.

**Risk:** Low

```python
search_memory(
    query: str,          # What to search for
    num_results: int = 3 # Number of relevant fragments to return
)
```

---

## Browser Agent

### `browser_agent`
Control a real Chromium browser using Playwright.

**Risk:** High | **Sandbox:** Yes

```python
browser_agent(
    task: str,           # Natural language description of what to do in the browser
    url: str = "",       # Optional starting URL
    headless: bool = True # Run without showing browser window
)
```

**Capabilities:**
- Navigate to any URL
- Click buttons, fill forms, select dropdowns
- Extract text and data from pages
- Take screenshots of specific elements
- Wait for dynamic content to load
- Log in to websites (with credentials provided in the task)
- Scrape structured data from multiple pages

**Examples:**
```
"log into my GitHub and check my notifications"
→ browser_agent("Go to github.com/login, log in with user 'john' password 'xxx', then check notifications", url="https://github.com")

"find the cheapest iPhone 16 on Amazon"
→ browser_agent("Search Amazon for iPhone 16, sort by price low to high, return the first 5 results with prices", url="https://amazon.com")
```

---

## System Info Tool

### `system_info`
Get detailed information about the host system.

**Risk:** Low

```python
system_info(
    category: str = "all"  # "cpu", "memory", "disk", "gpu", "battery", "processes", "all"
)
```

**Returns:** JSON with system stats including:
- CPU usage, cores, frequency
- RAM total/used/available
- Disk partitions and usage
- GPU info (if available)
- Battery status (if laptop)
- Top running processes

---

## Google Workspace Tools

All Google tools require OAuth2 credentials configured (see [Configuration](./11-configuration.md)).

### `gmail_read`
Read emails from Gmail inbox.

```python
gmail_read(
    max_results: int = 10,     # Number of emails to fetch
    query: str = "",           # Gmail search query (e.g. "from:boss@company.com")
    include_body: bool = True  # Include email body text
)
```

### `gmail_send`
Send an email via Gmail.

```python
gmail_send(
    to: str,             # Recipient email address
    subject: str,        # Email subject
    body: str,           # Email body (plain text or HTML)
    cc: str = "",        # CC recipients (comma-separated)
    attachments: list = [] # File paths to attach
)
```

### `calendar_list`
List Google Calendar events.

```python
calendar_list(
    days_ahead: int = 7,       # How many days to look ahead
    calendar_id: str = "primary" # Calendar to query
)
```

### `calendar_create`
Create a Google Calendar event.

```python
calendar_create(
    title: str,          # Event title
    start: str,          # ISO 8601 datetime (e.g. "2025-06-15T14:00:00")
    end: str,            # ISO 8601 datetime
    description: str = "", # Event description
    attendees: list = [] # Email addresses of attendees
)
```

### `drive_list`
List files in Google Drive.

```python
drive_list(
    folder_id: str = "root",  # Folder to list (default: root)
    max_results: int = 20
)
```

### `drive_upload`
Upload a file to Google Drive.

```python
drive_upload(
    file_path: str,      # Local path to the file
    folder_id: str = "", # Target folder (default: root)
    file_name: str = ""  # Override filename
)
```

### `youtube_search`
Search YouTube for videos.

```python
youtube_search(
    query: str,          # Search query
    max_results: int = 5 # Number of results
)
```

---

## Blender 3D Tools

Control Blender via its Python API (`bpy`). Requires Blender installed and in PATH.

### `blender_start`
Launch Blender in background mode.

```python
blender_start(
    scene_file: str = "" # Optional .blend file to open
)
```

### `blender_exec`
Execute Python (`bpy`) code in the running Blender instance.

```python
blender_exec(
    code: str            # Python code using the bpy module
)
```

### `blender_run_script`
Execute a Python script file in Blender.

```python
blender_run_script(
    script_path: str     # Path to the .py script file
)
```

### `blender_export`
Export the current Blender scene.

```python
blender_export(
    file_path: str,      # Output path (.glb, .obj, .stl, .fbx)
    format: str = "glb"  # Export format
)
```

### `blender_info`
Get info about the current Blender scene.

```python
blender_info(
    detail: str = "summary" # "summary", "objects", "materials", "cameras"
)
```

### `blender_stop`
Close the Blender instance.

```python
blender_stop()
```

**Example workflow:**
```
"Create a chess pawn in Blender and export it as GLB"
→ blender_start()
→ blender_exec("""
    import bpy
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete()
    # Create pawn shape...
""")
→ blender_export("/workspace/pawn.glb")
→ blender_stop()
→ send_file_to_chat("/workspace/pawn.glb")
```

---

## Meta Tools (Self-Extension)

### `create_tool`
Create a new Python tool at runtime.

**Risk:** High

```python
create_tool(
    name: str,           # Tool identifier (snake_case)
    description: str,    # What the tool does
    parameters: dict,    # JSON Schema for parameters
    code: str,           # Python async function body
    category: str = "general",  # Tool category
    apply: bool = False  # False = validate only; True = register live
)
```

**Two-phase workflow:**
1. Call with `apply=False` → validates code, runs tests, shows preview
2. User confirms → call with `apply=True` → registers in live registry, no restart needed

### `create_skill`
Create a new skill (behavior instruction) as a markdown file.

```python
create_skill(
    name: str,           # Skill name (kebab-case)
    description: str,    # One-line description
    content: str,        # Markdown instructions for the LLM
    category: str = "custom" # Skill category folder
)
```

### `toggle_skill`
Enable or disable a skill.

```python
toggle_skill(
    name: str,           # Skill name
    active: bool         # True to enable, False to disable
)
```

### `list_skills`
List all available skills.

```python
list_skills(
    filter: str = "all"  # "all", "active", "inactive", "builtin", "custom"
)
```

### `delete_skill`
Permanently delete a skill.

```python
delete_skill(
    name: str            # Skill name to delete
)
```

---

## IoT / Smart Home Tools

Control smart home devices via local LAN. Supports Tuya, Xiaomi Mi Home (miio), and LG WebOS.

### `iot_scan`
Discover devices on the local network.

```python
iot_scan(
    protocols: list = ["tuya", "miio", "webos"] # Protocols to scan
)
```

### `iot_devices`
List registered devices.

```python
iot_devices(
    type: str = "all"    # "all", "light", "cover", "tv", "vacuum", "switch", "sensor"
)
```

### `iot_control`
Send a command to a device.

```python
iot_control(
    device_id: str,      # Device identifier
    command: str,        # Command: "on", "off", "toggle", "set"
    value: any = None    # Command value (brightness 0-100, color "red", etc.)
)
```

### `iot_status`
Query the current state of a device.

```python
iot_status(
    device_id: str       # Device identifier
)
```

### `iot_rename`
Give a device a friendly name.

```python
iot_rename(
    device_id: str,      # Current device ID
    name: str            # New friendly name
)
```

**Example:**
```
"Turn off all the lights in the living room"
→ iot_devices(type="light") → finds devices tagged "living_room"
→ iot_control("light_001", "off")
→ iot_control("light_002", "off")
→ iot_control("light_003", "off")
```

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

## Creating Custom Tools

You can ask OpenACM to create a new tool for itself:

```
You: Create a tool called "weather" that fetches the current weather for a given city using the Open-Meteo API (no API key required)
```

OpenACM will:
1. Write the Python async function
2. Validate it (syntax, imports, security)
3. Show you a preview and ask for confirmation
4. Register it live in the tool registry

The tool is immediately available for subsequent requests without restarting.

See [Extending OpenACM](./17-extending.md) for the full guide.
