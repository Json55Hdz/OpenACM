Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "  OpenACM Tier-1 Autonomous Agent Setup" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host ""

# Check Python version
$pythonVersion = python --version 2>&1
if ($pythonVersion -match "Python 3\.(\d+)\.(\d+)") {
    $minorVersion = [int]$matches[1]
    if ($minorVersion -lt 12) {
        Write-Host "[!] Warning: Python 3.$minorVersion detected." -ForegroundColor Yellow
        Write-Host "    OpenACM requires Python 3.12 or higher." -ForegroundColor Yellow
        Write-Host "    The installer will try to install Python 3.12 via uv..." -ForegroundColor Yellow
        Write-Host ""
    } else {
        Write-Host "[OK] Python 3.$minorVersion detected." -ForegroundColor Green
    }
} else {
    Write-Host "[!] Could not detect Python version." -ForegroundColor Yellow
}

# Check if uv is installed, if not, download it
if (!(Get-Command "uv" -ErrorAction SilentlyContinue)) {
    Write-Host "[*] Installing 'uv' (fast Python package manager)..." -ForegroundColor Yellow
    try {
        Invoke-RestMethod -Uri "https://astral.sh/uv/install.ps1" | Invoke-Expression
        # uv installs to .local\bin on newer versions, .cargo\bin on older — add both
        foreach ($p in @("$env:USERPROFILE\.local\bin", "$env:USERPROFILE\.cargo\bin", "$HOME\.local\bin", "$HOME\.cargo\bin")) {
            if (Test-Path $p) { $env:Path = "$p;$env:Path" }
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

# Install Python 3.12 via uv
Write-Host "[*] Setting up Python 3.12 environment..." -ForegroundColor Yellow
try {
    uv python install 3.12 --quiet
    if ($LASTEXITCODE -ne 0) {
        throw "uv python install failed"
    }
} catch {
    Write-Host "[!] Could not install Python 3.12 via uv." -ForegroundColor Yellow
    Write-Host "    Trying to continue with the current version..." -ForegroundColor Yellow
}

# Create virtual environment
Write-Host "[*] Creating virtual environment..." -ForegroundColor Yellow

# Remove old venv if it has no pip
if (Test-Path ".venv\Scripts\python.exe") {
    if (!(Test-Path ".venv\Scripts\pip.exe")) {
        Write-Host "[!] Existing venv without pip detected. Recreating..." -ForegroundColor Yellow
        Remove-Item -Recurse -Force .venv
    }
}

try {
    # Create venv with seed packages (includes pip)
    uv venv --seed
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
    Write-Host "   2. Try running: uv pip install -e . --verbose" -ForegroundColor Yellow
    Write-Host "   3. If the error persists, install Visual C++ Build Tools" -ForegroundColor Yellow
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
    exit 0  # setup.bat will launch run.bat
} else {
    Write-Host ""
    Write-Host "To start later, double-click 'run.bat'" -ForegroundColor Cyan
    Write-Host ""
    Read-Host "Press Enter to close"
    exit 1  # setup.bat will just close
}
