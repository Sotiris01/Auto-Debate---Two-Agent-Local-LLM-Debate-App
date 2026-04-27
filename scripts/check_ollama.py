"""
scripts/check_ollama.py — Ollama installation, server, and model check.

Phase 0 (Step 0.2) of the Auto Debate roadmap.

Reports one of four states and exits with a corresponding code:

    READY           (0)  — Ollama installed, server reachable, model present
    MODEL_MISSING   (1)  — server up, but the requested model is not pulled
    OLLAMA_DOWN     (2)  — binary present, server unreachable
    MISSING_OLLAMA  (3)  — ``ollama`` binary not found on PATH

This script does NOT auto-install Ollama and does NOT auto-pull the model.
Both are heavy operations that must be a deliberate user choice.

Reads ``MODEL_NAME`` and ``OLLAMA_HOST`` from the environment / .env if
``python-dotenv`` is available; otherwise falls back to defaults.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import sys
import urllib.error
import urllib.request

DEFAULT_HOST = "http://localhost:11434"
DEFAULT_MODEL = "gemma3:4b"


# --- minimal color helpers (duplicated to keep this script standalone) -------

_USE_COLOR = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


def _c(code: str, text: str) -> str:
    return f"\x1b[{code}m{text}\x1b[0m" if _USE_COLOR else text


def green(s: str) -> str:
    return _c("32", s)


def yellow(s: str) -> str:
    return _c("33", s)


def red(s: str) -> str:
    return _c("31", s)


def bold(s: str) -> str:
    return _c("1", s)


# --- env loading -------------------------------------------------------------


def _load_env() -> None:
    """Best-effort .env loading; silent if dotenv is not installed yet."""
    try:
        from dotenv import load_dotenv  # type: ignore[import-not-found]
    except ImportError:
        return
    load_dotenv(override=False)


# --- install hint per OS -----------------------------------------------------


def install_hint() -> str:
    sysname = platform.system()
    if sysname == "Windows":
        return (
            "Install Ollama for Windows:\n"
            "    winget install Ollama.Ollama\n"
            "  or download the installer: https://ollama.com/download/windows"
        )
    if sysname == "Darwin":
        return (
            "Install Ollama for macOS:\n"
            "    brew install --cask ollama\n"
            "  or download the dmg: https://ollama.com/download/mac"
        )
    if sysname == "Linux":
        return (
            "Install Ollama for Linux:\n"
            "    curl -fsSL https://ollama.com/install.sh | sh"
        )
    return "See https://ollama.com/download"


# --- checks ------------------------------------------------------------------


def _windows_fallback_paths() -> list[str]:
    """Common locations the Ollama Windows installer drops the binary into.

    The installer updates the *user* PATH, but already-open shells keep the
    old PATH, so ``shutil.which`` misses it. Check the well-known install
    folders directly as a fallback.
    """
    candidates: list[str] = []
    local = os.environ.get("LOCALAPPDATA")
    if local:
        candidates.append(os.path.join(local, "Programs", "Ollama", "ollama.exe"))
    program_files = os.environ.get("ProgramFiles")
    if program_files:
        candidates.append(os.path.join(program_files, "Ollama", "ollama.exe"))
    return candidates


def find_ollama_binary() -> str | None:
    """Return the resolved path to the ``ollama`` executable, or None.

    Looks on PATH first; on Windows, falls back to the standard installer
    locations because the installer modifies PATH only for *new* shells.
    """
    found = shutil.which("ollama")
    if found:
        return found
    if platform.system() == "Windows":
        for path in _windows_fallback_paths():
            if os.path.isfile(path):
                return path
    return None


def fetch_tags(host: str, timeout: float = 2.0) -> list[dict] | None:
    """Return the parsed ``models`` list from /api/tags, or None on failure."""
    url = host.rstrip("/") + "/api/tags"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError):
        return None
    models = data.get("models")
    return models if isinstance(models, list) else []


def model_present(models: list[dict], model_name: str) -> bool:
    """Match by full name and by base (no tag), to be forgiving."""
    target = model_name.strip()
    base = target.split(":", 1)[0]
    for m in models:
        name = (m.get("name") or "").strip()
        if name == target:
            return True
        if name.split(":", 1)[0] == base and ":" not in target:
            return True
    return False


# --- main --------------------------------------------------------------------


def main() -> int:
    _load_env()
    host = os.getenv("OLLAMA_HOST", DEFAULT_HOST)
    model = os.getenv("MODEL_NAME", DEFAULT_MODEL)

    print(bold("\nAuto Debate — Ollama Check"))
    print(f"  host : {host}")
    print(f"  model: {model}\n")

    # 1. Try the API first — it's the only check that actually matters for
    #    the app. A reachable server proves Ollama is installed AND running,
    #    independent of whether ``ollama.exe`` is on the current shell's PATH
    #    (the Windows installer updates PATH only for new shells).
    models = fetch_tags(host)

    if models is not None:
        if not model_present(models, model):
            installed = ", ".join(m.get("name", "?") for m in models) or "(none)"
            print(yellow(bold("STATE: MODEL_MISSING")))
            print(f"  Installed models: {installed}")
            print("  Pull the configured model:")
            print(f"      ollama pull {model}")
            print()
            return 1

        print(green(bold("STATE: READY")))
        print(f"  Model '{model}' is available on {host}.\n")
        return 0

    # 2. API unreachable — distinguish "not installed" from "installed but
    #    server stopped" so the user gets the right remediation hint.
    binary = find_ollama_binary()
    if binary is None:
        print(red(bold("STATE: MISSING_OLLAMA")))
        print(install_hint())
        print()
        return 3

    print(red(bold("STATE: OLLAMA_DOWN")))
    print(f"  Found ollama binary at: {binary}")
    print(f"  But could not reach {host}/api/tags")
    print("  Start the server (in another terminal):")
    print("      ollama serve")
    print("  Or, on Windows, launch the 'Ollama' app from the Start menu.")
    print()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
