"""
scripts/install_defaults.py — One-shot setup orchestrator.

Phase 0 (Step 0.6) of the Auto Debate roadmap.

Runs the Phase-0 checker scripts in order and installs whatever is missing
that *can* safely be installed without administrator rights:

    1. check_system.py      — hardware / OS sanity (informational, never fails
                              the orchestrator unless FATAL).
    2. bootstrap_env.py     — create .venv and install Python deps if absent.
    3. check_ollama.py      — probe Ollama state.
    4. ollama pull <model>  — pull the configured model when missing
                              (only step that downloads several GB; user is
                              prompted unless --yes / -y is passed).

Things this script will NEVER do automatically:

    * Install the Ollama binary (requires elevation / GUI installer on
      Windows; printed instructions instead).
    * Start the Ollama server when it is stopped (printed instructions
      instead).

Usage:
    python scripts/install_defaults.py            # interactive
    python scripts/install_defaults.py --yes      # auto-confirm model pull
    python scripts/install_defaults.py --dev      # also install dev deps

Exit codes:
    0  — everything ready (READY).
    1  — at least one prerequisite still missing; see printed remediation.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"

# Make scripts/ importable so we can call check_ollama directly to avoid
# spawning yet another Python process for the final probe.
sys.path.insert(0, str(SCRIPTS_DIR))


# --- ANSI helpers ------------------------------------------------------------

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


def section(title: str) -> None:
    bar = "=" * 60
    print(f"\n{bar}\n{bold(title)}\n{bar}")


# --- subprocess helpers ------------------------------------------------------


def run_python_script(script: Path, *args: str) -> int:
    """Run ``python <script> <args>`` with the *current* interpreter."""
    cmd = [sys.executable, str(script), *args]
    print(f"  $ {' '.join(cmd)}")
    return subprocess.run(cmd, check=False).returncode


def run_command(cmd: list[str]) -> int:
    """Run an arbitrary external command (e.g. ``ollama pull``)."""
    print(f"  $ {' '.join(cmd)}")
    try:
        return subprocess.run(cmd, check=False).returncode
    except FileNotFoundError:
        print(red(f"  command not found: {cmd[0]}"))
        return 127


# --- Ollama-specific helpers (re-uses check_ollama.py logic) -----------------


def probe_ollama() -> tuple[int, str, str]:
    """Run check_ollama.main() in-process and return (code, host, model)."""
    import check_ollama  # type: ignore[import-not-found]

    host = os.getenv("OLLAMA_HOST", check_ollama.DEFAULT_HOST)
    model = os.getenv("MODEL_NAME", check_ollama.DEFAULT_MODEL)
    code = check_ollama.main()
    return code, host, model


def resolve_ollama_cmd() -> str | None:
    """Return a usable ``ollama`` command (PATH name or absolute fallback)."""
    import check_ollama  # type: ignore[import-not-found]

    return check_ollama.find_ollama_binary()


def confirm(prompt: str, *, assume_yes: bool) -> bool:
    if assume_yes:
        print(f"{prompt} [auto-yes]")
        return True
    try:
        answer = input(f"{prompt} [y/N]: ").strip().lower()
    except EOFError:
        return False
    return answer in {"y", "yes"}


# --- main --------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run Phase-0 checks and install missing defaults.",
    )
    parser.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="Auto-confirm potentially-large downloads (e.g. ollama pull).",
    )
    parser.add_argument(
        "--dev",
        action="store_true",
        help="Pass --dev to bootstrap_env.py to install dev dependencies.",
    )
    parser.add_argument(
        "--skip-system",
        action="store_true",
        help="Skip the hardware/OS sanity check.",
    )
    parser.add_argument(
        "--skip-bootstrap",
        action="store_true",
        help="Skip the venv bootstrap step.",
    )
    args = parser.parse_args()

    # 1. System check (informational; warnings allowed, fatal aborts)
    if not args.skip_system:
        section("[1/4] System check")
        rc = run_python_script(SCRIPTS_DIR / "check_system.py")
        if rc == 2:
            print(red(bold("\nFATAL system requirement not met. Aborting.")))
            return 1
        if rc == 1:
            print(yellow("System check produced warnings — continuing."))
        else:
            print(green("System check passed."))

    # 2. Bootstrap venv + Python deps
    if not args.skip_bootstrap:
        section("[2/4] Virtualenv + Python dependencies")
        boot_args: list[str] = []
        if args.dev:
            boot_args.append("--dev")
        rc = run_python_script(SCRIPTS_DIR / "bootstrap_env.py", *boot_args)
        if rc != 0:
            print(red(bold("\nBootstrap failed. Fix the error above and re-run.")))
            return 1

    # 3. Ollama probe
    section("[3/4] Ollama probe")
    code, host, model = probe_ollama()

    if code == 3:
        print(red(bold("\nOllama is not installed.")))
        print("Install it (printed instructions above), then re-run this script.")
        return 1

    if code == 2:
        print(
            red(
                bold(
                    "\nOllama binary present but server unreachable. "
                    "Start it and re-run this script.",
                ),
            ),
        )
        return 1

    # 4. Model pull (only when MODEL_MISSING)
    if code == 1:
        section(f"[4/4] Pulling model '{model}'")
        if not confirm(
            f"Download '{model}' from {host}? This is several GB.",
            assume_yes=args.yes,
        ):
            print(yellow("Skipped. Pull manually with: ollama pull " + model))
            return 1

        ollama_cmd = resolve_ollama_cmd() or "ollama"
        rc = run_command([ollama_cmd, "pull", model])
        if rc != 0:
            print(red(bold(f"\n'ollama pull {model}' failed (exit {rc}).")))
            return 1

        # Re-probe to confirm.
        code, host, model = probe_ollama()
        if code != 0:
            print(red(bold("\nModel pull reported success but probe is not READY.")))
            return 1
    else:
        section("[4/4] Model")
        print(green(f"Model '{model}' already available."))

    section("All defaults installed")
    print(green(bold("READY — you can now run: streamlit run app.py")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
