"""Phase 22 — Run metadata & transcript auto-save.

When a debate completes (and ``settings.memory_enabled`` is on), the app
persists two new artefacts under ``runs/<run_id>/``:

* ``auto_debate_transcript.md`` — the full markdown transcript that the
  Phase 8 export already produces, written automatically so users do not
  have to click a download button to keep a record.
* ``run.json`` — a structured record of the run: the topic, the
  ISO-8601 start / finish timestamps, the total wall-clock seconds, a
  snapshot of the active :class:`auto_debate.config.Settings`, the
  per-turn wall-clock seconds (in turn order), and a per-agent research
  summary (one ``"<query> → N hits → M kept"`` line per planned query).

The persistence helpers in this module are deliberately small and pure:
they take dataclasses and return paths. Directories are created on
demand; I/O errors propagate to the caller (the Streamlit app gates the
calls behind ``st.warning`` so the UI never crashes).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from auto_debate.config import Settings
from auto_debate.memory import AgentId

__all__ = [
    "ResearchSummary",
    "RunMetadata",
    "persist_run_metadata",
    "persist_transcript",
    "settings_snapshot",
]


@dataclass(frozen=True)
class ResearchSummary:
    """Per-agent research summary for one debate run.

    ``queries`` is a sequence of human-readable lines in the form
    ``"<query> → N hits → M kept"`` (one per planned query). ``total_hits``
    and ``kept_hits`` are aggregates across all queries.
    """

    agent_id: AgentId
    queries: tuple[str, ...]
    total_hits: int
    kept_hits: int

    def __post_init__(self) -> None:
        if self.agent_id not in ("offender", "defender"):
            raise ValueError(f"agent_id must be 'offender' or 'defender', got {self.agent_id!r}")
        if self.total_hits < 0:
            raise ValueError(f"total_hits must be >= 0, got {self.total_hits}")
        if self.kept_hits < 0:
            raise ValueError(f"kept_hits must be >= 0, got {self.kept_hits}")
        if self.kept_hits > self.total_hits:
            raise ValueError(
                f"kept_hits ({self.kept_hits}) cannot exceed total_hits ({self.total_hits})",
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "queries": list(self.queries),
            "total_hits": self.total_hits,
            "kept_hits": self.kept_hits,
        }


@dataclass(frozen=True)
class RunMetadata:
    """Top-level run record persisted to ``run.json``.

    Timestamps are ISO-8601 UTC strings (e.g. ``"2026-04-28T11:02:41Z"``).
    ``per_turn_seconds`` is the wall-clock cost of every committed turn,
    in turn order. ``settings`` is a plain-dict snapshot of the active
    :class:`Settings` (taken via :func:`settings_snapshot`).
    """

    topic: str
    started_at: str
    finished_at: str
    total_seconds: float
    settings: dict[str, Any]
    per_turn_seconds: tuple[float, ...]
    research_summary: tuple[ResearchSummary, ...] = ()

    def __post_init__(self) -> None:
        if not self.topic.strip():
            raise ValueError("topic must be a non-empty string")
        if not self.started_at.strip() or not self.finished_at.strip():
            raise ValueError("started_at and finished_at must be non-empty ISO-8601 strings")
        if self.total_seconds < 0:
            raise ValueError(f"total_seconds must be >= 0, got {self.total_seconds}")
        for s in self.per_turn_seconds:
            if s < 0:
                raise ValueError(f"per_turn_seconds entries must be >= 0, got {s}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "topic": self.topic,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "total_seconds": round(self.total_seconds, 3),
            "settings": self.settings,
            "per_turn_seconds": [round(s, 3) for s in self.per_turn_seconds],
            "research_summary": [s.to_dict() for s in self.research_summary],
        }


def settings_snapshot(settings: Settings) -> dict[str, Any]:
    """Return a JSON-serialisable snapshot of ``settings``.

    Uses :func:`dataclasses.asdict`, which recursively converts nested
    dataclasses to plain dicts. The result is safe to dump via
    :func:`json.dumps` without further coercion.
    """
    return asdict(settings)


def persist_run_metadata(metadata: RunMetadata, *, run_dir: Path) -> Path:
    """Write ``metadata`` to ``<run_dir>/run.json`` and return the path.

    Creates ``run_dir`` (and parents) if absent. Raises :class:`OSError`
    on I/O failure — callers in the UI wrap this in a ``try/except`` and
    surface a non-fatal warning.
    """
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / "run.json"
    payload = json.dumps(metadata.to_dict(), indent=2, ensure_ascii=False)
    path.write_text(payload + "\n", encoding="utf-8")
    return path


def persist_transcript(markdown: str, *, run_dir: Path) -> Path:
    """Write ``markdown`` to ``<run_dir>/auto_debate_transcript.md`` and return the path.

    Creates ``run_dir`` (and parents) if absent. Raises :class:`OSError`
    on I/O failure.
    """
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / "auto_debate_transcript.md"
    path.write_text(markdown, encoding="utf-8")
    return path
