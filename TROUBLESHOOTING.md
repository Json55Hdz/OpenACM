# OpenACM Troubleshooting Guide

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
.venv\Scripts\uv run playwright install chromium
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
2. **Switch models** in `config/default.yaml`:
   ```yaml
   llm:
     default_model: "openai/gpt-4o"  # Try another model
   ```
3. **Verify your API key** in `config/.env`

---

## Problem: duckduckgo_search warning

```
RuntimeWarning: This package has been renamed to `ddgs`!
```

**Solution:** Already fixed in the latest version. If it persists:

```batch
.venv\Scripts\uv pip install ddgs>=7.0
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
