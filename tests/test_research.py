"""Tests for the Phase 11 web-research module."""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from memory import MemoryStore
from research import (
    OfflineFixtureAdapter,
    Researcher,
    ResearchLimits,
    SearchResult,
    _parse_query_plan,
    _parse_summary,
    _SearchCache,
)

# --- helpers ----------------------------------------------------------------


class _ScriptedClient:
    """Minimal LLM client. Returns canned strings for sequential chat calls."""

    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.calls: list[list[dict[str, Any]]] = []

    def stream_chat(
        self,
        messages: list[dict[str, Any]],
        *,
        options: dict[str, Any] | None = None,
        model: str | None = None,
    ) -> Iterator[str]:
        self.calls.append(messages)
        if not self._responses:
            raise AssertionError("ScriptedClient ran out of responses")
        chunk = self._responses.pop(0)
        # Yield in two parts so the consumer must concatenate.
        if chunk:
            yield chunk[: len(chunk) // 2]
            yield chunk[len(chunk) // 2 :]
        else:
            yield ""


def _result(url: str, *, title: str = "t", snippet: str = "s") -> SearchResult:
    return SearchResult(title=title, url=url, snippet=snippet, fetched_at="2025-01-01T00:00:00Z")


# --- SearchResult / OfflineFixtureAdapter ----------------------------------


def test_search_result_round_trip() -> None:
    r = _result("https://example.com/a")
    assert SearchResult.from_dict(r.as_dict()) == r


def test_offline_adapter_returns_capped_results() -> None:
    fixture = {
        "ai safety": [_result(f"https://example.com/{i}") for i in range(7)],
    }
    adapter = OfflineFixtureAdapter(fixture=fixture)
    hits = adapter.search("AI safety", max_results=3)
    assert len(hits) == 3
    assert hits[0].url == "https://example.com/0"


def test_offline_adapter_unknown_query_is_empty() -> None:
    adapter = OfflineFixtureAdapter(fixture={})
    assert adapter.search("anything", max_results=5) == []


# --- planner / summary parsing ---------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ('["q1","q2","q3"]', ["q1", "q2", "q3"]),
        ('```json\n["q1", "q2"]\n```', ["q1", "q2"]),
        ('noise before ["q1", "q2"] noise after', ["q1", "q2"]),
    ],
)
def test_parse_query_plan_happy_paths(raw: str, expected: list[str]) -> None:
    assert _parse_query_plan(raw, fallback_topic="topic") == expected


def test_parse_query_plan_falls_back_on_garbage() -> None:
    assert _parse_query_plan("not json at all", fallback_topic="topic") == ["topic"]


def test_parse_query_plan_falls_back_when_not_a_list() -> None:
    assert _parse_query_plan('{"q":"x"}', fallback_topic="topic") == ["topic"]


def test_parse_summary_valid() -> None:
    raw = '{"summary": "Short paraphrase.", "tag": "supports"}'
    assert _parse_summary(raw) == ("Short paraphrase.", "supports")


def test_parse_summary_caps_length() -> None:
    long = " ".join(f"w{i}" for i in range(60))
    raw = json.dumps({"summary": long, "tag": "contradicts"})
    parsed = _parse_summary(raw)
    assert parsed is not None
    summary, tag = parsed
    assert tag == "contradicts"
    assert len(summary.split()) == 40


def test_parse_summary_rejects_unknown_tag() -> None:
    assert _parse_summary('{"summary": "x", "tag": "lol"}') is None


def test_parse_summary_rejects_garbage() -> None:
    assert _parse_summary("nothing useful") is None


# --- _SearchCache ----------------------------------------------------------


def test_search_cache_round_trip(tmp_path: Path) -> None:
    cache = _SearchCache(root=tmp_path)
    items = [_result("https://example.com/a"), _result("https://example.com/b")]
    cache.save("hello world", items)
    loaded = cache.load("HELLO WORLD")  # case/whitespace-insensitive
    assert loaded == items


