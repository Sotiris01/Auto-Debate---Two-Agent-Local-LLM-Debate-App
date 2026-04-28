"""Tests for the Phase 15 judge / evaluator agent."""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import pytest

from judge import (
    DIMENSIONS,
    Judge,
    JudgeReport,
    build_judge_messages,
    parse_judge_response,
    render_report_markdown,
    save_report,
)

# --- helpers ----------------------------------------------------------------


def _good_payload(scores: dict[str, int] | None = None) -> dict[str, Any]:
    """Build a complete, valid judge JSON payload."""
    base = scores or {dim.key: 4 for dim in DIMENSIONS}
    return {
        dim.key: {"score": base[dim.key], "comment": f"comment for {dim.qid}"} for dim in DIMENSIONS
    } | {"verdict": "Solid debate, on-topic and persona-distinct."}


def _wrap_report(payload: dict[str, Any]) -> str:
    return f"<REPORT>\n{json.dumps(payload)}\n</REPORT>"


# --- 15.1 schema + parser ---------------------------------------------------


def test_parse_judge_response_happy_path() -> None:
    raw = _wrap_report(_good_payload())
    report = parse_judge_response(raw=raw, topic="X vs Y", model="m")
    assert report is not None
    assert len(report.scores) == 9
    assert {s.key for s in report.scores} == {d.key for d in DIMENSIONS}
    assert all(1 <= s.score <= 5 for s in report.scores)
    assert report.overall == 4.0
    assert report.verdict.startswith("Solid")
    assert report.model == "m"
    assert report.topic == "X vs Y"


def test_parse_tolerates_surrounding_prose() -> None:
    raw = (
        "Sure, here is the report:\n\n"
        + _wrap_report(_good_payload())
        + "\n\nLet me know if you need anything else."
    )
    report = parse_judge_response(raw=raw, topic="t")
    assert report is not None
    assert report.overall == 4.0


def test_parse_falls_back_to_bare_json_object_without_block() -> None:
    payload = _good_payload()
    raw = "Here goes:\n" + json.dumps(payload)
    report = parse_judge_response(raw=raw, topic="t")
    assert report is not None
    assert report.scores[0].key == DIMENSIONS[0].key


def test_parse_rejects_missing_dimension() -> None:
    payload = _good_payload()
    del payload["safety"]
    raw = _wrap_report(payload)
    assert parse_judge_response(raw=raw, topic="t") is None


def test_parse_rejects_out_of_range_score() -> None:
    payload = _good_payload()
    payload["on_topic"]["score"] = 9
    raw = _wrap_report(payload)
    assert parse_judge_response(raw=raw, topic="t") is None


def test_parse_rejects_below_minimum_score() -> None:
    payload = _good_payload()
    payload["on_topic"]["score"] = 0
    raw = _wrap_report(payload)
    assert parse_judge_response(raw=raw, topic="t") is None


def test_parse_rejects_non_numeric_score() -> None:
    payload = _good_payload()
    payload["on_topic"]["score"] = "great"
    raw = _wrap_report(payload)
    assert parse_judge_response(raw=raw, topic="t") is None


def test_parse_coerces_float_score_to_int() -> None:
    payload = _good_payload()
    payload["on_topic"]["score"] = 4.4
    raw = _wrap_report(payload)
    report = parse_judge_response(raw=raw, topic="t")
    assert report is not None
    on_topic = next(s for s in report.scores if s.key == "on_topic")
    assert on_topic.score == 4


def test_parse_returns_none_on_malformed_json() -> None:
    raw = "<REPORT>\n{not json{{{\n</REPORT>"
    assert parse_judge_response(raw=raw, topic="t") is None


def test_parse_returns_none_on_empty_input() -> None:
    assert parse_judge_response(raw="", topic="t") is None
    assert parse_judge_response(raw="   \n", topic="t") is None


def test_parse_returns_none_when_no_block_or_json() -> None:
    assert parse_judge_response(raw="just some prose, no scores", topic="t") is None


def test_parse_truncates_long_comment() -> None:
    payload = _good_payload()
    payload["on_topic"]["comment"] = "a" * 5000
    raw = _wrap_report(payload)
    report = parse_judge_response(raw=raw, topic="t")
    assert report is not None
    on_topic = next(s for s in report.scores if s.key == "on_topic")
    assert len(on_topic.comment) <= 410  # 400 + ellipsis


def test_parse_rejects_bool_score() -> None:
    payload = _good_payload()
    payload["on_topic"]["score"] = True  # bool sneaks past int isinstance otherwise
    raw = _wrap_report(payload)
    assert parse_judge_response(raw=raw, topic="t") is None


def test_parse_rejects_missing_verdict() -> None:
    payload = _good_payload()
    del payload["verdict"]
    raw = _wrap_report(payload)
    assert parse_judge_response(raw=raw, topic="t") is None


def test_parse_rejects_empty_verdict() -> None:
    payload = _good_payload()
    payload["verdict"] = "   "
    raw = _wrap_report(payload)
    assert parse_judge_response(raw=raw, topic="t") is None


# --- 15.2 prompt assembly ---------------------------------------------------


def test_build_judge_messages_contains_topic_and_turns() -> None:
    msgs = build_judge_messages(
        topic="Cats vs dogs",
        transcript=[("offender", "Cats are aloof."), ("defender", "Dogs are needy.")],
    )
    assert len(msgs) == 2
    assert msgs[0]["role"] == "system"
    assert msgs[1]["role"] == "user"
    user_text = msgs[1]["content"]
    assert "Cats vs dogs" in user_text
    assert "Turn 1 — Offender" in user_text
    assert "Turn 2 — Defender" in user_text
    assert "Cats are aloof." in user_text


