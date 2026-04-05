# CLI Providers

Connect OpenACM to AI models through locally-installed CLI tools — no API key required.

---

## Why CLI providers?

Some providers (Anthropic, Google) restrict third-party API access or require billing even when you have a personal account. Their official CLI tools (`claude`, `gemini`) authenticate via your browser session, bypassing API key requirements entirely.

CLI providers let you use these models at no extra cost, authenticated as your own account.

---

## How it works

1. OpenACM formats the full conversation (messages + tool schemas) as structured text
2. The text is piped to the CLI binary via `stdin`
3. The CLI response is parsed — tool calls use `<tool_call>` XML tags
4. The result is returned in the same format as any other provider

All existing features work: tool execution, memory, file ops, browser control, cron jobs, etc.

---

## Setup

### 1. Install the CLI

**Claude:**
```bash
npm install -g @anthropic-ai/claude-code
claude          # first-run login flow
```

**Gemini:**
```bash
npm install -g @google/gemini-cli
gemini          # first-run login flow
```

**OpenCode:**
```bash
npm install -g opencode-ai
opencode        # first-run login flow
```

### 2. Restart OpenACM

That's it. OpenACM auto-detects binaries on PATH at startup.

```bash
python -m openacm
```

### 3. Select the provider in Settings

Go to **Settings → Model** — the CLI provider appears automatically with its model chip. Click it to activate.

---

## Advanced: override defaults

To change timeout, args, or any other option, add an explicit entry in `config/default.yaml` under `llm.providers`. The YAML entry takes precedence over auto-detection.

```yaml
llm:
  default_provider: "cli_claude"
  providers:
    cli_claude:
      type: "cli"
      binary: "claude"
      args: ["--print"]
      default_model: "claude"
      timeout: 600       # longer timeout for complex tasks
```

---

## Configuration options

| Key | Description | Default |
|-----|-------------|---------|
| `type` | Must be `"cli"` | — |
| `binary` | CLI executable name (must be on PATH) | `"claude"` |
| `args` | Arguments passed to the binary | `["--print"]` |
| `default_model` | Display name shown in the UI | binary name |
| `timeout` | Max seconds to wait for a response | `300` |

---

## Tool calling protocol

Since CLI tools don't natively support OpenAI tool schemas, OpenACM injects tool definitions as plain text before the last user message:

```
[AVAILABLE TOOLS]
You can call tools by outputting <tool_call> tags with JSON:
<tool_call>{"name": "tool_name", "arguments": {"arg": "value"}}</tool_call>

Available tools:
- run_command: Execute a shell command
    • command (string, required): ...
...
[/AVAILABLE TOOLS]

[USER]
List the files in the current directory.

[ASSISTANT]
```

The model responds with `<tool_call>` blocks that OpenACM parses and executes.

---

## Limitations

- **No streaming** — CLI providers return the full response at once
- **Token counts are estimated** — (~4 chars/token), not exact
- **Login required** — if the CLI session expires, restart it manually
- **Performance** — CLI startup adds ~1–2s overhead per request
- **Multi-modal** — images in conversation history are replaced with `[image omitted]`