def test_search_cache_expires(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cache = _SearchCache(root=tmp_path, ttl_seconds=10.0)
    monkeypatch.setattr(time, "time", lambda: 1000.0)
    cache.save("q", [_result("https://example.com/a")])
    monkeypatch.setattr(time, "time", lambda: 1011.0)
    assert cache.load("q") is None


def test_search_cache_corrupt_file_returns_none(tmp_path: Path) -> None:
    cache = _SearchCache(root=tmp_path)
    path = cache._path_for("q")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not valid json", encoding="utf-8")
    assert cache.load("q") is None


# --- Researcher.populate_for_agent end-to-end ------------------------------


def _three_offender_results() -> dict[str, list[SearchResult]]:
    return {
        "risks of x": [
            _result("https://example.com/r1", title="Risks 1", snippet="bad things"),
            _result("https://example.com/r2", title="Risks 2", snippet="more bad things"),
            _result("https://example.com/r3", title="Risks 3", snippet="even more"),
        ],
    }


def test_researcher_populates_memory_with_url_entries(tmp_path: Path) -> None:
    fixture = _three_offender_results()
    adapter = OfflineFixtureAdapter(fixture=fixture)
    # 1 planner call + 3 summary calls.
    client = _ScriptedClient(
        responses=[
            '["risks of x"]',
            '{"summary": "First risk.", "tag": "supports"}',
            '{"summary": "Second risk.", "tag": "supports"}',
            '{"summary": "Third risk.", "tag": "contradicts"}',
        ],
    )
    store = MemoryStore(root=tmp_path)
    run_id = "testrun"
    researcher = Researcher(
        llm_client=client,
        adapter=adapter,
        memory_store=store,
        run_id=run_id,
    )
    memory = researcher.populate_for_agent("offender", topic="X is good")
    assert len(memory.knowledge) >= 3
    for entry in memory.knowledge:
        assert "https://example.com/" in entry
    # Verify it was persisted to disk too.
    reloaded = store.load(run_id, "offender")
    assert reloaded.knowledge == memory.knowledge


def test_researcher_skips_irrelevant_results(tmp_path: Path) -> None:
    fixture = _three_offender_results()
    adapter = OfflineFixtureAdapter(fixture=fixture)
    client = _ScriptedClient(
        responses=[
            '["risks of x"]',
            '{"summary": "Useful.", "tag": "supports"}',
            '{"summary": "Off-topic.", "tag": "irrelevant"}',
            '{"summary": "Other.", "tag": "supports"}',
        ],
    )
    store = MemoryStore(root=tmp_path)
    researcher = Researcher(
        llm_client=client,
        adapter=adapter,
        memory_store=store,
        run_id="run",
    )
    memory = researcher.populate_for_agent("offender", topic="X")
    assert len(memory.knowledge) == 2


def test_researcher_dedupes_existing_entries(tmp_path: Path) -> None:
    fixture = _three_offender_results()
    adapter = OfflineFixtureAdapter(fixture=fixture)
    # Pre-seed memory with what would be the first entry.
    store = MemoryStore(root=tmp_path)
    from memory import AgentMemory

    seeded = AgentMemory(
        agent_id="offender",
        knowledge=("[supports] First risk. (source: https://example.com/r1)",),
        observations=(),
        strategy=(),
        turn_index=0,
    )
    store.save("run", seeded)

    client = _ScriptedClient(
        responses=[
            '["risks of x"]',
            '{"summary": "First risk.", "tag": "supports"}',
            '{"summary": "Second risk.", "tag": "supports"}',
            '{"summary": "Third risk.", "tag": "supports"}',
        ],
    )
    researcher = Researcher(
        llm_client=client,
        adapter=adapter,
        memory_store=store,
        run_id="run",
    )
    memory = researcher.populate_for_agent("offender", topic="X")
    # Original + 2 new (the duplicate first entry was deduped).
    assert len(memory.knowledge) == 3


def test_researcher_respects_max_queries(tmp_path: Path) -> None:
    fixture = {f"q{i}": [_result(f"https://e.com/{i}")] for i in range(10)}
    adapter = OfflineFixtureAdapter(fixture=fixture)
    plan = json.dumps([f"q{i}" for i in range(10)])
    summaries = ['{"summary": "ok.", "tag": "supports"}' for _ in range(10)]
    client = _ScriptedClient(responses=[plan, *summaries])
    store = MemoryStore(root=tmp_path)
    researcher = Researcher(
        llm_client=client,
        adapter=adapter,
        memory_store=store,
        run_id="run",
        limits=ResearchLimits(max_queries=2, max_results_per_query=5),
    )
    memory = researcher.populate_for_agent("offender", topic="X")
    assert len(memory.knowledge) == 2  # only 2 queries got summarised


def test_researcher_respects_wall_clock_budget(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _three_offender_results()
    adapter = OfflineFixtureAdapter(fixture=fixture)
    client = _ScriptedClient(
        responses=['["risks of x"]', '{"summary":"a.","tag":"supports"}'],
    )
    store = MemoryStore(root=tmp_path)
    # Make monotonic jump past the deadline immediately.
    fake_time = iter([0.0, 0.0, 1000.0, 1000.0, 1000.0, 1000.0, 1000.0])
    monkeypatch.setattr(
        "research.time.monotonic",
        lambda: next(fake_time, 1000.0),
    )
    researcher = Researcher(
        llm_client=client,
        adapter=adapter,
        memory_store=store,
        run_id="run",
        limits=ResearchLimits(wall_clock_budget_seconds=10.0),
    )
    memory = researcher.populate_for_agent("offender", topic="X")
    # Budget exhausted before we could enrich knowledge -> no new entries.
    assert memory.knowledge == ()


def test_researcher_falls_back_to_topic_on_planner_error(tmp_path: Path) -> None:
    fixture = {"climate change is real": [_result("https://e.com/x")]}
    adapter = OfflineFixtureAdapter(fixture=fixture)
    client = _ScriptedClient(
        responses=[
            "this is not JSON at all",
            '{"summary": "a.", "tag": "supports"}',
        ],
    )
    store = MemoryStore(root=tmp_path)
    researcher = Researcher(
        llm_client=client,
        adapter=adapter,
        memory_store=store,
        run_id="run",
    )
    memory = researcher.populate_for_agent("offender", topic="climate change is real")
    assert len(memory.knowledge) == 1
    assert "https://e.com/x" in memory.knowledge[0]


def test_research_limits_validation() -> None:
    with pytest.raises(ValueError):
        ResearchLimits(max_queries=0)
    with pytest.raises(ValueError):
        ResearchLimits(max_results_per_query=0)
    with pytest.raises(ValueError):
        ResearchLimits(wall_clock_budget_seconds=0.0)
