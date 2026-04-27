<#
.SYNOPSIS
    One-shot launcher for Auto Debate — checks the environment, then starts
    the Streamlit app.

.DESCRIPTION
    Runs the existing diagnostic scripts (``scripts/check_system.py`` and
    ``scripts/check_ollama.py``) against the project's virtualenv, prints
    their summaries, and — if both pass cleanly — boots the Streamlit UI on
    http://localhost:8501.

    Exit codes from the helpers are interpreted as follows:

        check_system.py
            0 — OK
            1 — warnings (project should still work) → continue
            2 — fatal (project will not run)         → abort

        check_ollama.py
            0 — READY                                → continue
            1 — MODEL_MISSING                        → abort with hint
            2 — OLLAMA_DOWN                          → abort with hint
            3 — MISSING_OLLAMA                       → abort with hint

.PARAMETER Port
    Port to bind the Streamlit server to. Default: 8501.

.PARAMETER SkipChecks
    Skip the diagnostic scripts and go straight to launching the app.

.EXAMPLE
    .\run.ps1
    .\run.ps1 -Port 8602
    .\run.ps1 -SkipChecks
#>

[CmdletBinding()]
param(
    [int]$Port = 8501,
    [switch]$SkipChecks
)

$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot

# --- locate the venv Python --------------------------------------------------

$venvPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $venvPython)) {
    Write-Host ''
    Write-Host '[run.ps1] No virtualenv found at .venv\' -ForegroundColor Red
    Write-Host '         Create it first with:' -ForegroundColor Red
    Write-Host '           .\scripts\bootstrap.ps1' -ForegroundColor Yellow
    Write-Host '         (or follow the manual steps in README.md)' -ForegroundColor Red
    exit 10
}

function Write-Section {
    param([string]$Title)
    Write-Host ''
    Write-Host ('=' * 72) -ForegroundColor DarkGray
    Write-Host "  $Title" -ForegroundColor Cyan
    Write-Host ('=' * 72) -ForegroundColor DarkGray
}

# --- diagnostics -------------------------------------------------------------

if (-not $SkipChecks) {
    Write-Section 'Step 1/3 — System check (scripts/check_system.py)'
    & $venvPython (Join-Path $PSScriptRoot 'scripts\check_system.py')
    $sysExit = $LASTEXITCODE
    switch ($sysExit) {
        0 { Write-Host '[run.ps1] System check: OK' -ForegroundColor Green }
        1 { Write-Host '[run.ps1] System check: warnings — continuing.' -ForegroundColor Yellow }
        default {
            Write-Host "[run.ps1] System check failed (exit $sysExit). Aborting." -ForegroundColor Red
            exit $sysExit
        }
    }

    Write-Section 'Step 2/3 — Ollama check (scripts/check_ollama.py)'
    & $venvPython (Join-Path $PSScriptRoot 'scripts\check_ollama.py')
    $ollamaExit = $LASTEXITCODE
    switch ($ollamaExit) {
        0 { Write-Host '[run.ps1] Ollama check: READY' -ForegroundColor Green }
        1 {
            Write-Host '[run.ps1] Model not pulled. Run: ollama pull <model>' -ForegroundColor Red
            exit $ollamaExit
        }
        2 {
            Write-Host '[run.ps1] Ollama server is not running. Start it (e.g. `ollama serve`) and retry.' -ForegroundColor Red
            exit $ollamaExit
        }
        3 {
            Write-Host '[run.ps1] Ollama is not installed or not on PATH. See https://ollama.com/download' -ForegroundColor Red
            exit $ollamaExit
        }
        default {
            Write-Host "[run.ps1] Ollama check failed (exit $ollamaExit). Aborting." -ForegroundColor Red
            exit $ollamaExit
        }
    }
} else {
    Write-Host '[run.ps1] -SkipChecks specified; skipping diagnostics.' -ForegroundColor Yellow
}

# --- launch ------------------------------------------------------------------

Write-Section "Step 3/3 — Starting Streamlit on http://localhost:$Port"
Write-Host '[run.ps1] Press Ctrl+C in this window to stop the app.' -ForegroundColor DarkGray
Write-Host ''

& $venvPython -m streamlit run (Join-Path $PSScriptRoot 'app.py') `
    --server.port=$Port `
    --server.headless=true `
    --browser.gatherUsageStats=false

exit $LASTEXITCODE
