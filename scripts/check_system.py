"""
scripts/check_system.py — Hardware / OS / Python sanity check.

Phase 0 (Step 0.1) of the Auto Debate roadmap.

Reports CPU, RAM, disk, OS, Python version, GPU backend hints, and basic
network reachability for Ollama-related endpoints.

Exit codes:
    0  — all checks passed (system OK)
    1  — at least one warning (project should still work)
    2  — fatal: project will not run on this machine

Run standalone, before any virtualenv exists. Only depends on the standard
library; ``psutil`` is used if available but not required.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
import urllib.error
import urllib.request

# --- tiny ANSI color helpers (no external dep) -------------------------------

_USE_COLOR = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


def _c(code: str, text: str) -> str:
    if not _USE_COLOR:
        return text
    return f"\x1b[{code}m{text}\x1b[0m"


def green(s: str) -> str:
    return _c("32", s)


def yellow(s: str) -> str:
    return _c("33", s)


def red(s: str) -> str:
    return _c("31", s)


def bold(s: str) -> str:
    return _c("1", s)


# --- result accumulator ------------------------------------------------------


class Report:
    def __init__(self) -> None:
        self.rows: list[tuple[str, str, str]] = []  # (level, label, detail)
        self.exit_code = 0

    def ok(self, label: str, detail: str) -> None:
        self.rows.append(("OK", label, detail))

    def warn(self, label: str, detail: str) -> None:
        self.rows.append(("WARN", label, detail))
        if self.exit_code < 1:
            self.exit_code = 1

    def fatal(self, label: str, detail: str) -> None:
        self.rows.append(("FATAL", label, detail))
        self.exit_code = 2

    def print(self) -> None:
        print(bold("\nAuto Debate — System Check\n"))
        width = max((len(r[1]) for r in self.rows), default=10)
        for level, label, detail in self.rows:
            if level == "OK":
                tag = green("  OK  ")
            elif level == "WARN":
                tag = yellow(" WARN ")
            else:
                tag = red("FATAL ")
            print(f"  [{tag}] {label.ljust(width)}  {detail}")
        print()
        if self.exit_code == 0:
            print(green(bold("System OK — proceed to scripts/check_ollama.py")))
        elif self.exit_code == 1:
            print(yellow(bold("System usable with warnings — review above.")))
        else:
            print(red(bold("System NOT ready — fix FATAL items before continuing.")))
        print()


# --- individual checks -------------------------------------------------------


def check_os(r: Report) -> None:
    sysname = platform.system()
    arch = platform.machine()
    detail = f"{sysname} {platform.release()} ({arch})"
    if sysname in {"Windows", "Linux", "Darwin"} and arch.lower() in {
        "amd64",
        "x86_64",
        "arm64",
        "aarch64",
    }:
        r.ok("OS / arch", detail)
    else:
        r.warn("OS / arch", f"{detail} — untested combination")


def check_python(r: Report) -> None:
    v = sys.version_info
    detail = f"{v.major}.{v.minor}.{v.micro} ({sys.executable})"
    if (v.major, v.minor) >= (3, 10):
        r.ok("Python version", detail)
    else:
        r.fatal("Python version", f"{detail} — need >= 3.10")


def check_cpu(r: Report) -> None:
    cores = os.cpu_count() or 0
    if cores >= 4:
        r.ok("CPU cores", f"{cores} logical cores")
    elif cores > 0:
        r.warn("CPU cores", f"{cores} logical cores — gemma3:4b will be slow")
    else:
        r.warn("CPU cores", "unknown")


def check_ram(r: Report) -> None:
    try:
        import psutil  # type: ignore[import-not-found]
    except ImportError:
        r.warn(
            "RAM",
            "psutil not installed — skipped (will be installed by bootstrap)",
        )
        return
    total_gb = psutil.virtual_memory().total / (1024**3)
    detail = f"{total_gb:.1f} GiB total"
    if total_gb < 4:
        r.fatal("RAM", f"{detail} — need >= 4 GiB")
    elif total_gb < 8:
        r.warn("RAM", f"{detail} — 8 GiB recommended for gemma3:4b")
    else:
        r.ok("RAM", detail)


def check_disk(r: Report) -> None:
    try:
        free_gb = shutil.disk_usage(".").free / (1024**3)
    except OSError as e:
        r.warn("Free disk", f"cannot read: {e}")
        return
    detail = f"{free_gb:.1f} GiB free in cwd"
    if free_gb < 5:
        r.fatal("Free disk", f"{detail} — need >= 5 GiB")
    elif free_gb < 10:
        r.warn("Free disk", f"{detail} — gemma3:4b is ~3.3 GiB plus venv")
    else:
        r.ok("Free disk", detail)


def _has_cmd(name: str) -> bool:
    return shutil.which(name) is not None


def _run(cmd: list[str], timeout: float = 3.0) -> tuple[int, str]:
    try:
        out = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return out.returncode, (out.stdout or "") + (out.stderr or "")
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return 1, ""


def check_gpu(r: Report) -> None:
    sysname = platform.system()
    if sysname == "Darwin" and platform.machine().lower() == "arm64":
        r.ok("GPU backend", "Apple Silicon — Ollama will use Metal")
        return
    if _has_cmd("nvidia-smi"):
        rc, out = _run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"])
        if rc == 0 and out.strip():
            first = out.strip().splitlines()[0]
            r.ok("GPU backend", f"NVIDIA detected: {first}")
            return
    if _has_cmd("rocminfo"):
        r.ok("GPU backend", "AMD ROCm detected")
        return
    r.warn("GPU backend", "no GPU detected — Ollama will run on CPU (slower)")


def check_network(r: Report) -> None:
    targets = [
        "https://ollama.com",
        "https://registry.ollama.ai",
    ]
    failures: list[str] = []
    for url in targets:
        req = urllib.request.Request(url, method="HEAD")
        try:
            with urllib.request.urlopen(req, timeout=4) as resp:  # noqa: S310
                if resp.status >= 400:
                    failures.append(f"{url} -> HTTP {resp.status}")
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            failures.append(f"{url} -> {e.__class__.__name__}")
    if not failures:
        r.ok("Network", "ollama.com reachable")
    else:
        r.warn("Network", "; ".join(failures))


# --- main --------------------------------------------------------------------


def main() -> int:
    r = Report()
    check_os(r)
    check_python(r)
    check_cpu(r)
    check_ram(r)
    check_disk(r)
    check_gpu(r)
    check_network(r)
    r.print()
    return r.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
