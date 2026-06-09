Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "  OpenACM - Update" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host ""

$REPO_ROOT = Split-Path -Parent $PSScriptRoot
Set-Location $REPO_ROOT

# ── 1. Pull latest code ─────────────────────────────────────────────────────
# If this is a git checkout, use `git pull`. If it's a manual zip install,
# download the latest zip from GitHub and unpack it on top. User files
# (config\.env, data\, .venv\) are never in the zip so they're safe.
$ZipUrl = "https://github.com/Json55Hdz/OpenACM/archive/refs/heads/main.zip"

$IsGitRepo = $false
if ((Test-Path ".git") -and (Get-Command "git" -ErrorAction SilentlyContinue)) {
    git rev-parse --is-inside-work-tree 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0) { $IsGitRepo = $true }
}

$Stashed = $false
if ($IsGitRepo) {
    $dirty = $false
    git diff --quiet HEAD 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) { $dirty = $true }
    $porcelain = git status --porcelain 2>$null
    if ($porcelain) { $dirty = $true }

    if ($dirty) {
        Write-Host "[*] Local changes detected — stashing them temporarily..." -ForegroundColor Yellow
        $ts = [int][double]::Parse((Get-Date -UFormat %s))
        git stash push -u -m "openacm-update-autostash-$ts" 2>&1 | Out-Null
        if ($LASTEXITCODE -eq 0) { $Stashed = $true }
    }

    Write-Host "[*] Fetching latest changes via git..." -ForegroundColor Yellow
    git pull --ff-only
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[ERROR] git pull failed." -ForegroundColor Red
        Write-Host "    Probably your branch has diverged from the remote." -ForegroundColor White
        Write-Host "    Resolve it manually, then run update again." -ForegroundColor White
        if ($Stashed) {
            Write-Host "[*] Restoring your local changes..." -ForegroundColor Yellow
            git stash pop 2>&1 | Out-Null
        }
        pause
        exit 1
    }
    Write-Host "[OK] Repository updated." -ForegroundColor Green

    if ($Stashed) {
        Write-Host "[*] Restoring your local changes..." -ForegroundColor Yellow
        git stash pop 2>&1 | Out-Null
        if ($LASTEXITCODE -ne 0) {
            Write-Host "[!] Could not auto-restore stash — there may be conflicts." -ForegroundColor Yellow
            Write-Host "    Run 'git stash list' and resolve manually." -ForegroundColor White
        }
    }
} else {
    Write-Host "[*] Not a git checkout — downloading latest from GitHub..." -ForegroundColor Yellow

    $stamp = Get-Random
    $TmpZip = Join-Path $env:TEMP "openacm-update-$stamp.zip"
    $TmpDir = Join-Path $env:TEMP "openacm-update-$stamp"
    New-Item -ItemType Directory -Force -Path $TmpDir | Out-Null

    try {
        # TLS 1.2 for older Win10 PowerShell
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest -Uri $ZipUrl -OutFile $TmpZip -UseBasicParsing
    } catch {
        Write-Host "[ERROR] Failed to download the latest version." -ForegroundColor Red
        Write-Host "    URL: $ZipUrl" -ForegroundColor White
        Write-Host "    Details: $_" -ForegroundColor White
        pause
        exit 1
    }

    try {
        Expand-Archive -Path $TmpZip -DestinationPath $TmpDir -Force
    } catch {
        Write-Host "[ERROR] Failed to extract the downloaded archive." -ForegroundColor Red
        Remove-Item -Recurse -Force $TmpZip, $TmpDir -ErrorAction SilentlyContinue
        pause
        exit 1
    }

    # GitHub zips wrap everything in an inner folder like "OpenACM-main"
    $InnerDir = Get-ChildItem $TmpDir -Directory | Select-Object -First 1
    if (-not $InnerDir) {
        Write-Host "[ERROR] Downloaded archive looked empty." -ForegroundColor Red
        Remove-Item -Recurse -Force $TmpZip, $TmpDir -ErrorAction SilentlyContinue
        pause
        exit 1
    }

    Write-Host "[*] Applying new files (config\.env, data\, .venv\ are preserved)..." -ForegroundColor Yellow
    Copy-Item -Path (Join-Path $InnerDir.FullName "*") -Destination $REPO_ROOT -Recurse -Force
    Remove-Item -Recurse -Force $TmpZip, $TmpDir -ErrorAction SilentlyContinue
    Write-Host "[OK] Latest version downloaded and applied." -ForegroundColor Green
}
Write-Host ""

# ── 2. Sync Python dependencies ──────────────────────────────────────────────
Write-Host "[*] Syncing Python dependencies..." -ForegroundColor Yellow
if (Get-Command "uv" -ErrorAction SilentlyContinue) {
    uv pip install -e . --quiet
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[!] uv had issues, falling back to pip..." -ForegroundColor Yellow
        if (Test-Path ".venv\Scripts\pip.exe") { .venv\Scripts\pip.exe install -e . -q }
    }
} elseif (Test-Path ".venv\Scripts\pip.exe") {
    .venv\Scripts\pip.exe install -e . -q
} else {
    Write-Host "[ERROR] No virtual environment found. Run 'openacm install' first." -ForegroundColor Red
    pause
    exit 1
}
Write-Host "[OK] Python dependencies synced." -ForegroundColor Green
Write-Host ""

# ── 3. Rebuild frontend ──────────────────────────────────────────────────────
$FrontendBuilt = $true
if (!(Get-Command "node" -ErrorAction SilentlyContinue)) {
    Write-Host "[!] Node.js not found, skipping frontend build." -ForegroundColor Yellow
    $FrontendBuilt = $false
} elseif (!(Test-Path "frontend")) {
    Write-Host "[!] frontend/ folder not found, skipping build." -ForegroundColor Yellow
    $FrontendBuilt = $false
} else {
    Write-Host "[*] Rebuilding frontend..." -ForegroundColor Yellow
    Set-Location frontend
    npm install --silent 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Set-Location $REPO_ROOT
        Write-Host "[ERROR] npm install failed. Frontend was NOT updated." -ForegroundColor Red
        pause
        exit 1
    }
    npm run build
    if ($LASTEXITCODE -ne 0) {
        Set-Location $REPO_ROOT
        Write-Host "[ERROR] Frontend build failed. Frontend was NOT updated." -ForegroundColor Red
        pause
        exit 1
    }
    Set-Location $REPO_ROOT

    if (!(Test-Path "src\openacm\web\static")) {
        New-Item -ItemType Directory -Force -Path "src\openacm\web\static" | Out-Null
    } else {
        Get-ChildItem "src\openacm\web\static" -Recurse -Force | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
    }
    Copy-Item -Recurse -Force "frontend\dist\*" "src\openacm\web\static\"
    Write-Host "[OK] Frontend rebuilt." -ForegroundColor Green
}
Write-Host ""

Write-Host "==========================================" -ForegroundColor Green
Write-Host "  Update Complete!" -ForegroundColor Green
Write-Host "==========================================" -ForegroundColor Green
if (-not $FrontendBuilt) {
    Write-Host "  (Note: frontend was not rebuilt — see warnings above.)" -ForegroundColor Yellow
}
Write-Host ""
# Restart is handled by the caller (update.bat), which launches run.bat after this script exits 0.
