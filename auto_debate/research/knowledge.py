"""
knowledge.py — Structured, attributed Knowledge synthesis (Phase 21).

Part of the Auto Debate project. See PROJECT.md, ROADMAP.md and the
design contract in ``docs/research/agentic_research.md`` §2.4.

Stage D — the final stage of the four-stage research pipeline
(``stance → plan → filter → synthesise``). Reads the kept
:class:`~auto_debate.research.filter.FilteredHit`s for one agent and
collapses them into ≤ 10 attributed :class:`KnowledgeEntry` bullets,
grouped by ``claim_index``, with hallucination-resistant attribution
prefixes.

The stage is a *single* LLM call (``temperature=0.2``,
``num_predict=512``) gated by the ``<KNOWLEDGE>{...}</KNOWLEDGE>``
delimiter. Failures degrade gracefully — the agent's Knowledge section
falls back to a fixed sentinel rather than crashing the debate.

Key invariants enforced by the deterministic citation linter (no LLM
involvement):

* Each entry's ``body`` is ≤ 30 words.
* Any ``"..."`` quoted phrase in ``body`` MUST appear verbatim
  (case-insensitive, whitespace-collapsed) in the matched
  ``FilteredHit.result.snippet``. Linter failures drop the entry.
* The attribution prefix is generated from a fixed per-``source_kind``
  template — the LLM never invents an outlet name. Only the URL host
  fragment fills the placeholder, so the worst case is "From
  example.com".
* ≤ 2 entries per ``claim_index``; ≤ 10 entries total.

Persistence: when a ``run_root`` is supplied to
:func:`synthesise_knowledge`, the resulting bullets are written to
``<run_root>/<run_id>/research/<agent>.knowledge.json`` for audit.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Protocol
from urllib.parse import urlparse

from auto_debate.research.filter import FilteredHit
from auto_debate.research.planner import VALID_SOURCE_KINDS, SourceKind
from auto_debate.research.stance import StanceBrief

__all__ = [
    "FALLBACK_KNOWLEDGE_LINE",
    "KNOWLEDGE_SYSTEM_PROMPT",
    "MAX_ENTRIES_PER_CLAIM",
    "MAX_KNOWLEDGE_ENTRIES",
    "KnowledgeEntry",
    "citation_lint",
    "format_knowledge_entry",
    "persist_knowledge",
    "render_knowledge_lines",
    "synthesise_knowledge",
]

_log = logging.getLogger(__name__)


# --- hard caps (mirror docs/research/agentic_research.md §2.4) -------------

MAX_KNOWLEDGE_ENTRIES: Final[int] = 10
MAX_ENTRIES_PER_CLAIM: Final[int] = 2
_BODY_WORD_CAP: Final[int] = 30
_KNOWLEDGE_NUM_PREDICT: Final[int] = 512
FALLBACK_KNOWLEDGE_LINE: Final[str] = "No verified sources for this turn."


KNOWLEDGE_SYSTEM_PROMPT: Final[str] = (
    "You are writing the agent's Knowledge section. Group the kept "
    "hits by claim_index, deduplicate near-identical claims, and "
    "compose a one-line attributed bullet for each remaining hit.\n\n"
    "OUTPUT: a single <KNOWLEDGE>{...}</KNOWLEDGE> block containing "
    "one JSON object. No prose before or after. No markdown. No code "
    "fences.\n\n"
    "RULES (an entry that violates any rule is discarded):\n"
    "  - Each entry's body is a paraphrase, <= 30 words.\n"
    "  - Each entry MAY quote at most one phrase from the source "
    'snippet (wrapped in straight double quotes, "like this"). The '
    "quoted phrase MUST appear verbatim in the snippet.\n"
    "  - Do NOT invent outlet names, authors, or dates. The system "
    "renders the attribution prefix from the URL itself.\n"
    "  - At most 2 entries per claim_index, at most 10 entries total.\n"
    "  - Drop near-duplicates: do not emit two entries that say the "
    "same thing.\n\n"
    "JSON schema:\n"
    '  - "entries": array of objects, each with:\n'
    '      - "claim_index":  integer, 0-based index into key_claims.\n'
    '      - "source_kind":  one of '
    '{"paper", "news", "forum", "wiki", "blog", "other"}.\n'
    '      - "body":         string, <= 30 words.\n'
    '      - "url":          string, MUST match a kept hit URL.\n'
    '      - "confidence":   number in [0.0, 1.0].\n'
)


# --- attribution templates (LLM never names outlets) -----------------------


def _domain_from_url(url: str) -> str:
    try:
        host = urlparse(url).netloc.lower().split(":", 1)[0]
    except (ValueError, AttributeError):
        return "the source"
    if not host:
        return "the source"
    if host.startswith("www."):
        host = host[4:]
    return host


def _attribution_for(source_kind: SourceKind, url: str) -> str:
    """Render the fixed attribution prefix from ``source_kind`` + ``url``.

    The LLM never sees a free-form attribution slot — only the URL host
    is interpolated, so the worst case is e.g. "From example.com".
    """
    domain = _domain_from_url(url)
    if source_kind == "paper":
        return f"According to {domain}"
    if source_kind == "news":
        return f"In {domain}"
    if source_kind == "forum":
        return f"On {domain}"
    if source_kind == "wiki":
        return f"Per {domain}"
    if source_kind == "blog":
        return f"On {domain}"
    return f"From {domain}"


# --- dataclass -------------------------------------------------------------


@dataclass(frozen=True)
class KnowledgeEntry:
    """One attributed Knowledge bullet for a single agent.

    The ``attribution`` field is rendered deterministically from
    :func:`_attribution_for`; callers should not pass a free-form
    string. Tests instantiate :class:`KnowledgeEntry` directly using
    the helper :func:`make_entry` below.
    """

    claim_index: int
    source_kind: SourceKind
    attribution: str
    body: str
    url: str
    confidence: float

    def __post_init__(self) -> None:
        if self.claim_index < 0:
            raise ValueError(f"claim_index must be >= 0, got {self.claim_index}")
        if self.source_kind not in VALID_SOURCE_KINDS:
            raise ValueError(f"invalid source_kind: {self.source_kind!r}")
        if not self.attribution.strip():
            raise ValueError("attribution must not be empty")
        if not self.body.strip():
            raise ValueError("body must not be empty")
        if len(self.body.split()) > _BODY_WORD_CAP:
            raise ValueError(f"body exceeds {_BODY_WORD_CAP}-word cap")
        if not self.url.strip():
            raise ValueError("url must not be empty")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"confidence must be in [0,1], got {self.confidence}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim_index": self.claim_index,
            "source_kind": self.source_kind,
            "attribution": self.attribution,
            "body": self.body,
            "url": self.url,
            "confidence": self.confidence,
        }


def format_knowledge_entry(entry: KnowledgeEntry) -> str:
    """Render one entry to the single line stored in ``AgentMemory.knowledge``."""
    return f"[claim {entry.claim_index}] {entry.attribution}, {entry.body} ({entry.url})"


def render_knowledge_lines(entries: Iterable[KnowledgeEntry]) -> tuple[str, ...]:
    """Render entries into the Knowledge section lines, sorted by claim_index.

    Caller is responsible for passing entries that already passed the
    citation linter. Returns the fallback sentinel when empty.
    """
    sorted_entries = sorted(entries, key=lambda e: (e.claim_index, e.url))
    if not sorted_entries:
        return (FALLBACK_KNOWLEDGE_LINE,)
    return tuple(format_knowledge_entry(e) for e in sorted_entries)


# --- LLM transport ---------------------------------------------------------


class _LLMClient(Protocol):
    def stream_chat(
        self,
        messages: list[dict[str, Any]],
        *,
        options: dict[str, Any] | None = ...,
        model: str | None = ...,
    ) -> Iterator[str]: ...


_KNOWLEDGE_BLOCK_RE: Final[re.Pattern[str]] = re.compile(
    r"<KNOWLEDGE>\s*(\{[\s\S]*?\})\s*</KNOWLEDGE>",
    re.IGNORECASE,
)
_BARE_OBJECT_RE: Final[re.Pattern[str]] = re.compile(r"\{[\s\S]*\}")
_QUOTED_RE: Final[re.Pattern[str]] = re.compile(r'"([^"\n]+)"')
_WHITESPACE_RE: Final[re.Pattern[str]] = re.compile(r"\s+")


# --- parsing & linting -----------------------------------------------------


def _strip_code_fence(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"```\s*$", "", text)
    return text.strip()


def _extract_json_object(raw: str) -> str | None:
    cleaned = _strip_code_fence(raw)
    block = _KNOWLEDGE_BLOCK_RE.search(cleaned)
    if block is not None:
        return block.group(1)
    bare = _BARE_OBJECT_RE.search(cleaned)
    if bare is not None:
        return bare.group(0)
    return None


def _normalise(text: str) -> str:
    return _WHITESPACE_RE.sub(" ", text).strip().lower()


def citation_lint(body: str, snippet: str) -> bool:
    """Return ``True`` iff every quoted phrase in ``body`` appears verbatim
    (case-insensitive, whitespace-collapsed) inside ``snippet``.

    A body with no quoted phrases passes trivially.
    """
    haystack = _normalise(snippet)
    for match in _QUOTED_RE.finditer(body):
        phrase = _normalise(match.group(1))
        if not phrase:
            continue
        if phrase not in haystack:
            return False
    return True


def _coerce_source_kind(value: Any) -> SourceKind | None:
    if not isinstance(value, str):
        return None
    kind = value.strip().lower()
    if kind in VALID_SOURCE_KINDS:
        return kind  # type: ignore[return-value]
    return None


def _validate_entry(
    raw: dict[str, Any],
    *,
    brief: StanceBrief,
    hits_by_url: dict[str, FilteredHit],
) -> KnowledgeEntry | None:
    try:
        claim_index = int(raw.get("claim_index", -1))
    except (TypeError, ValueError):
        return None
    if not (0 <= claim_index < len(brief.key_claims)):
        return None

    body = str(raw.get("body", "")).strip()
    if not body or len(body.split()) > _BODY_WORD_CAP:
        return None

    url = str(raw.get("url", "")).strip()
    if not url:
        return None

    matched_hit = hits_by_url.get(url)
    if matched_hit is None:
        # The LLM hallucinated a URL not in the kept set.
        return None

    if not citation_lint(body, matched_hit.result.snippet):
        _log.warning("citation_lint dropped entry quoting absent phrase: url=%s", url)
        return None

    # Source kind: prefer the deterministic value from the FilteredHit;
    # accept the LLM's value only if it matches.
    source_kind: SourceKind = matched_hit.source_kind
    llm_kind = _coerce_source_kind(raw.get("source_kind"))
    if llm_kind is not None:
        source_kind = llm_kind if llm_kind == matched_hit.source_kind else matched_hit.source_kind

    confidence_raw = raw.get("confidence", 0.0)
    try:
        confidence = float(confidence_raw)
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))

    attribution = _attribution_for(source_kind, url)

    try:
        return KnowledgeEntry(
            claim_index=claim_index,
            source_kind=source_kind,
            attribution=attribution,
            body=body,
            url=url,
            confidence=confidence,
        )
    except ValueError:
        return None


def _enforce_caps(entries: list[KnowledgeEntry]) -> list[KnowledgeEntry]:
    """Apply per-claim and total caps. Order of incoming entries is preserved
    within each claim group (LLM ranking is respected)."""
    seen_per_claim: dict[int, int] = {}
    seen_urls: set[str] = set()
    out: list[KnowledgeEntry] = []
    for entry in entries:
        if entry.url in seen_urls:
            continue
        count = seen_per_claim.get(entry.claim_index, 0)
        if count >= MAX_ENTRIES_PER_CLAIM:
            continue
        out.append(entry)
        seen_urls.add(entry.url)
        seen_per_claim[entry.claim_index] = count + 1
        if len(out) >= MAX_KNOWLEDGE_ENTRIES:
            break
    return out


def _parse_knowledge(
    raw: str,
    *,
    brief: StanceBrief,
    kept_hits: list[FilteredHit],
) -> list[KnowledgeEntry]:
    payload = _extract_json_object(raw)
    if payload is None:
        return []
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, dict):
        return []
    raw_entries = data.get("entries")
    if not isinstance(raw_entries, list):
        return []

    hits_by_url: dict[str, FilteredHit] = {h.result.url: h for h in kept_hits}
    out: list[KnowledgeEntry] = []
    for entry in raw_entries:
        if not isinstance(entry, dict):
            continue
        validated = _validate_entry(entry, brief=brief, hits_by_url=hits_by_url)
        if validated is not None:
            out.append(validated)
    return _enforce_caps(out)


# --- user message ----------------------------------------------------------


def _hits_payload(kept_hits: list[FilteredHit]) -> list[dict[str, Any]]:
    payload: list[dict[str, Any]] = []
    for hit in kept_hits:
        payload.append(
            {
                "url": hit.result.url,
                "title": hit.result.title,
                "snippet": hit.result.snippet,
                "source_kind": hit.source_kind,
                "supports_claim": hit.supports_claim,
            },
        )
    return payload


def _user_message(brief: StanceBrief, kept_hits: list[FilteredHit]) -> str:
    stance_payload: dict[str, Any] = {
        "topic": brief.topic,
        "agent_id": brief.agent_id,
        "position": brief.position,
        "thesis": brief.thesis,
        "key_claims": list(brief.key_claims),
    }
    return (
        f"<STANCE>{json.dumps(stance_payload, ensure_ascii=False)}</STANCE>\n"
        f"<HITS>{json.dumps(_hits_payload(kept_hits), ensure_ascii=False)}</HITS>"
    )


# --- public API ------------------------------------------------------------


def persist_knowledge(
    entries: list[KnowledgeEntry],
    *,
    run_root: Path,
    run_id: str,
    agent_id: str,
) -> Path:
    """Write ``entries`` to ``run_root/run_id/research/<agent>.knowledge.json``.

    The file always exists on return (an empty list is serialised as
    ``[]``). Returns the path written.
    """
    target_dir = run_root / run_id / "research"
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / f"{agent_id}.knowledge.json"
    path.write_text(
        json.dumps([e.to_dict() for e in entries], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return path


def synthesise_knowledge(
    client: _LLMClient,
    brief: StanceBrief,
    kept_hits: list[FilteredHit],
    *,
    model: str | None = None,
    run_root: Path | None = None,
    run_id: str | None = None,
) -> list[KnowledgeEntry]:
    """Run one LLM call and return ≤ 10 attributed :class:`KnowledgeEntry`.

    Always returns a list (never raises). On LLM error / malformed JSON
    / total citation-linter failure, the returned list is empty — the
    caller is expected to render the
    :data:`FALLBACK_KNOWLEDGE_LINE` sentinel.

    When ``kept_hits`` is empty, no LLM call is made.

    When both ``run_root`` and ``run_id`` are supplied, the entries are
    persisted to ``<run_root>/<run_id>/research/<agent>.knowledge.json``.
    """
    if not kept_hits:
        if run_root is not None and run_id is not None:
            try:
                persist_knowledge(
                    [],
                    run_root=run_root,
                    run_id=run_id,
                    agent_id=brief.agent_id,
                )
            except OSError:
                _log.exception(
                    "failed to persist empty knowledge for agent=%s",
                    brief.agent_id,
                )
        return []

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": KNOWLEDGE_SYSTEM_PROMPT},
        {"role": "user", "content": _user_message(brief, kept_hits)},
    ]
    options: dict[str, Any] = {"temperature": 0.2, "num_predict": _KNOWLEDGE_NUM_PREDICT}

    raw = ""
    try:
        if model is None:
            raw = "".join(client.stream_chat(messages, options=options))
        else:
            raw = "".join(client.stream_chat(messages, options=options, model=model))
    except Exception:
        _log.exception(
            "knowledge LLM call failed for agent=%s; falling back to empty entries",
            brief.agent_id,
        )

    entries = _parse_knowledge(raw, brief=brief, kept_hits=kept_hits)

    if not entries and raw:
        _log.warning(
            "knowledge synthesis produced 0 valid entries for agent=%s",
            brief.agent_id,
        )

    if run_root is not None and run_id is not None:
        try:
            persist_knowledge(
                entries,
                run_root=run_root,
                run_id=run_id,
                agent_id=brief.agent_id,
            )
        except OSError:
            _log.exception("failed to persist knowledge for agent=%s", brief.agent_id)

    return entries


# Re-exports for unit tests.
_parse_knowledge_for_tests = _parse_knowledge
_attribution_for_tests = _attribution_for