def test_build_judge_messages_rubric_lists_all_nine_dimensions() -> None:
    msgs = build_judge_messages(topic="t", transcript=[("offender", "x")])
    system = msgs[0]["content"]
    for dim in DIMENSIONS:
        assert dim.qid in system
        assert dim.key in system


# --- 15.2 rendering ---------------------------------------------------------


def test_render_report_markdown_has_all_sections() -> None:
    raw = _wrap_report(_good_payload())
    report = parse_judge_response(raw=raw, topic="Cats vs dogs", model="gemma3:4b")
    assert report is not None
    md = render_report_markdown(report)
    assert "# Auto Debate — Judge Report" in md
    assert "Cats vs dogs" in md
    assert "gemma3:4b" in md
    for dim in DIMENSIONS:
        assert f"## {dim.qid}. {dim.title}" in md
    assert "## Summary scorecard" in md
    assert "| Q1 |" in md
    assert "**Overall (mean)**" in md
    assert "## Headline verdict" in md


def test_overall_is_unweighted_mean() -> None:
    scores = {dim.key: 3 for dim in DIMENSIONS}
    scores["on_topic"] = 5  # mean = (5 + 8*3) / 9 = 29/9 ≈ 3.2
    raw = _wrap_report(_good_payload(scores))
    report = parse_judge_response(raw=raw, topic="t")
    assert report is not None
    assert report.overall == pytest.approx(3.2, abs=0.05)


# --- 15.3 persistence -------------------------------------------------------


def test_save_report_writes_json_and_markdown(tmp_path: Any) -> None:
    raw = _wrap_report(_good_payload())
    report = parse_judge_response(raw=raw, topic="X", model="m")
    assert report is not None
    json_path, md_path = save_report(report, run_dir=tmp_path / "runs" / "abc")
    assert json_path.exists()
    assert md_path.exists()
    parsed = json.loads(json_path.read_text(encoding="utf-8"))
    assert parsed["topic"] == "X"
    assert parsed["model"] == "m"
    assert parsed["overall"] == 4.0
    assert {s["key"] for s in parsed["scores"]} == {d.key for d in DIMENSIONS}
    md_text = md_path.read_text(encoding="utf-8")
    assert "Auto Debate — Judge Report" in md_text


def test_save_report_creates_missing_parent_dir(tmp_path: Any) -> None:
    raw = _wrap_report(_good_payload())
    report = parse_judge_response(raw=raw, topic="X")
    assert report is not None
    target = tmp_path / "deep" / "nested" / "run-1"
    save_report(report, run_dir=target)
    assert (target / "report.json").exists()
    assert (target / "report.md").exists()


# --- 15.5 LLM-driven Judge --------------------------------------------------


class _StubClient:
    """Fake LLM client that returns a canned chunked response."""

    def __init__(self, response: str, *, raises: type[BaseException] | None = None) -> None:
        self._response = response
        self._raises = raises
        self.calls: list[list[dict[str, Any]]] = []

    def stream_chat(
        self,
        messages: list[dict[str, Any]],
        *,
        options: dict[str, Any] | None = None,
        model: str | None = None,
    ) -> Iterator[str]:
        self.calls.append([dict(m) for m in messages])
        if self._raises is not None:
            raise self._raises("boom")
        # Stream a few chunks to match real Ollama behaviour.
        for chunk in (self._response[:20], self._response[20:]):
            if chunk:
                yield chunk


def test_judge_evaluate_happy_path() -> None:
    raw = _wrap_report(_good_payload())
    client = _StubClient(raw)
    judge = Judge(llm_client=client, model="gemma3:4b")
    report = judge.evaluate(
        topic="topic",
        transcript=[("offender", "a"), ("defender", "b")],
    )
    assert report is not None
    assert report.model == "gemma3:4b"
    assert len(client.calls) == 1


def test_judge_returns_none_on_malformed_response() -> None:
    client = _StubClient("not a report at all")
    judge = Judge(llm_client=client)
    assert judge.evaluate(topic="t", transcript=[("offender", "x")]) is None


def test_judge_returns_none_on_llm_error() -> None:
    client = _StubClient("", raises=RuntimeError)
    judge = Judge(llm_client=client)
    assert judge.evaluate(topic="t", transcript=[("offender", "x")]) is None


def test_judge_refuses_empty_transcript() -> None:
    client = _StubClient(_wrap_report(_good_payload()))
    judge = Judge(llm_client=client)
    assert judge.evaluate(topic="t", transcript=[]) is None
    assert client.calls == []  # no LLM call made


# --- 15.4 sanity smoke (offline) --------------------------------------------


def test_report_round_trip_through_to_dict() -> None:
    """JSON round-trip preserves every field used by the persisted report."""
    raw = _wrap_report(_good_payload())
    report = parse_judge_response(raw=raw, topic="X", model="m")
    assert report is not None
    serialised = json.dumps(report.to_dict())
    parsed = json.loads(serialised)
    assert parsed["topic"] == "X"
    assert parsed["overall"] == 4.0
    assert len(parsed["scores"]) == 9


def test_dimension_score_validates_range() -> None:
    from judge import DimensionScore

    with pytest.raises(ValueError, match="out of range"):
        DimensionScore(key="x", qid="Q1", title="t", score=6)
    with pytest.raises(ValueError, match="out of range"):
        DimensionScore(key="x", qid="Q1", title="t", score=0)


def test_judge_report_overall_handles_empty_scores() -> None:
    empty = JudgeReport(topic="t", scores=())
    assert empty.overall == 0.0
