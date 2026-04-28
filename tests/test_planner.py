"""Tests for the Phase 19 stance-driven query planner."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from auto_debate.research import (
    PLANNER_SYSTEM_PROMPT,
    PlannedQuery,
    QueryPlan,
    StanceBrief,
    plan_queries,
)
from auto_debate.research.planner import (
    JACCARD_DEDUP_THRESHOLD,
    MAX_QUERIES,
    _fallback_for_tests,
    _parse_plan_for_tests,
    persist_plan,
)

# --- helpers ----------------------------------------------------------------


def _brief() -> StanceBrief:
    return StanceBrief(
        topic="Cars are bad for cities",
        agent_id="offender",
        position="against",
        thesis="Private cars dominate urban land and externalise costs onto everyone else.",
        key_claims=(
            "Cars consume disproportionate urban land per passenger.",
            "Tailpipe emissions worsen public-health outcomes.",
            "Car infrastructure subsidies dwarf transit funding.",
        ),
        expected_counterclaims=(
            "Cars provide door-to-door mobility for the disabled.",
            "Suburban density makes transit non-viable.",
            "EVs already eliminate tailpipe emissions.",
        ),
        entities=("urban planning", "EPA", "transit agencies"),
    )


def _good_query(text: str, claim: int = 0) -> dict[str, Any]:
    return {
        "text": text,
        "target_claim": claim,
        "expected_source_kinds": ["paper", "news"],
    }


def _wrap(payload: dict[str, Any]) -> str:
    return f"<PLAN>{json.dumps(payload)}</PLAN>"


class _ScriptedClient:
    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.calls: list[list[dict[str, Any]]] = []
        self.options_seen: list[dict[str, Any] | None] = []

    def stream_chat(
        self,
        messages: list[dict[str, Any]],
        *,
        options: dict[str, Any] | None = None,
        model: str | None = None,
    ) -> Iterator[str]:
        self.calls.append(messages)
        self.options_seen.append(options)
        if not self._responses:
            raise AssertionError("ScriptedClient ran out of responses")
        yield self._responses.pop(0)


class _BoomClient:
    def stream_chat(
        self,
        messages: list[dict[str, Any]],
        *,
        options: dict[str, Any] | None = None,
        model: str | None = None,
    ) -> Iterator[str]:
        raise RuntimeError("boom")
        yield ""  # pragma: no cover


# --- PlannedQuery / QueryPlan dataclasses ----------------------------------


def test_planned_query_rejects_overlong_text() -> None:
    long = " ".join(["w"] * 13)
    with pytest.raises(ValueError, match="word cap"):
        PlannedQuery(text=long, target_claim=0, expected_source_kinds=("news",))


def test_planned_query_rejects_negative_claim() -> None:
    with pytest.raises(ValueError, match="target_claim"):
        PlannedQuery(text="ok query", target_claim=-1, expected_source_kinds=("news",))


def test_planned_query_rejects_unknown_source_kind() -> None:
    with pytest.raises(ValueError, match="source_kind"):
        PlannedQuery(
            text="ok query",
            target_claim=0,
            expected_source_kinds=("podcast",),  # type: ignore[arg-type]
        )


def test_query_plan_caps_at_max_queries() -> None:
    qs = tuple(
        PlannedQuery(text=f"q{i}", target_claim=0, expected_source_kinds=("news",))
        for i in range(MAX_QUERIES + 1)
    )
    with pytest.raises(ValueError, match="cap"):
        QueryPlan(agent_id="offender", queries=qs)


# --- parser -----------------------------------------------------------------


def test_parse_plan_happy_path() -> None:
    payload = {
        "agent_id": "offender",
        "queries": [
            _good_query("urban planning car land use", 0),
            _good_query("EPA tailpipe emissions health", 1),
            _good_query("transit agencies subsidy car infrastructure", 2),
            _good_query("urban planning parking minimums", 0),
            _good_query("EPA emissions urban air quality", 1),
        ],
    }
    out = _parse_plan_for_tests(_wrap(payload), brief=_brief())
    assert len(out) == 5
    assert {q.target_claim for q in out} == {0, 1, 2}


def test_parse_plan_drops_query_without_entity() -> None:
    payload = {
        "agent_id": "offender",
        "queries": [
            _good_query("urban planning car land use", 0),
            _good_query("just some random text without anchor", 0),
        ],
    }
    out = _parse_plan_for_tests(_wrap(payload), brief=_brief())
    assert len(out) == 1


def test_parse_plan_drops_out_of_range_claim_index() -> None:
    payload = {
        "agent_id": "offender",
        "queries": [
            _good_query("urban planning car land", 99),
            _good_query("EPA emissions tailpipe", 1),
        ],
    }
    out = _parse_plan_for_tests(_wrap(payload), brief=_brief())
    assert len(out) == 1
    assert out[0].target_claim == 1


def test_parse_plan_dedups_near_duplicates_by_jaccard() -> None:
    payload = {
        "agent_id": "offender",
        "queries": [
            _good_query("urban planning EPA emissions", 0),
            _good_query("urban planning EPA emissions car", 0),  # Jaccard ~0.8
            _good_query("transit agencies subsidies dwarf", 2),
        ],
    }
    out = _parse_plan_for_tests(_wrap(payload), brief=_brief())
    assert len(out) == 2
    assert out[0].text == "urban planning EPA emissions"
    assert out[1].target_claim == 2


def test_parse_plan_returns_empty_on_garbage() -> None:
    assert _parse_plan_for_tests("not json", brief=_brief()) == []


def test_parse_plan_returns_empty_on_invalid_json() -> None:
    assert _parse_plan_for_tests("<PLAN>{not json}</PLAN>", brief=_brief()) == []


def test_parse_plan_drops_overlong_query() -> None:
    long = " ".join(["urban", "planning"] + ["w"] * 12)  # 14 words
    payload = {
        "agent_id": "offender",
        "queries": [_good_query(long, 0), _good_query("EPA emissions", 1)],
    }
    out = _parse_plan_for_tests(_wrap(payload), brief=_brief())
    assert len(out) == 1
    assert out[0].target_claim == 1


# --- jaccard threshold sanity ----------------------------------------------


def test_jaccard_threshold_value() -> None:
    assert JACCARD_DEDUP_THRESHOLD == 0.6


# --- fallback ---------------------------------------------------------------


def test_fallback_yields_queries_when_brief_present() -> None:
    out = _fallback_for_tests(_brief())
    assert len(out) >= 1
    assert all(q.target_claim == 0 for q in out)
    assert all(len(q.text.split()) <= 12 for q in out)


# --- end-to-end -------------------------------------------------------------


def test_plan_queries_happy_path_uses_correct_options() -> None:
    payload = {
        "agent_id": "offender",
        "queries": [
            _good_query("urban planning car land", 0),
            _good_query("EPA emissions tailpipe", 1),
            _good_query("transit agencies subsidies", 2),
            _good_query("urban planning parking", 0),
        ],
    }
    client = _ScriptedClient([_wrap(payload)])
    plan = plan_queries(client, _brief())
    assert plan.agent_id == "offender"
    assert len(plan.queries) >= 3
    assert client.calls[0][0]["content"] == PLANNER_SYSTEM_PROMPT
    options = client.options_seen[0]
    assert options is not None
    assert options.get("temperature") == 0.3


def test_plan_queries_falls_back_when_llm_returns_garbage() -> None:
    client = _ScriptedClient(["not even close to JSON"])
    plan = plan_queries(client, _brief())
    assert len(plan.queries) >= 1


def test_plan_queries_falls_back_when_llm_raises() -> None:
    plan = plan_queries(_BoomClient(), _brief())
    assert len(plan.queries) >= 1


def test_plan_queries_appends_fallback_when_under_minimum() -> None:
    payload = {
        "agent_id": "offender",
        "queries": [_good_query("urban planning car land", 0)],  # only 1 valid
    }
    client = _ScriptedClient([_wrap(payload)])
    plan = plan_queries(client, _brief())
    assert len(plan.queries) >= 3
    assert plan.queries[0].text == "urban planning car land"


def test_plan_queries_persists_to_disk(tmp_path: Path) -> None:
    payload = {
        "agent_id": "offender",
        "queries": [
            _good_query("urban planning car land", 0),
            _good_query("EPA emissions tailpipe", 1),
            _good_query("transit agencies subsidies", 2),
        ],
    }
    client = _ScriptedClient([_wrap(payload)])
    plan_queries(
        client,
        _brief(),
        run_root=tmp_path,
        run_id="run-x",
    )
    expected = tmp_path / "run-x" / "research" / "offender.plan.json"
    assert expected.exists()
    saved = json.loads(expected.read_text(encoding="utf-8"))
    assert saved["agent_id"] == "offender"
    assert len(saved["queries"]) >= 3


def test_persist_plan_round_trip(tmp_path: Path) -> None:
    plan = QueryPlan(
        agent_id="defender",
        queries=(PlannedQuery(text="ok one", target_claim=0, expected_source_kinds=("news",)),),
    )
    path = persist_plan(plan, run_root=tmp_path, run_id="r1")
    assert path.parent.name == "research"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data == plan.to_dict()
