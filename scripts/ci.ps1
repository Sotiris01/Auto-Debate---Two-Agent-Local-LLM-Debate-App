<#
.SYNOPSIS
  One-shot CI: ruff lint + format check, mypy --strict, pytest. Non-zero exit
  on the first failure. Phase 7 exit-criterion script.

.PARAMETER SkipMypy
  Skip the mypy --strict step (useful when iterating on tests only).

.EXAMPLE
  ./scripts/ci.ps1
#>
[CmdletBinding()]
param(
    [switch]$SkipMypy
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    Write-Error "Could not find .venv Python at $python. Run scripts/bootstrap_env.py first."
    exit 2
}

function Invoke-Step {
    param([string]$Name, [scriptblock]$Body)
    Write-Host ""
    Write-Host "==> $Name" -ForegroundColor Cyan
    & $Body
    if ($LASTEXITCODE -ne 0) {
        Write-Host "FAILED: $Name (exit $LASTEXITCODE)" -ForegroundColor Red
        exit $LASTEXITCODE
    }
}

Invoke-Step "ruff check ." {
    & $python -m ruff check .
}

Invoke-Step "ruff format --check ." {
    & $python -m ruff format --check .
}

if (-not $SkipMypy) {
    Invoke-Step "mypy --strict (config/prompts/llm/engine)" {
        & $python -m mypy
    }
}

Invoke-Step "pytest -q" {
    & $python -m pytest -q
}

Write-Host ""
Write-Host "All CI checks passed." -ForegroundColor Green
exit 0
