# scripts/bootstrap.ps1 — Windows PowerShell wrapper for bootstrap_env.py
#
# Usage:
#   .\scripts\bootstrap.ps1            # runtime deps only
#   .\scripts\bootstrap.ps1 -Dev       # also install dev deps
#   .\scripts\bootstrap.ps1 -Recreate  # nuke .venv and start fresh

[CmdletBinding()]
param(
    [switch]$Dev,
    [switch]$Recreate
)

$ErrorActionPreference = 'Stop'

# Resolve repo root (parent of this script's directory)
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

# Locate a system Python (>=3.10). Prefer 'py -3', fall back to 'python'.
function Resolve-Python {
    if (Get-Command 'py' -ErrorAction SilentlyContinue) {
        return @('py', '-3')
    }
    if (Get-Command 'python' -ErrorAction SilentlyContinue) {
        return @('python')
    }
    throw "Python 3.10+ not found on PATH. Install from https://www.python.org/downloads/"
}

$pythonCmd = Resolve-Python

$bootstrapArgs = @('scripts/bootstrap_env.py')
if ($Dev)      { $bootstrapArgs += '--dev' }
if ($Recreate) { $bootstrapArgs += '--recreate' }

& $pythonCmd[0] @($pythonCmd[1..($pythonCmd.Length - 1)] + $bootstrapArgs)
exit $LASTEXITCODE
