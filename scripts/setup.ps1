$REPO_ROOT = Split-Path -Parent $PSScriptRoot
Set-Location $REPO_ROOT

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "  OpenACM Tier-1 Autonomous Agent Setup" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host ""

# ── 1. Bootstrap uv (installs its own Python — no system Python required) ───
# We intentionally skip checking for a system `python` here. uv can install a
# standalone Python 3.12 even when none exists on the machine, which is the
# cleanest path on a fresh PC.
if (!(Get-Command "uv" -ErrorAction SilentlyContinue)) {
    Write-Host "[*] Installing 'uv' (fast Python package manager)..." -ForegroundColor Yellow
    try {
        Invoke-RestMethod -Uri "https://astral.sh/uv/install.ps1" | Invoke-Expression
        # uv installs to .local\bin on newer versions, .cargo\bin on older — add both
        foreach ($p in @("$env:USERPROFILE\.local\bin", "$env:USERPROFILE\.cargo\bin", "$HOME\.local\bin", "$HOME\.cargo\bin")) {
            if (Test-Path $p) { $env:Path = "$p;$env:Path" }
        }
        if (!(Get-Command "uv" -ErrorAction SilentlyContinue)) {
            Write-Host "[ERROR] uv was installed but is not in PATH for this session." -ForegroundColor Red
            Write-Host "    Open a new PowerShell window and re-run setup." -ForegroundColor White
            pause
            exit 1
        }
        Write-Host "[OK] 'uv' installed successfully." -ForegroundColor Green
    } catch {
        Write-Host "[ERROR] Failed to install uv. Install it manually from https://docs.astral.sh/uv/" -ForegroundColor Red
        pause
        exit 1
    }
} else {
    Write-Host "[OK] 'uv' is already installed." -ForegroundColor Green
}

# ── 2. Install Python 3.12 via uv (standalone — no system Python needed) ────
Write-Host "[*] Installing standalone Python 3.12 via uv..." -ForegroundColor Yellow
uv python install 3.12
if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERROR] uv could not install Python 3.12." -ForegroundColor Red
    Write-Host "    Check your internet connection or proxy settings, then re-run." -ForegroundColor White
    pause
    exit 1
}
Write-Host "[OK] Python 3.12 ready." -ForegroundColor Green

# ── 3. Check Visual C++ Build Tools (needed for some native deps) ───────────
# We don't hard-fail because most modern wheels are precompiled, but we warn
# loudly so a later 'uv pip install' failure makes sense to the user.
$buildToolsFound = $false
$vswhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
if (Test-Path $vswhere) {
    $vc = & $vswhere -latest -products * `
        -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 `
        -property installationPath 2>$null
    if ($vc) { $buildToolsFound = $true }
}
# Fallback heuristics
if (-not $buildToolsFound) {
    $vsRoots = @(
        "${env:ProgramFiles}\Microsoft Visual Studio\2022\BuildTools\VC",
        "${env:ProgramFiles(x86)}\Microsoft Visual Studio\2022\BuildTools\VC",
        "${env:ProgramFiles}\Microsoft Visual Studio\2019\BuildTools\VC",
        "${env:ProgramFiles(x86)}\Microsoft Visual Studio\2019\BuildTools\VC"
    )
    foreach ($r in $vsRoots) { if (Test-Path $r) { $buildToolsFound = $true; break } }
}

if (-not $buildToolsFound) {
    Write-Host "[!] Visual C++ Build Tools were not detected." -ForegroundColor Yellow
    Write-Host "    Most dependencies have prebuilt wheels and will work without them," -ForegroundColor White
    Write-Host "    but if 'uv pip install' fails with a 'cl.exe' or 'MSVC' error you" -ForegroundColor White
    Write-Host "    will need to install them." -ForegroundColor White

    if (Get-Command "winget" -ErrorAction SilentlyContinue) {
        $ans = Read-Host "    Install Visual Studio 2022 Build Tools via winget now? (y/N)"
        if ($ans -match "^[yY]") {
            Write-Host "[*] Installing Build Tools (this can take several minutes)..." -ForegroundColor Yellow
            winget install --id Microsoft.VisualStudio.2022.BuildTools `
                --override "--passive --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended" `
                --accept-source-agreements --accept-package-agreements
            if ($LASTEXITCODE -eq 0) {
                Write-Host "[OK] Build Tools installed." -ForegroundColor Green
            } else {
                Write-Host "[!] winget install returned $LASTEXITCODE — continuing anyway." -ForegroundColor Yellow
            }
        }
    } else {
        Write-Host "    Manual download: https://visualstudio.microsoft.com/visual-cpp-build-tools/" -ForegroundColor White
    }
} else {
    Write-Host "[OK] Visual C++ Build Tools detected." -ForegroundColor Green
}

# ── 4. Create virtual environment ───────────────────────────────────────────
Write-Host "[*] Creating virtual environment..." -ForegroundColor Yellow

# Remove old venv if it has no pip
if (Test-Path ".venv\Scripts\python.exe") {
    if (!(Test-Path ".venv\Scripts\pip.exe")) {
        Write-Host "[!] Existing venv without pip detected. Recreating..." -ForegroundColor Yellow
        Remove-Item -Recurse -Force .venv
    }
}

try {
    # Create venv with seed packages (includes pip) using the uv-managed Python
    uv venv --seed --python 3.12
    if ($LASTEXITCODE -ne 0) {
        throw "uv venv failed"
    }

    # Verify pip exists
    if (!(Test-Path ".venv\Scripts\pip.exe")) {
        Write-Host "[!] pip not found, installing..." -ForegroundColor Yellow
        .venv\Scripts\python.exe -m ensurepip --upgrade
    }

    Write-Host "[OK] Virtual environment created with pip." -ForegroundColor Green
} catch {
    Write-Host "[ERROR] Failed to create virtual environment." -ForegroundColor Red
    Write-Host "   Error: $_" -ForegroundColor Red
    pause
    exit 1
}

