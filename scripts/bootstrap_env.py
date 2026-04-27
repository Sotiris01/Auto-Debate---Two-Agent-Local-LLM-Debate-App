"""
scripts/bootstrap_env.py — Create / refresh the project virtualenv.

Phase 0 (Step 0.3) of the Auto Debate roadmap.

Steps performed:

    1. Create .venv/ if it does not already exist (using the current
       interpreter via ``python -m venv``).
    2. Resolve the venv's Python executable (cross-platform).
    3. Upgrade pip inside the venv.
    4. Install (or refresh) packages from requirements.txt.
    5. Optionally install requirements-dev.txt when --dev is passed.
    6. Print the activation command for the host shell.

Idempotent: safe to re-run. Stops with a non-zero exit code on any failure.

Only depends on the standard library so it can run BEFORE any package is
installed.
"""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
VENV_DIR = REPO_ROOT / ".venv"
REQ_FILE = REPO_ROOT / "requirements.txt"
REQ_DEV_FILE = REPO_ROOT / "requirements-dev.txt"


def venv_python(venv_dir: Path) -> Path:
    if platform.system() == "Windows":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def activate_hint(venv_dir: Path) -> str:
    if platform.system() == "Windows":
        ps1 = venv_dir / "Scripts" / "Activate.ps1"
        bat = venv_dir / "Scripts" / "activate.bat"
        return f"PowerShell : {ps1}\n  cmd.exe    : {bat}"
    return f"  bash/zsh   : source {venv_dir / 'bin' / 'activate'}"


def run(cmd: list[str | os.PathLike[str]], *, label: str) -> None:
    print(f"\n>>> {label}")
    print("    $ " + " ".join(str(c) for c in cmd))
    result = subprocess.run([str(c) for c in cmd], check=False)
    if result.returncode != 0:
        print(f"!!! {label} failed (exit {result.returncode})", file=sys.stderr)
        sys.exit(result.returncode)


def ensure_venv() -> Path:
    py = venv_python(VENV_DIR)
    if VENV_DIR.exists() and py.exists():
        print(f"= venv already exists at {VENV_DIR}")
        return py
    if VENV_DIR.exists() and not py.exists():
        # Broken venv — wipe it.
        print(f"! removing broken venv at {VENV_DIR}")
        shutil.rmtree(VENV_DIR)
    run(
        [sys.executable, "-m", "venv", VENV_DIR],
        label=f"creating virtualenv at {VENV_DIR}",
    )
    if not py.exists():
        print(f"!!! venv creation did not produce {py}", file=sys.stderr)
        sys.exit(1)
    return py


def upgrade_pip(py: Path) -> None:
    run(
        [py, "-m", "pip", "install", "--upgrade", "pip"],
        label="upgrading pip",
    )


def install_requirements(py: Path, req_path: Path, label: str) -> None:
    if not req_path.exists():
        print(f"!!! missing {req_path}", file=sys.stderr)
        sys.exit(1)
    run(
        [py, "-m", "pip", "install", "-r", req_path],
        label=label,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Bootstrap the Auto Debate venv.")
    parser.add_argument(
        "--dev",
        action="store_true",
        help="Also install requirements-dev.txt (ruff, pytest, mypy).",
    )
    parser.add_argument(
        "--recreate",
        action="store_true",
        help="Delete .venv/ and start fresh.",
    )
    args = parser.parse_args()

    if args.recreate and VENV_DIR.exists():
        print(f"! recreate flag set — removing {VENV_DIR}")
        shutil.rmtree(VENV_DIR)

    py = ensure_venv()
    upgrade_pip(py)
    install_requirements(py, REQ_FILE, "installing runtime requirements")
    if args.dev:
        install_requirements(py, REQ_DEV_FILE, "installing dev requirements")

    print("\n" + "=" * 60)
    print("Bootstrap complete.")
    print("Activate the virtualenv:")
    print(activate_hint(VENV_DIR))
    print("\nNext steps:")
    print("  python scripts/check_system.py")
    print("  python scripts/check_ollama.py")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
