param([string]$Command = "help")

$REPO_ROOT = Split-Path -Parent $PSScriptRoot
Set-Location $REPO_ROOT

function Show-Help {
    Write-Host ""
    Write-Host "  OpenACM CLI" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "  Usage: openacm <command>" -ForegroundColor White
    Write-Host ""
    Write-Host "  Commands:" -ForegroundColor White
    Write-Host "    install   First-time setup (create venv, install deps, build frontend)" -ForegroundColor Gray
    Write-Host "    update    Pull latest changes + sync deps + rebuild frontend" -ForegroundColor Gray
    Write-Host "    start     Start OpenACM" -ForegroundColor Gray
    Write-Host "    stop      Stop OpenACM" -ForegroundColor Gray
    Write-Host "    status    Check if OpenACM is running" -ForegroundColor Gray
    Write-Host "    repair    Reinstall Python dependencies (no git pull)" -ForegroundColor Gray
    Write-Host ""
}

function Get-OpenACMPid {
    try {
        $conn = Get-NetTCPConnection -LocalPort 47821 -State Listen -ErrorAction SilentlyContinue
        if ($conn) { return $conn.OwningProcess }
    } catch {}
    $line = netstat -ano 2>$null | Select-String "47821.*LISTENING"
    if ($line) { return ($line.ToString().Trim() -split '\s+')[-1] }
    return $null
}

switch ($Command.ToLower()) {
    "install" {
        powershell -ExecutionPolicy Bypass -File "$PSScriptRoot\setup.ps1"
    }
    "update" {
        powershell -ExecutionPolicy Bypass -File "$PSScriptRoot\update.ps1"
    }
    "start" {
        powershell -ExecutionPolicy Bypass -File "$PSScriptRoot\run.ps1"
    }
    "stop" {
        $pid = Get-OpenACMPid
        if ($pid) {
            Write-Host "[*] Stopping OpenACM (PID $pid)..." -ForegroundColor Yellow
            Stop-Process -Id $pid -Force -ErrorAction SilentlyContinue
            Write-Host "[OK] OpenACM stopped." -ForegroundColor Green
        } else {
            Write-Host "[!] OpenACM is not running." -ForegroundColor Yellow
        }
    }
    "status" {
        $pid = Get-OpenACMPid
        if ($pid) {
            $proc = Get-Process -Id $pid -ErrorAction SilentlyContinue
            Write-Host "[OK] OpenACM is running  (PID $pid  •  $($proc.CPU)s CPU)" -ForegroundColor Green
            Write-Host "     Web: http://127.0.0.1:47821" -ForegroundColor Cyan
        } else {
            Write-Host "[--] OpenACM is not running." -ForegroundColor Yellow
        }
    }
    "repair" {
        Write-Host "[*] Reinstalling Python dependencies..." -ForegroundColor Yellow
        if (Get-Command "uv" -ErrorAction SilentlyContinue) {
            uv pip install -e .
        } elseif (Test-Path ".venv\Scripts\pip.exe") {
            .venv\Scripts\pip.exe install -e .
        } else {
            Write-Host "[ERROR] No virtual environment found. Run 'openacm install' first." -ForegroundColor Red
            exit 1
        }
        Write-Host "[OK] Repair complete. Run 'openacm start' to launch." -ForegroundColor Green
    }
    default {
        if ($Command -ne "help" -and $Command -ne "--help" -and $Command -ne "-h") {
            Write-Host "[!] Unknown command: $Command" -ForegroundColor Red
        }
        Show-Help
    }
}
