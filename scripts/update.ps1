Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "  OpenACM - Update" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host ""

$REPO_ROOT = Split-Path -Parent $PSScriptRoot
Set-Location $REPO_ROOT

# ── 1. Git pull (only if this is a git checkout) ────────────────────────────
$IsGitRepo = $false
if ((Test-Path ".git") -and (Get-Command "git" -ErrorAction SilentlyContinue)) {
    git rev-parse --is-inside-work-tree 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0) { $IsGitRepo = $true }
}

$Stashed = $false
if ($IsGitRepo) {
    # Autostash uncommitted changes so the pull doesn't blow up
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

    Write-Host "[*] Fetching latest changes..." -ForegroundColor Yellow
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
    Write-Host "[!] This is not a git checkout — skipping 'git pull'." -ForegroundColor Yellow
    Write-Host "    If you want to update the code, download the latest version" -ForegroundColor White
    Write-Host "    from GitHub and extract it over this folder, then re-run update." -ForegroundColor White
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

$choice = Read-Host "Restart OpenACM now? (Y/n)"
if ($choice -eq "" -or $choice -match "^[yY]") {
    Write-Host ""
    Write-Host "Launching OpenACM..." -ForegroundColor Green
    Write-Host ""
    powershell -ExecutionPolicy Bypass -File "$PSScriptRoot\run.ps1"
} else {
    Write-Host "Run 'openacm start' to launch." -ForegroundColor Cyan
    Read-Host "Press Enter to close"
}
