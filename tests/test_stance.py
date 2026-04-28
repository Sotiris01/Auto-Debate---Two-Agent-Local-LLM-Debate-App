"""Tests for the Phase 18 stance-analysis module."""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import pytest

from auto_debate.research import (
    STANCE_SYSTEM_PROMPT,
    StanceBrief,
    analyse_topic,
    render_stance_lines,
)
from auto_debate.research.stance import _parse_stance

# --- helpers ----------------------------------------------------------------


class _ScriptedClient:
    """Minimal LLM client returning a single canned response per call."""

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


def _well_formed_payload() -> dict[str, Any]:
    return {
        "topic": "Cars are bad for cities",
        "agent_id": "offender",
        "position": "against",
        "thesis": "Private cars dominate urban land and externalise costs onto everyone else.",
        "key_claims": [
            "Cars consume disproportionate urban land per passenger.",
            "Tailpipe emissions worsen public-health outcomes.",
            "Car infrastructure subsidies dwarf transit funding.",
        ],
        "expected_counterclaims": [
            "Cars provide door-to-door mobility for the disabled.",
            "Suburban density makes transit non-viable.",
            "EVs already eliminate tailpipe emissions.",
        ],
        "entities": ["urban planning", "EPA", "transit agencies"],
    }


def _wrap_block(payload: dict[str, Any]) -> str:
    return f"<STANCE>{json.dumps(payload)}</STANCE>"


# --- StanceBrief dataclass --------------------------------------------------


def test_stancebrief_constructs_with_valid_fields() -> None:
    brief = StanceBrief(
        topic="t",
        agent_id="defender",
        position="for",
        thesis="A short defensible thesis about the topic.",
        key_claims=("c1", "c2", "c3"),
        expected_counterclaims=("x1", "x2", "x3"),
        entities=("e1", "e2", "e3"),
    )
    assert brief.position == "for"


def test_stancebrief_rejects_overlong_thesis() -> None:
    with pytest.raises(ValueError, match="thesis"):
        StanceBrief(
            topic="t",
            agent_id="offender",
            position="against",
            thesis=" ".join(["word"] * 31),
            key_claims=("c1", "c2", "c3"),
            expected_counterclaims=("x1", "x2", "x3"),
            entities=("e1", "e2", "e3"),
        )


def test_stancebrief_rejects_too_few_claims() -> None:
    with pytest.raises(ValueError, match="key_claims"):
        StanceBrief(
            topic="t",
            agent_id="offender",
            position="against",
            thesis="ok",
            key_claims=("c1", "c2"),
            expected_counterclaims=("x1", "x2", "x3"),
            entities=("e1", "e2", "e3"),
        )


def test_stancebrief_rejects_overlong_claim() -> None:
    long = " ".join(["w"] * 21)
    with pytest.raises(ValueError, match="key_claims entry"):
        StanceBrief(
            topic="t",
            agent_id="offender",
            position="against",
            thesis="ok",
            key_claims=(long, "c2", "c3"),
            expected_counterclaims=("x1", "x2", "x3"),
            entities=("e1", "e2", "e3"),
        )


def test_stancebrief_rejects_too_many_entities() -> None:
    with pytest.raises(ValueError, match="entities"):
        StanceBrief(
            topic="t",
            agent_id="offender",
            position="against",
            thesis="ok",
            key_claims=("c1", "c2", "c3"),
            expected_counterclaims=("x1", "x2", "x3"),
            entities=tuple(f"e{i}" for i in range(9)),
        )


# --- parser -----------------------------------------------------------------


def test_parse_stance_happy_path() -> None:
    payload = _well_formed_payload()
    raw = _wrap_block(payload)
    brief = _parse_stance(raw, topic=payload["topic"], agent_id="offender")
    assert brief is not None
    assert brief.position == "against"
    assert len(brief.key_claims) == 3
    assert "EPA" in brief.entities


def test_parse_stance_accepts_bare_object_no_delimiter() -> None:
    payload = _well_formed_payload()
    raw = "noise " + json.dumps(payload) + " trailing"
    brief = _parse_stance(raw, topic=payload["topic"], agent_id="offender")
    assert brief is not None


def test_parse_stance_strips_code_fence() -> None:
    payload = _well_formed_payload()
    raw = "```json\n" + _wrap_block(payload) + "\n```"
    brief = _parse_stance(raw, topic=payload["topic"], agent_id="offender")
    assert brief is not None


def test_parse_stance_returns_none_on_garbage() -> None:
    assert _parse_stance("not even close", topic="t", agent_id="offender") is None


def test_parse_stance_returns_none_on_invalid_json() -> None:
    assert (
        _parse_stance("<STANCE>{not valid json}</STANCE>", topic="t", agent_id="offender") is None
    )


def test_parse_stance_returns_none_when_caps_violated() -> None:
    payload = _well_formed_payload()
    payload["key_claims"] = ["only-one"]  # below the 3-claim minimum
    raw = _wrap_block(payload)
    assert _parse_stance(raw, topic=payload["topic"], agent_id="offender") is None


def test_parse_stance_defaults_position_from_agent_id() -> None:
    payload = _well_formed_payload()
    payload["position"] = "wobble"  # invalid
    raw = _wrap_block(payload)
    brief = _parse_stance(raw, topic=payload["topic"], agent_id="offender")
    assert brief is not None
    assert brief.position == "against"


# --- analyse_topic end-to-end ----------------------------------------------


def test_analyse_topic_returns_brief_on_well_formed_response() -> None:
    payload = _well_formed_payload()
    client = _ScriptedClient([_wrap_block(payload)])
    brief = analyse_topic(client, "Cars are bad for cities", "offender")
    assert brief is not None
    assert brief.thesis.startswith("Private cars")
    # The system prompt must be exactly STANCE_SYSTEM_PROMPT.
    assert client.calls[0][0]["content"] == STANCE_SYSTEM_PROMPT
    # Temperature must be the deterministic value the design doc pins.
    options = client.options_seen[0]
    assert options is not None
    assert options.get("temperature") == 0.2


def test_analyse_topic_returns_none_on_malformed_output() -> None:
    client = _ScriptedClient(["this is not json at all"])
    assert analyse_topic(client, "topic", "offender") is None


def test_analyse_topic_rejects_empty_topic() -> None:
    client = _ScriptedClient([])
    with pytest.raises(ValueError, match="topic"):
        analyse_topic(client, "  ", "offender")


def test_analyse_topic_rejects_bad_agent_id() -> None:
    client = _ScriptedClient([])
    with pytest.raises(ValueError, match="agent_id"):
        analyse_topic(client, "topic", "judge")  # type: ignore[arg-type]


# --- rendering --------------------------------------------------------------


def test_render_stance_lines_orders_thesis_first() -> None:
    payload = _well_formed_payload()
    brief = _parse_stance(_wrap_block(payload), topic=payload["topic"], agent_id="offender")
    assert brief is not None
    lines = render_stance_lines(brief)
    assert lines[0].startswith("Thesis (against):")
    assert any(line.startswith("Key claim 1:") for line in lines)
    assert any(line.startswith("Expected counterclaim 1:") for line in lines)
    assert lines[-1].startswith("Entities:")
