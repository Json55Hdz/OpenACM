# OpenACM Troubleshooting Guide

> Most examples below are for Windows (`.bat`, `.venv\Scripts\...`). On macOS/Linux use `./setup.sh`, `./run.sh` and `.venv/bin/...`.

## First checks

- **Logs:** `data/logs/` (turn on **Configuration → Security → Debug mode**, or `POST /api/config/debug_mode`, for DEBUG-level logs)
- **Traces:** the **Traces** page shows every agentic iteration, tool timing and the error of a failed request
- **Health:** `curl http://127.0.0.1:47821/api/ping` → `{"ok": true}`
- **Nothing happens when the agent wants to run a command?** In the default `confirmation` mode the command waits for your approval in the dashboard. In `auto` mode, commands not listed in `whitelisted_commands` are rejected.

## Problem: "Gets stuck after a command"

If OpenACM executes a command or tool and then freezes (no response), try these solutions:

### Solution 1: Verify virtual environment Python

The most common problem is Windows using the system Python instead of the .venv one.

**Check which Python is being used:**
```batch
.venv\Scripts\python.exe --version
python --version
```

If the second command shows a different version, your PATH is misconfigured.

**Fix (temporary):**
```batch
set PATH=%CD%\.venv\Scripts;%PATH%
python -m openacm
```

**Fix (permanent):**
1. Search for "Environment variables" in the Start menu
2. Edit the user "Path" variable
3. Remove or move to the end any Python paths that are NOT .venv

### Solution 2: Temporarily disable antivirus

Some antivirus programs (Windows Defender, McAfee, etc.) block:
- Subprocess execution
- Playwright/Chromium
- WebSocket connections

**Try:** Temporarily disable your antivirus and run OpenACM.

### Solution 3: Run as Administrator

1. Right-click on `run.bat`
2. "Run as administrator"
3. Check if it works better

### Solution 4: Clean corrupted installation

```batch
:: 1. Stop OpenACM if it's running
:: 2. Delete temporary folders
rmdir /s /q .venv
rmdir /s /q data\media
rmdir /s /q data\vectordb

:: 3. Reinstall
call setup.bat
```

### Solution 5: Verify installed Python versions

```batch
:: List all Python installations
where python
where python3
where uv

:: If there are multiple versions, force the project's one
.venv\Scripts\python.exe -m openacm
```

---

## Problem: Browser timeout errors

```
Page.goto: Timeout 30000ms exceeded
```

### Causes:
1. Slow internet connection
2. Website is blocked by firewall
3. Playwright is not properly installed

### Solutions:

**Reinstall Playwright:**
```batch
uv run playwright install chromium
:: or
.venv\Scripts\playwright install chromium
```

**Check connection:**
```batch
ping google.com
```

**Disable proxy/firewall:**
Some corporate networks block Playwright.

---

## Problem: LLM 500 Error (opencode.ai)

```
Server error '500 Internal Server Error'
```

### This is NOT a problem with your installation

A 500 error means the OpenCode.ai server had an internal issue. This may be due to:
- Server maintenance
- Temporary overload
- Issues with the specific model

### Solutions:

1. **Wait a few minutes** and try again
2. **Switch models** — in chat: `/model openai/gpt-4o`, in the dashboard (**Configuration → Model**), or in `config/local.yaml`:
   ```yaml
   llm:
     default_provider: openai
     providers:
       openai:
         default_model: "gpt-4o"
   ```
3. **Verify your API key** in `config/.env` (`OPENCODE_GO_API_KEY` for OpenCode Go)

Transient 5xx errors and `429 Too Many Requests` are already retried automatically with exponential backoff; you only see the error once retries are exhausted.

---

## Problem: duckduckgo_search warning

```
RuntimeWarning: This package has been renamed to `ddgs`!
```

**Solution:** Already fixed in the latest version. If it persists:

```batch
uv pip install "ddgs>=7.0"
```

---

## Problem: "ModuleNotFoundError" when running

### Cause: The virtual environment was not activated correctly

### Quick fix:
```batch
:: Instead of just run.bat, execute:
call .venv\Scripts\activate.bat
python -m openacm
```

### Permanent fix:
Edit `run.bat` and ensure it uses absolute paths:
```batch
set "PYTHON=%~dp0.venv\Scripts\python.exe"
"%PYTHON%" -m openacm
```

---

## Problem: Dashboard shows "Unauthorized"

The token in your browser doesn't match `DASHBOARD_TOKEN` in `config/.env` (e.g. after regenerating it). Log out and paste the current token — it is printed in the terminal at startup.

---

## Problem: Docker container is running but the dashboard doesn't load

The compose file publishes port 8080, but OpenACM listens on `127.0.0.1:47821` unless told otherwise. Create `config/local.yaml` with:

```yaml
web:
  host: 0.0.0.0
  port: 8080
```

and restart the container. See [Docker](./32-docker.md).

---

## Problem: WhatsApp webhook doesn't verify / messages are ignored

See the troubleshooting table in [WhatsApp Setup](./WHATSAPP_SETUP.md). The most common causes are a verify token mismatch and an empty/wrong `WHATSAPP_APP_SECRET` (logs show `signature invalid`).

---

## Verification Checklist

Before reporting an issue, verify:

- [ ] You ran `setup.bat` fully without errors
- [ ] You have Python 3.12+ installed (check with `python --version`)
- [ ] The `config/.env` file exists and has your API keys
- [ ] Playwright is installed: `.venv\Scripts\playwright --version`
- [ ] No antivirus is blocking processes
- [ ] You have a stable internet connection
- [ ] You tried running as administrator (just to test)

---

## How to Report Issues

If nothing works, run this and share the output:

```batch
echo === SYSTEM INFO === > debug.txt
echo. >> debug.txt
echo Python in PATH: >> debug.txt
where python >> debug.txt 2>&1
echo. >> debug.txt
echo Python version: >> debug.txt
python --version >> debug.txt 2>&1
echo. >> debug.txt
echo Version in .venv: >> debug.txt
.venv\Scripts\python.exe --version >> debug.txt 2>&1
echo. >> debug.txt
echo Environment variables: >> debug.txt
echo PATH=%PATH% >> debug.txt
echo. >> debug.txt
echo === .ENV CONTENTS === >> debug.txt
type config\.env >> debug.txt 2>&1
```

Share the `debug.txt` file (remove your API keys first!).
