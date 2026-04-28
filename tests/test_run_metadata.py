"""Tests for the Phase 22 run-metadata module."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from auto_debate.config import Settings
from auto_debate.run_metadata import (
    ResearchSummary,
    RunMetadata,
    persist_run_metadata,
    persist_transcript,
    settings_snapshot,
)


def _settings() -> Settings:
    return Settings(
        ollama_host="http://localhost:11434",
        model_name="gemma3:4b",
        max_turns=2,
        temperature=0.8,
        top_p=0.95,
        word_limit=80,
    )


def _summary() -> ResearchSummary:
    return ResearchSummary(
        agent_id="offender",
        queries=("cars urban land → 5 hits → 3 kept", "EPA emissions → 4 hits → 2 kept"),
        total_hits=9,
        kept_hits=5,
    )


def _metadata() -> RunMetadata:
    return RunMetadata(
        topic="Cars are bad for cities",
        started_at="2026-04-28T12:00:00Z",
        finished_at="2026-04-28T12:05:30Z",
        total_seconds=330.25,
        settings=settings_snapshot(_settings()),
        per_turn_seconds=(12.5, 14.1, 13.7, 11.9),
        research_summary=(_summary(),),
    )


# --- ResearchSummary --------------------------------------------------------


def test_research_summary_to_dict_roundtrip() -> None:
    s = _summary()
    d = s.to_dict()
    assert d["agent_id"] == "offender"
    assert d["queries"] == list(s.queries)
    assert d["total_hits"] == 9
    assert d["kept_hits"] == 5


def test_research_summary_rejects_invalid_agent_id() -> None:
    with pytest.raises(ValueError, match="agent_id"):
        ResearchSummary(
            agent_id="bystander",  # type: ignore[arg-type]
            queries=(),
            total_hits=0,
            kept_hits=0,
        )


def test_research_summary_rejects_negative_counts() -> None:
    with pytest.raises(ValueError, match="total_hits"):
        ResearchSummary(agent_id="offender", queries=(), total_hits=-1, kept_hits=0)
    with pytest.raises(ValueError, match="kept_hits"):
        ResearchSummary(agent_id="offender", queries=(), total_hits=0, kept_hits=-1)


def test_research_summary_kept_cannot_exceed_total() -> None:
    with pytest.raises(ValueError, match="kept_hits"):
        ResearchSummary(agent_id="offender", queries=(), total_hits=2, kept_hits=5)


# --- RunMetadata ------------------------------------------------------------


def test_run_metadata_rejects_blank_topic() -> None:
    with pytest.raises(ValueError, match="topic"):
        RunMetadata(
            topic="   ",
            started_at="2026-04-28T12:00:00Z",
            finished_at="2026-04-28T12:00:01Z",
            total_seconds=1.0,
            settings={},
            per_turn_seconds=(),
        )


def test_run_metadata_rejects_negative_total_seconds() -> None:
    with pytest.raises(ValueError, match="total_seconds"):
        RunMetadata(
            topic="t",
            started_at="2026-04-28T12:00:00Z",
            finished_at="2026-04-28T12:00:01Z",
            total_seconds=-0.1,
            settings={},
            per_turn_seconds=(),
        )


def test_run_metadata_rejects_negative_per_turn_seconds() -> None:
    with pytest.raises(ValueError, match="per_turn_seconds"):
        RunMetadata(
            topic="t",
            started_at="2026-04-28T12:00:00Z",
            finished_at="2026-04-28T12:00:01Z",
            total_seconds=1.0,
            settings={},
            per_turn_seconds=(1.0, -0.5),
        )


def test_run_metadata_to_dict_rounds_seconds() -> None:
    d = _metadata().to_dict()
    assert d["total_seconds"] == 330.25
    assert d["per_turn_seconds"] == [12.5, 14.1, 13.7, 11.9]
    assert d["research_summary"][0]["agent_id"] == "offender"
    assert d["topic"] == "Cars are bad for cities"


# --- settings_snapshot ------------------------------------------------------


def test_settings_snapshot_is_json_serialisable() -> None:
    snap = settings_snapshot(_settings())
    payload = json.dumps(snap)
    restored = json.loads(payload)
    assert restored["model_name"] == "gemma3:4b"
    assert restored["max_turns"] == 2


def test_settings_snapshot_includes_phase_flags() -> None:
    snap = settings_snapshot(_settings())
    # Spot-check some flags introduced in v0.2 / v0.3.
    assert "memory_enabled" in snap
    assert "web_research_enabled" in snap
    assert "stance_analysis_enabled" in snap


# --- persist_transcript -----------------------------------------------------


def test_persist_transcript_writes_file(tmp_path: Path) -> None:
    body = "# Debate: foo\n\n### Turn 1 — Offender\n\nHello.\n"
    path = persist_transcript(body, run_dir=tmp_path / "run-A")
    assert path == tmp_path / "run-A" / "auto_debate_transcript.md"
    assert path.read_text(encoding="utf-8") == body


def test_persist_transcript_creates_missing_dirs(tmp_path: Path) -> None:
    path = persist_transcript("x\n", run_dir=tmp_path / "deep" / "nest")
    assert path.exists()


# --- persist_run_metadata ---------------------------------------------------


def test_persist_run_metadata_writes_json(tmp_path: Path) -> None:
    md = _metadata()
    path = persist_run_metadata(md, run_dir=tmp_path / "run-X")
    assert path == tmp_path / "run-X" / "run.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["topic"] == "Cars are bad for cities"
    assert data["per_turn_seconds"] == [12.5, 14.1, 13.7, 11.9]
    assert data["research_summary"][0]["kept_hits"] == 5
    assert data["settings"]["model_name"] == "gemma3:4b"


def test_persist_run_metadata_pretty_prints(tmp_path: Path) -> None:
    path = persist_run_metadata(_metadata(), run_dir=tmp_path)
    text = path.read_text(encoding="utf-8")
    # JSON is indented (more than one line) and ends with a trailing newline.
    assert text.count("\n") > 5
    assert text.endswith("\n")


def test_persist_run_metadata_creates_missing_dirs(tmp_path: Path) -> None:
    path = persist_run_metadata(_metadata(), run_dir=tmp_path / "a" / "b")
    assert path.exists()