# ── 5. Config (.env) ────────────────────────────────────────────────────────
Write-Host "[*] Checking configuration (.env)..." -ForegroundColor Yellow
if (!(Test-Path "config\.env")) {
    if (Test-Path "config\.env.example") {
        Copy-Item "config\.env.example" "config\.env"
        Write-Host "[OK] 'config\.env' created from example." -ForegroundColor Green
    } else {
        New-Item -ItemType Directory -Force -Path "config" | Out-Null
        "# OpenACM Configuration" | Out-File -FilePath "config\.env" -Encoding utf8
        Write-Host "[OK] 'config\.env' created (empty)." -ForegroundColor Green
    }
}

# ── 6. Install project deps ─────────────────────────────────────────────────
Write-Host "[*] Installing all project dependencies (this may take a few minutes)..." -ForegroundColor Yellow
try {
    uv pip install -e . 2>&1 | ForEach-Object {
        if ($_ -match "error|ERROR|failed") {
            Write-Host "   [!] $_" -ForegroundColor Yellow
        } else {
            Write-Host "   $_" -ForegroundColor Gray
        }
    }

    if ($LASTEXITCODE -ne 0) {
        throw "pip install failed with exit code $LASTEXITCODE"
    }
    Write-Host "[OK] Dependencies installed." -ForegroundColor Green
} catch {
    Write-Host "[ERROR] Failed to install dependencies." -ForegroundColor Red
    Write-Host "   Details: $_" -ForegroundColor Red
    Write-Host ""
    Write-Host "   Suggestions:" -ForegroundColor Yellow
    Write-Host "   1. Check your internet connection" -ForegroundColor Yellow
    Write-Host "   2. If you see 'cl.exe' or 'MSVC' errors: install Visual C++ Build Tools" -ForegroundColor Yellow
    Write-Host "      https://visualstudio.microsoft.com/visual-cpp-build-tools/" -ForegroundColor Yellow
    Write-Host "   3. Try running: uv pip install -e . --verbose" -ForegroundColor Yellow
    pause
    exit 1
}

# Install optional media-processing extras (MarkItDown converters + audio)
Write-Host "[*] Installing file-processing extras (MarkItDown)..." -ForegroundColor Yellow
try {
    uv pip install "markitdown[docx,xlsx,pptx,audio-transcription]" 2>&1 | Out-Null
    Write-Host "[OK] MarkItDown extras installed." -ForegroundColor Green
} catch {
    Write-Host "[!] Could not install MarkItDown extras (non-critical)." -ForegroundColor Yellow
}

# Install AI/ML enhancement libraries
Write-Host "[*] Installing AI enhancement libraries (chonkie, docling, instructor)..." -ForegroundColor Yellow
try {
    uv pip install "chonkie[sentence]>=1.0" "docling>=2.0" "instructor>=1.0" 2>&1 | Out-Null
    Write-Host "[OK] AI enhancement libraries installed." -ForegroundColor Green
} catch {
    Write-Host "[!] Could not install some AI enhancement libraries (non-critical)." -ForegroundColor Yellow
}

Write-Host "[*] Downloading browsers for the Web Agent (Playwright)..." -ForegroundColor Yellow
try {
    uv run playwright install chromium 2>&1 | ForEach-Object {
        Write-Host "   $_" -ForegroundColor Gray
    }
    if ($LASTEXITCODE -eq 0) {
        Write-Host "[OK] Chromium installed." -ForegroundColor Green
    } else {
        Write-Host "[!] Playwright install returned code $LASTEXITCODE, but continuing..." -ForegroundColor Yellow
    }
} catch {
    Write-Host "[!] Warning: Could not install Playwright automatically." -ForegroundColor Yellow
    Write-Host "    You can install it manually later: uv run playwright install chromium" -ForegroundColor Yellow
}

# Final verification
Write-Host ""
Write-Host "[*] Verifying installation..." -ForegroundColor Yellow
try {
    $testImport = uv run python -c "import openacm; print('OK')" 2>&1
    if ($testImport -match "OK") {
        Write-Host "[OK] OpenACM imports correctly." -ForegroundColor Green
    } else {
        Write-Host "[!] Warning: There were issues verifying the installation." -ForegroundColor Yellow
    }
} catch {
    Write-Host "[!] Could not verify the installation, but continuing..." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "==========================================" -ForegroundColor Green
Write-Host "  Setup Complete!" -ForegroundColor Green
Write-Host "==========================================" -ForegroundColor Green
Write-Host ""
Write-Host "  Before starting, make sure to configure" -ForegroundColor White
Write-Host "  your API keys in: config\.env" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Docs:" -ForegroundColor White
Write-Host "  - README.md - Quick start guide" -ForegroundColor Gray
Write-Host "  - SKILLS_TOOLS_GUIDE.md - How to create skills and tools" -ForegroundColor Gray
Write-Host ""
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host ""

$choice = Read-Host "Launch OpenACM now? (Y/n)"
if ($choice -eq "" -or $choice -match "^[yY]") {
    Write-Host ""
    Write-Host "Launching OpenACM..." -ForegroundColor Green
    Write-Host ""
    powershell -ExecutionPolicy Bypass -File "$PSScriptRoot\run.ps1"
} else {
    Write-Host ""
    Write-Host "To start later, run: openacm start" -ForegroundColor Cyan
    Write-Host ""
    Read-Host "Press Enter to close"
}
