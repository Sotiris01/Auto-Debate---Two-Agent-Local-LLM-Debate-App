"""
stance.py — Per-agent topic stance brief (Phase 18).

Part of the Auto Debate project. See PROJECT.md, ROADMAP.md and the
design contract in ``docs/research/agentic_research.md`` §2.1.

Before any search runs, each agent reads the topic through one short
LLM pass and emits a structured :class:`StanceBrief`: what the agent
is being asked to defend, what its core claims are, what counter-
claims to expect, and which entities anchor the rest of the research
pipeline. The brief is the single input every later stage (planner /
filter / synthesise) conditions on.

The stage is one LLM call, ~250 output tokens, ``temperature=0.2``,
gated by the ``<STANCE>{...}</STANCE>`` delimiter. Parser failures
return ``None`` rather than raising — the debate keeps running on the
legacy Phase-11 path until ``settings.stance_analysis_enabled`` flips
on (default off, per Phase 18 exit criteria).

This module is intentionally pure: no I/O, no engine imports. The only
LLM I/O is through the same ``stream_chat`` Protocol the rest of the
research pipeline uses, injected by the caller.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any, Final, Literal, Protocol

__all__ = [
    "STANCE_SYSTEM_PROMPT",
    "StanceBrief",
    "analyse_topic",
    "render_stance_lines",
]

_log = logging.getLogger(__name__)

AgentId = Literal["offender", "defender"]

# --- hard caps (mirror docs/research/agentic_research.md §2.1) -------------

_THESIS_WORD_CAP: Final[int] = 30
_CLAIM_WORD_CAP: Final[int] = 20
_MIN_CLAIMS: Final[int] = 3
_MAX_CLAIMS: Final[int] = 5
_MIN_COUNTERCLAIMS: Final[int] = 3
_MAX_COUNTERCLAIMS: Final[int] = 5
_MIN_ENTITIES: Final[int] = 3
_MAX_ENTITIES: Final[int] = 8


STANCE_SYSTEM_PROMPT: Final[str] = (
    "You are a debate-prep assistant. Read the TOPIC and the agent's "
    "POSITION, then produce a structured stance brief.\n\n"
    "OUTPUT: a single <STANCE>{...}</STANCE> block containing one JSON "
    "object. No prose before or after. No markdown. No code fences.\n\n"
    "When the topic is ambiguous, COMMIT to one reading; do not hedge.\n"
    "The brief MUST be defensible without any web search.\n\n"
    "JSON schema (all fields required):\n"
    '  - "topic":                   string, the topic verbatim.\n'
    '  - "agent_id":                "offender" | "defender".\n'
    '  - "position":                "for" | "against".\n'
    '  - "thesis":                  one sentence, <= 30 words.\n'
    '  - "key_claims":              array of 3-5 strings, each <= 20 words.\n'
    '  - "expected_counterclaims":  array of 3-5 strings, each <= 20 words.\n'
    '  - "entities":                array of 3-8 short noun/org strings '
    "(named anchors for searches).\n\n"
    "If you violate any cap or schema rule the output is discarded."
)


def _user_message(topic: str, agent_id: AgentId) -> str:
    position = "against" if agent_id == "offender" else "for"
    return (
        f'TOPIC: "{topic}"\n'
        f"AGENT_ID: {agent_id}\n"
        f"POSITION: {position}\n"
        "Reply with the <STANCE>{...}</STANCE> block."
    )


@dataclass(frozen=True)
class StanceBrief:
    """Structured stance for a single debate agent.

    Field caps mirror :data:`STANCE_SYSTEM_PROMPT` and
    ``docs/research/agentic_research.md`` §2.1. The constructor enforces
    them so a malformed LLM payload that survives JSON parsing still
    fails fast at the dataclass boundary.
    """

    topic: str
    agent_id: AgentId
    position: Literal["for", "against"]
    thesis: str
    key_claims: tuple[str, ...] = field(default_factory=tuple)
    expected_counterclaims: tuple[str, ...] = field(default_factory=tuple)
    entities: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.topic.strip():
            raise ValueError("topic must not be empty")
        if self.agent_id not in ("offender", "defender"):
            raise ValueError(f"agent_id must be offender|defender, got {self.agent_id!r}")
        if self.position not in ("for", "against"):
            raise ValueError(f"position must be for|against, got {self.position!r}")
        if not self.thesis.strip():
            raise ValueError("thesis must not be empty")
        if len(self.thesis.split()) > _THESIS_WORD_CAP:
            raise ValueError(f"thesis exceeds {_THESIS_WORD_CAP}-word cap")
        if not (_MIN_CLAIMS <= len(self.key_claims) <= _MAX_CLAIMS):
            raise ValueError(
                f"key_claims must have {_MIN_CLAIMS}-{_MAX_CLAIMS} entries, "
                f"got {len(self.key_claims)}",
            )
        if not (_MIN_COUNTERCLAIMS <= len(self.expected_counterclaims) <= _MAX_COUNTERCLAIMS):
            raise ValueError(
                "expected_counterclaims must have "
                f"{_MIN_COUNTERCLAIMS}-{_MAX_COUNTERCLAIMS} entries, "
                f"got {len(self.expected_counterclaims)}",
            )
        if not (_MIN_ENTITIES <= len(self.entities) <= _MAX_ENTITIES):
            raise ValueError(
                f"entities must have {_MIN_ENTITIES}-{_MAX_ENTITIES} entries, "
                f"got {len(self.entities)}",
            )
        for label, items in (
            ("key_claims", self.key_claims),
            ("expected_counterclaims", self.expected_counterclaims),
        ):
            for entry in items:
                if not entry.strip():
                    raise ValueError(f"{label} entries must not be empty")
                if len(entry.split()) > _CLAIM_WORD_CAP:
                    raise ValueError(
                        f"{label} entry exceeds {_CLAIM_WORD_CAP}-word cap: {entry!r}",
                    )
        for entity in self.entities:
            if not entity.strip():
                raise ValueError("entities must not be empty")


class _LLMClient(Protocol):
    def stream_chat(
        self,
        messages: list[dict[str, Any]],
        *,
        options: dict[str, Any] | None = ...,
        model: str | None = ...,
    ) -> Iterator[str]: ...


_STANCE_BLOCK_RE: Final[re.Pattern[str]] = re.compile(
    r"<STANCE>\s*(\{[\s\S]*?\})\s*</STANCE>",
    re.IGNORECASE,
)
_BARE_OBJECT_RE: Final[re.Pattern[str]] = re.compile(r"\{[\s\S]*\}")


def _strip_code_fence(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"```\s*$", "", text)
    return text.strip()


def _extract_json_object(raw: str) -> str | None:
    cleaned = _strip_code_fence(raw)
    block = _STANCE_BLOCK_RE.search(cleaned)
    if block is not None:
        return block.group(1)
    bare = _BARE_OBJECT_RE.search(cleaned)
    if bare is not None:
        return bare.group(0)
    return None


def _coerce_string_list(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    out: list[str] = []
    for item in value:
        if isinstance(item, str) and item.strip():
            out.append(item.strip())
    return tuple(out)


def _parse_stance(
    raw: str,
    *,
    topic: str,
    agent_id: AgentId,
) -> StanceBrief | None:
    """Parse the LLM output into a :class:`StanceBrief` or ``None``."""
    payload = _extract_json_object(raw)
    if payload is None:
        return None
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None

    expected_position: Literal["for", "against"] = "against" if agent_id == "offender" else "for"
    raw_position = str(data.get("position", "")).strip().lower()
    position: Literal["for", "against"]
    if raw_position == "for":
        position = "for"
    elif raw_position == "against":
        position = "against"
    else:
        position = expected_position

    thesis = str(data.get("thesis", "")).strip()
    if not thesis:
        return None

    try:
        return StanceBrief(
            topic=topic,
            agent_id=agent_id,
            position=position,
            thesis=thesis,
            key_claims=_coerce_string_list(data.get("key_claims")),
            expected_counterclaims=_coerce_string_list(data.get("expected_counterclaims")),
            entities=_coerce_string_list(data.get("entities")),
        )
    except ValueError as exc:
        _log.debug("stance brief failed validation: %s", exc)
        return None


def analyse_topic(
    client: _LLMClient,
    topic: str,
    agent_id: AgentId,
    *,
    model: str | None = None,
) -> StanceBrief | None:
    """Run one LLM call and return the agent's :class:`StanceBrief`.

    Returns ``None`` if the LLM raises, the output cannot be parsed, or
    the parsed brief fails any field cap. The caller is expected to log
    the failure and continue without a stance — this function never
    crashes the debate.
    """
    if not topic.strip():
        raise ValueError("topic must not be empty")
    if agent_id not in ("offender", "defender"):
        raise ValueError(f"agent_id must be offender|defender, got {agent_id!r}")

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": STANCE_SYSTEM_PROMPT},
        {"role": "user", "content": _user_message(topic, agent_id)},
    ]
    options: dict[str, Any] = {"temperature": 0.2, "num_predict": 256}
    try:
        if model is None:
            raw = "".join(client.stream_chat(messages, options=options))
        else:
            raw = "".join(client.stream_chat(messages, options=options, model=model))
    except Exception:
        _log.exception("stance analyse_topic LLM call failed for agent=%s", agent_id)
        return None

    brief = _parse_stance(raw, topic=topic, agent_id=agent_id)
    if brief is None:
        _log.warning(
            "stance analyse_topic: malformed output for agent=%s; falling back",
            agent_id,
        )
    return brief


def render_stance_lines(brief: StanceBrief) -> tuple[str, ...]:
    """Render a :class:`StanceBrief` as bullets for ``AgentMemory.stance``.

    The lines are short ``label: value`` pairs that the speaking prompt
    sees verbatim through the ``<MEMORY>`` block. Order is fixed:
    thesis → key claims → expected counterclaims → entities.
    """
    lines: list[str] = [f"Thesis ({brief.position}): {brief.thesis}"]
    for i, claim in enumerate(brief.key_claims, start=1):
        lines.append(f"Key claim {i}: {claim}")
    for i, counter in enumerate(brief.expected_counterclaims, start=1):
        lines.append(f"Expected counterclaim {i}: {counter}")
    if brief.entities:
        lines.append("Entities: " + ", ".join(brief.entities))
    return tuple(lines)
