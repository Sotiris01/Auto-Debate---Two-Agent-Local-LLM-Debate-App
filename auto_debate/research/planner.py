"""
planner.py — Stance-driven query planner (Phase 19).

Part of the Auto Debate project. See PROJECT.md, ROADMAP.md and the
design contract in ``docs/research/agentic_research.md`` §2.2.

Stage B of the four-stage research pipeline (stance → plan → filter →
synthesise). Reads a :class:`~auto_debate.research.stance.StanceBrief`
and produces 5-8 diverse, claim-anchored web-search queries. Every
query references at least one ``key_claim`` index from the brief, at
least one query targets an ``expected_counterclaim``, and queries are
deterministically de-duplicated by token-set Jaccard ≥ 0.6.

The stage is a single LLM call (``temperature=0.3``,
``num_predict=384``), gated by the ``<PLAN>{...}</PLAN>`` delimiter.
Parser/validation failures degrade gracefully via a deterministic
fallback so the search stage never starves; the planner never crashes
the debate.

Persistence: when a ``run_root`` is supplied to :func:`plan_queries`,
the resulting plan is written to
``<run_root>/<run_id>/research/<agent>.plan.json`` for audit.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final, Literal, Protocol

from auto_debate.research.stance import StanceBrief

__all__ = [
    "JACCARD_DEDUP_THRESHOLD",
    "MAX_QUERIES",
    "MIN_QUERIES_BEFORE_FALLBACK",
    "PLANNER_SYSTEM_PROMPT",
    "VALID_SOURCE_KINDS",
    "PlannedQuery",
    "QueryPlan",
    "persist_plan",
    "plan_queries",
]

_log = logging.getLogger(__name__)

SourceKind = Literal["paper", "news", "forum", "wiki", "blog", "other"]
VALID_SOURCE_KINDS: Final[frozenset[str]] = frozenset(
    {"paper", "news", "forum", "wiki", "blog", "other"},
)

# --- hard caps (mirror docs/research/agentic_research.md §2.2) -------------

_MIN_QUERIES: Final[int] = 5
MAX_QUERIES: Final[int] = 8
MIN_QUERIES_BEFORE_FALLBACK: Final[int] = 3
_QUERY_WORD_CAP: Final[int] = 12
JACCARD_DEDUP_THRESHOLD: Final[float] = 0.6


PLANNER_SYSTEM_PROMPT: Final[str] = (
    "You are planning web searches for a debate agent. Read the stance "
    "brief and produce 5-8 search queries. OUTPUT: a single "
    "<PLAN>{...}</PLAN> block containing one JSON object. No prose "
    "before or after. No markdown. No code fences.\n\n"
    "RULES (a query that violates any rule is discarded):\n"
    "  - Every query MUST reference at least one key_claim by index.\n"
    "  - At least one query MUST target an expected_counterclaim "
    "so the agent can pre-empt it.\n"
    "  - Queries MUST be diverse: no two queries may share more than "
    "60% of their tokens (Jaccard).\n"
    "  - Every query MUST contain at least one entity from the brief.\n"
    "  - Queries are short web-search strings (<= 12 words), NOT "
    "questions.\n\n"
    "JSON schema:\n"
    '  - "agent_id":   "offender" | "defender".\n'
    '  - "queries":    array of 5-8 objects, each with:\n'
    '      - "text":                  string, <= 12 words.\n'
    '      - "target_claim":          integer, 0-based index into '
    "key_claims.\n"
    '      - "expected_source_kinds": array of 1+ strings drawn from '
    '{"paper", "news", "forum", "wiki", "blog", "other"}.\n'
)


def _user_message(brief: StanceBrief) -> str:
    payload: dict[str, Any] = {
        "topic": brief.topic,
        "agent_id": brief.agent_id,
        "position": brief.position,
        "thesis": brief.thesis,
        "key_claims": list(brief.key_claims),
        "expected_counterclaims": list(brief.expected_counterclaims),
        "entities": list(brief.entities),
    }
    return f"<STANCE>{json.dumps(payload, ensure_ascii=False)}</STANCE>"


# --- dataclasses -----------------------------------------------------------


@dataclass(frozen=True)
class PlannedQuery:
    """One planned web-search query, anchored to a stance claim."""

    text: str
    target_claim: int
    expected_source_kinds: tuple[SourceKind, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise ValueError("query text must not be empty")
        if len(self.text.split()) > _QUERY_WORD_CAP:
            raise ValueError(
                f"query text exceeds {_QUERY_WORD_CAP}-word cap: {self.text!r}",
            )
        if self.target_claim < 0:
            raise ValueError(f"target_claim must be >= 0, got {self.target_claim}")
        if not self.expected_source_kinds:
            raise ValueError("expected_source_kinds must not be empty")
        for kind in self.expected_source_kinds:
            if kind not in VALID_SOURCE_KINDS:
                raise ValueError(f"invalid source_kind: {kind!r}")


@dataclass(frozen=True)
class QueryPlan:
    """A complete 5-8 query plan for one debate agent."""

    agent_id: Literal["offender", "defender"]
    queries: tuple[PlannedQuery, ...]

    def __post_init__(self) -> None:
        if self.agent_id not in ("offender", "defender"):
            raise ValueError(f"agent_id must be offender|defender, got {self.agent_id!r}")
        if not self.queries:
            raise ValueError("QueryPlan must have at least one query")
        if len(self.queries) > MAX_QUERIES:
            raise ValueError(f"QueryPlan exceeds {MAX_QUERIES}-query cap")

    def texts(self) -> tuple[str, ...]:
        return tuple(q.text for q in self.queries)

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "queries": [
                {
                    "text": q.text,
                    "target_claim": q.target_claim,
                    "expected_source_kinds": list(q.expected_source_kinds),
                }
                for q in self.queries
            ],
        }


# --- LLM transport ---------------------------------------------------------


class _LLMClient(Protocol):
    def stream_chat(
        self,
        messages: list[dict[str, Any]],
        *,
        options: dict[str, Any] | None = ...,
        model: str | None = ...,
    ) -> Iterator[str]: ...


_PLAN_BLOCK_RE: Final[re.Pattern[str]] = re.compile(
    r"<PLAN>\s*(\{[\s\S]*?\})\s*</PLAN>",
    re.IGNORECASE,
)
_BARE_OBJECT_RE: Final[re.Pattern[str]] = re.compile(r"\{[\s\S]*\}")
_TOKEN_RE: Final[re.Pattern[str]] = re.compile(r"[a-z0-9]+")


# --- parsing & validation --------------------------------------------------


def _strip_code_fence(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"```\s*$", "", text)
    return text.strip()


def _extract_json_object(raw: str) -> str | None:
    cleaned = _strip_code_fence(raw)
    block = _PLAN_BLOCK_RE.search(cleaned)
    if block is not None:
        return block.group(1)
    bare = _BARE_OBJECT_RE.search(cleaned)
    if bare is not None:
        return bare.group(0)
    return None


def _tokens(text: str) -> set[str]:
    return set(_TOKEN_RE.findall(text.lower()))


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _coerce_source_kinds(value: Any) -> tuple[SourceKind, ...]:
    if not isinstance(value, list):
        return ()
    out: list[SourceKind] = []
    for item in value:
        if isinstance(item, str):
            kind = item.strip().lower()
            if kind in VALID_SOURCE_KINDS and kind not in out:
                out.append(kind)  # type: ignore[arg-type]
    return tuple(out)


def _validate_query(
    raw: dict[str, Any],
    *,
    brief: StanceBrief,
) -> PlannedQuery | None:
    text = str(raw.get("text", "")).strip()
    if not text:
        return None
    if len(text.split()) > _QUERY_WORD_CAP:
        return None
    try:
        target = int(raw.get("target_claim", -1))
    except (TypeError, ValueError):
        return None
    if not (0 <= target < len(brief.key_claims)):
        return None
    kinds = _coerce_source_kinds(raw.get("expected_source_kinds"))
    if not kinds:
        # When the LLM omits the field we tolerate one default rather
        # than reject the query — the search adapter does not act on it.
        kinds = ("other",)
    # Entity grounding: the query MUST mention at least one entity.
    text_lower = text.lower()
    if not any(entity.lower() in text_lower for entity in brief.entities if entity.strip()):
        return None
    try:
        return PlannedQuery(
            text=text,
            target_claim=target,
            expected_source_kinds=kinds,
        )
    except ValueError:
        return None


def _dedup_by_jaccard(queries: list[PlannedQuery]) -> list[PlannedQuery]:
    """Drop later queries whose token-set Jaccard with any earlier
    accepted query is ``>= JACCARD_DEDUP_THRESHOLD``."""
    kept: list[PlannedQuery] = []
    kept_tokens: list[set[str]] = []
    for q in queries:
        toks = _tokens(q.text)
        if any(_jaccard(toks, prev) >= JACCARD_DEDUP_THRESHOLD for prev in kept_tokens):
            continue
        kept.append(q)
        kept_tokens.append(toks)
    return kept


def _parse_plan(
    raw: str,
    *,
    brief: StanceBrief,
) -> list[PlannedQuery]:
    payload = _extract_json_object(raw)
    if payload is None:
        return []
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, dict):
        return []
    raw_queries = data.get("queries")
    if not isinstance(raw_queries, list):
        return []
    out: list[PlannedQuery] = []
    for entry in raw_queries:
        if not isinstance(entry, dict):
            continue
        query = _validate_query(entry, brief=brief)
        if query is not None:
            out.append(query)
    return _dedup_by_jaccard(out)[:MAX_QUERIES]


# --- fallback --------------------------------------------------------------


def _fallback_queries(brief: StanceBrief) -> list[PlannedQuery]:
    """Deterministic 3-query fallback used when the LLM under-delivers.

    Mirrors §2.2: ``(topic_as_query, thesis_as_query,
    entity[0] + thesis_keywords)``. All queries point at claim 0; word
    cap is enforced via truncation so the fallback always validates.
    """
    entity = brief.entities[0] if brief.entities else brief.topic.split()[0]
    thesis_words = brief.thesis.split()
    thesis_short = " ".join(thesis_words[:_QUERY_WORD_CAP])
    thesis_keywords = " ".join(w for w in thesis_words if len(w) > 4).split()[: _QUERY_WORD_CAP - 1]
    candidates = [
        " ".join(brief.topic.split()[:_QUERY_WORD_CAP]),
        thesis_short,
        f"{entity} {' '.join(thesis_keywords)}".strip(),
    ]
    out: list[PlannedQuery] = []
    for text in candidates:
        if not text.strip():
            continue
        try:
            out.append(
                PlannedQuery(
                    text=text,
                    target_claim=0,
                    expected_source_kinds=("other",),
                ),
            )
        except ValueError:
            continue
    return _dedup_by_jaccard(out)


# --- public API ------------------------------------------------------------


def persist_plan(
    plan: QueryPlan,
    *,
    run_root: Path,
    run_id: str,
) -> Path:
    """Write ``plan`` to ``run_root/run_id/research/<agent>.plan.json``.

    The directory is created if missing. Returns the path written.
    """
    target_dir = run_root / run_id / "research"
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / f"{plan.agent_id}.plan.json"
    path.write_text(
        json.dumps(plan.to_dict(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return path


def plan_queries(
    client: _LLMClient,
    brief: StanceBrief,
    *,
    model: str | None = None,
    run_root: Path | None = None,
    run_id: str | None = None,
) -> QueryPlan:
    """Run one LLM call and return the agent's :class:`QueryPlan`.

    The plan always contains at least one query: if the LLM raises, or
    the parser yields fewer than :data:`MIN_QUERIES_BEFORE_FALLBACK`
    valid queries, the deterministic 3-query fallback is appended.

    When both ``run_root`` and ``run_id`` are supplied the plan is also
    persisted to ``<run_root>/<run_id>/research/<agent>.plan.json``.
    """
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": PLANNER_SYSTEM_PROMPT},
        {"role": "user", "content": _user_message(brief)},
    ]
    options: dict[str, Any] = {"temperature": 0.3, "num_predict": 384}
    raw = ""
    try:
        if model is None:
            raw = "".join(client.stream_chat(messages, options=options))
        else:
            raw = "".join(client.stream_chat(messages, options=options, model=model))
    except Exception:
        _log.exception(
            "planner LLM call failed for agent=%s; using deterministic fallback",
            brief.agent_id,
        )

    queries = _parse_plan(raw, brief=brief)
    if len(queries) < MIN_QUERIES_BEFORE_FALLBACK:
        if raw:
            _log.warning(
                "planner produced only %d valid queries for agent=%s; appending fallback",
                len(queries),
                brief.agent_id,
            )
        # Append fallback queries while preserving any LLM queries we did salvage.
        for q in _fallback_queries(brief):
            queries.append(q)
        queries = _dedup_by_jaccard(queries)[:MAX_QUERIES]

    plan = QueryPlan(agent_id=brief.agent_id, queries=tuple(queries))

    if run_root is not None and run_id is not None:
        try:
            persist_plan(plan, run_root=run_root, run_id=run_id)
        except OSError:
            _log.exception("failed to persist plan for agent=%s", brief.agent_id)

    return plan


# Re-export the parser for unit tests.
_parse_plan_for_tests = _parse_plan
_fallback_for_tests = _fallback_queries
