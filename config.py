"""
config.py — Typed runtime configuration loaded from environment / .env.

Part of the Auto Debate project. See PROJECT.md and ROADMAP.md.

Phase 2: single source of truth for all runtime knobs. Loaded once at
startup via :func:`load_settings`. The returned :class:`Settings` is
immutable — downstream layers (llm, engine, app) treat it as read-only.

Phase 7 also adds :func:`configure_logging`, a small idempotent helper
that installs a rotating file handler (logs/auto_debate.log, 1 MB x 3)
plus a console handler. Engine logs every committed turn at INFO; the
LLM layer logs request/response sizes at DEBUG.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from logging.handlers import RotatingFileHandler
from pathlib import Path

from dotenv import load_dotenv

__all__ = [
    "ConfigError",
    "Settings",
    "configure_logging",
    "load_settings",
]


# --- defaults (mirror .env.example) -----------------------------------------

_DEFAULT_OLLAMA_HOST = "http://localhost:11434"
_DEFAULT_MODEL_NAME = "gemma3:4b"
_DEFAULT_MAX_TURNS = 10
_DEFAULT_TEMPERATURE = 0.8
_DEFAULT_TOP_P = 0.95
_DEFAULT_WORD_LIMIT = 120
_DEFAULT_MEMORY_ENABLED = False


class ConfigError(ValueError):
    """Raised when one or more configuration values fail validation.

    The message is a single string with all problems concatenated, one per
    line, so the user sees every issue in one go instead of fixing them one
    by one.
    """


@dataclass(frozen=True)
class Settings:
    """Immutable runtime configuration for the Auto Debate app."""

    ollama_host: str
    model_name: str
    max_turns: int
    temperature: float
    top_p: float
    word_limit: int
    memory_enabled: bool = _DEFAULT_MEMORY_ENABLED


# --- helpers ----------------------------------------------------------------


def _get_str(name: str, default: str) -> str:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip()


def _get_int(name: str, default: int, problems: list[str]) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw.strip())
    except ValueError:
        problems.append(f"{name}={raw!r} is not a valid integer")
        return default


def _get_float(name: str, default: float, problems: list[str]) -> float:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw.strip())
    except ValueError:
        problems.append(f"{name}={raw!r} is not a valid float")
        return default


def _get_bool(name: str, default: bool, problems: list[str]) -> bool:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    value = raw.strip().lower()
    if value in ("1", "true", "yes", "on"):
        return True
    if value in ("0", "false", "no", "off"):
        return False
    problems.append(f"{name}={raw!r} is not a valid boolean")
    return default


def load_settings(*, dotenv_path: str | os.PathLike[str] | None = None) -> Settings:
    """Load and validate :class:`Settings` from the environment.

    Reads ``.env`` (if present) into ``os.environ`` via python-dotenv, then
    pulls every field with a typed default. All validation problems are
    collected and raised together as a single :class:`ConfigError`.

    Args:
        dotenv_path: Optional explicit path to a ``.env`` file. When ``None``
            (the default), python-dotenv searches the current working
            directory and its parents.
    """
    # ``override=False`` means real environment variables win over .env —
    # this matches twelve-factor expectations and keeps tests deterministic.
    if dotenv_path is None:
        load_dotenv(override=False)
    else:
        load_dotenv(dotenv_path=dotenv_path, override=False)

    problems: list[str] = []

    ollama_host = _get_str("OLLAMA_HOST", _DEFAULT_OLLAMA_HOST)
    model_name = _get_str("MODEL_NAME", _DEFAULT_MODEL_NAME)
    max_turns = _get_int("MAX_TURNS", _DEFAULT_MAX_TURNS, problems)
    temperature = _get_float("TEMPERATURE", _DEFAULT_TEMPERATURE, problems)
    top_p = _get_float("TOP_P", _DEFAULT_TOP_P, problems)
    word_limit = _get_int("WORD_LIMIT", _DEFAULT_WORD_LIMIT, problems)
    memory_enabled = _get_bool("MEMORY_ENABLED", _DEFAULT_MEMORY_ENABLED, problems)

    if not ollama_host.startswith(("http://", "https://")):
        problems.append(
            f"OLLAMA_HOST={ollama_host!r} must start with 'http://' or 'https://'",
        )
    if not model_name:
        problems.append("MODEL_NAME must not be empty")
    if max_turns < 1:
        problems.append(f"MAX_TURNS={max_turns} must be >= 1")
    if not (0 < temperature <= 2):
        problems.append(f"TEMPERATURE={temperature} must be in (0, 2]")
    if not (0 < top_p <= 1):
        problems.append(f"TOP_P={top_p} must be in (0, 1]")
    if word_limit < 30:
        problems.append(f"WORD_LIMIT={word_limit} must be >= 30")

    if problems:
        raise ConfigError("Invalid configuration:\n  - " + "\n  - ".join(problems))

    return Settings(
        ollama_host=ollama_host,
        model_name=model_name,
        max_turns=max_turns,
        temperature=temperature,
        top_p=top_p,
        word_limit=word_limit,
        memory_enabled=memory_enabled,
    )


# --- logging ----------------------------------------------------------------

_LOG_FORMAT = "%(asctime)s %(levelname)-7s %(name)s — %(message)s"
_LOG_DATEFMT = "%Y-%m-%d %H:%M:%S"
_LOG_FILE_BYTES = 1_048_576  # 1 MiB
_LOG_FILE_BACKUPS = 3
_LOG_MARKER = "_auto_debate_logging_configured"


def configure_logging(
    *,
    log_dir: str | os.PathLike[str] = "logs",
    file_level: int = logging.DEBUG,
    console_level: int = logging.INFO,
) -> None:
    """Install a rotating file handler + console handler on the root logger.

    Idempotent: subsequent calls are no-ops so Streamlit's per-rerun script
    execution doesn't keep stacking handlers. The file handler captures
    everything from DEBUG up (so the LLM layer's request/response sizes
    survive); the console handler is INFO+ for a clean terminal.
    """
    root = logging.getLogger()
    if getattr(root, _LOG_MARKER, False):
        return

    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter(_LOG_FORMAT, datefmt=_LOG_DATEFMT)

    file_handler = RotatingFileHandler(
        log_path / "auto_debate.log",
        maxBytes=_LOG_FILE_BYTES,
        backupCount=_LOG_FILE_BACKUPS,
        encoding="utf-8",
    )
    file_handler.setLevel(file_level)
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(console_level)
    console_handler.setFormatter(formatter)

    # Set root to the lowest of the two so handlers can filter independently.
    root.setLevel(min(file_level, console_level))
    root.addHandler(file_handler)
    root.addHandler(console_handler)
    setattr(root, _LOG_MARKER, True)
