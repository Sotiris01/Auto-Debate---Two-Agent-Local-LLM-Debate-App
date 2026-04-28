"""Tests for the Phase 21 attributed Knowledge synthesis."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from auto_debate.research import (
    FALLBACK_KNOWLEDGE_LINE,
    KNOWLEDGE_SYSTEM_PROMPT,
    FilteredHit,
    KnowledgeEntry,
    SearchResult,
    StanceBrief,
    citation_lint,
    format_knowledge_entry,
    persist_knowledge,
    render_knowledge_lines,
    synthesise_knowledge,
)
from auto_debate.research.knowledge import (
    MAX_ENTRIES_PER_CLAIM,
    MAX_KNOWLEDGE_ENTRIES,
    _attribution_for_tests,
    _parse_knowledge_for_tests,
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
        entities=("urban planning", "EPA", "transit"),
    )


def _hit(
    *,
    url: str = "https://www.nytimes.com/2024/cars-cities.html",
    snippet: str = (
        "EPA reports show private cars consume vast urban land per "
        "passenger compared to buses and trains."
    ),
    source_kind: str = "news",
    supports_claim: int = 0,
) -> FilteredHit:
    return FilteredHit(
        result=SearchResult(
            title="Cars and cities",
            url=url,
            snippet=snippet,
            fetched_at="2026-04-28T12:00:00Z",
        ),
        query="cars urban land",
        verdict="keep",
        reason="ok",
        supports_claim=supports_claim,
        confidence=0.9,
        source_kind=source_kind,  # type: ignore[arg-type]
    )


def _wrap(payload: dict[str, Any]) -> str:
    return f"<KNOWLEDGE>{json.dumps(payload)}</KNOWLEDGE>"


class _ScriptedClient:
    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.calls: list[list[dict[str, Any]]] = []
        self.options: list[dict[str, Any] | None] = []

    def stream_chat(
        self,
        messages: list[dict[str, Any]],
        *,
        options: dict[str, Any] | None = None,
        model: str | None = None,
    ) -> Iterator[str]:
        self.calls.append(messages)
        self.options.append(options)
        if not self._responses:
            raise AssertionError("no scripted responses left")
        yield self._responses.pop(0)


class _BoomClient:
    def stream_chat(
        self,
        messages: list[dict[str, Any]],
        *,
        options: dict[str, Any] | None = None,
        model: str | None = None,
    ) -> Iterator[str]:
        raise RuntimeError("LLM unavailable")
        yield ""  # pragma: no cover


# --- attribution templates --------------------------------------------------


@pytest.mark.parametrize(
    ("kind", "url", "expected"),
    [
        ("paper", "https://arxiv.org/abs/2401.0001", "According to arxiv.org"),
        ("news", "https://www.nytimes.com/2024/x.html", "In nytimes.com"),
        ("forum", "https://www.reddit.com/r/x", "On reddit.com"),
        ("wiki", "https://en.wikipedia.org/wiki/X", "Per en.wikipedia.org"),
        ("blog", "https://example.medium.com/x", "On example.medium.com"),
        ("other", "https://example.com/x", "From example.com"),
    ],
)
def test_attribution_for_each_source_kind(kind: str, url: str, expected: str) -> None:
    assert _attribution_for_tests(kind, url) == expected  # type: ignore[arg-type]


# --- citation linter --------------------------------------------------------


def test_citation_lint_passes_with_no_quotes() -> None:
    assert citation_lint("private cars consume more urban land", "irrelevant snippet")


def test_citation_lint_passes_with_verbatim_quote() -> None:
    snippet = "EPA reports show private cars consume vast urban land."
    body = 'EPA reports note "private cars consume vast urban land".'
    assert citation_lint(body, snippet)


def test_citation_lint_rejects_fabricated_quote() -> None:
    snippet = "EPA reports show private cars consume vast urban land."
    body = 'The agency claims "cars cause global warming directly".'
    assert not citation_lint(body, snippet)


def test_citation_lint_is_case_insensitive_and_collapses_whitespace() -> None:
    snippet = "EPA  reports show   private cars consume vast urban land."
    body = 'Quote: "private CARS consume vast urban land".'
    assert citation_lint(body, snippet)


# --- KnowledgeEntry dataclass -----------------------------------------------


def test_knowledge_entry_rejects_negative_claim_index() -> None:
    with pytest.raises(ValueError, match="claim_index"):
        KnowledgeEntry(
            claim_index=-1,
            source_kind="news",
            attribution="In x",
            body="Body text.",
            url="https://x.com",
            confidence=0.5,
        )


def test_knowledge_entry_rejects_overlong_body() -> None:
    long_body = " ".join(f"w{i}" for i in range(40))
    with pytest.raises(ValueError, match="body exceeds"):
        KnowledgeEntry(
            claim_index=0,
            source_kind="news",
            attribution="In x",
            body=long_body,
            url="https://x.com",
            confidence=0.5,
        )


def test_knowledge_entry_rejects_invalid_source_kind() -> None:
    with pytest.raises(ValueError, match="source_kind"):
        KnowledgeEntry(
            claim_index=0,
            source_kind="bogus",  # type: ignore[arg-type]
            attribution="In x",
            body="Body.",
            url="https://x.com",
            confidence=0.5,
        )


def test_knowledge_entry_rejects_confidence_out_of_range() -> None:
    with pytest.raises(ValueError, match="confidence"):
        KnowledgeEntry(
            claim_index=0,
            source_kind="news",
            attribution="In x",
            body="Body.",
            url="https://x.com",
            confidence=1.5,
        )


# --- format / render --------------------------------------------------------


def test_format_knowledge_entry_renders_claim_marker() -> None:
    entry = KnowledgeEntry(
        claim_index=2,
        source_kind="news",
        attribution="In nytimes.com",
        body="Cars consume vast urban land.",
        url="https://nytimes.com/x",
        confidence=0.9,
    )
    line = format_knowledge_entry(entry)
    assert line.startswith("[claim 2] In nytimes.com,")
    assert line.endswith("(https://nytimes.com/x)")


def test_render_knowledge_lines_sorts_by_claim_index() -> None:
    e0 = KnowledgeEntry(0, "news", "In a.com", "A.", "https://a.com", 0.5)
    e2 = KnowledgeEntry(2, "news", "In b.com", "B.", "https://b.com", 0.5)
    e1 = KnowledgeEntry(1, "news", "In c.com", "C.", "https://c.com", 0.5)
    lines = render_knowledge_lines([e2, e0, e1])
    assert lines[0].startswith("[claim 0]")
    assert lines[1].startswith("[claim 1]")
    assert lines[2].startswith("[claim 2]")


def test_render_knowledge_lines_returns_fallback_when_empty() -> None:
    assert render_knowledge_lines([]) == (FALLBACK_KNOWLEDGE_LINE,)


# --- parser -----------------------------------------------------------------


def test_parse_knowledge_happy_path() -> None:
    hit = _hit()
    raw = _wrap(
        {
            "entries": [
                {
                    "claim_index": 0,
                    "source_kind": "news",
                    "body": "EPA data shows cars consume disproportionate urban land.",
                    "url": hit.result.url,
                    "confidence": 0.85,
                }
            ]
        }
    )
    entries = _parse_knowledge_for_tests(raw, brief=_brief(), kept_hits=[hit])
    assert len(entries) == 1
    assert entries[0].claim_index == 0
    assert entries[0].source_kind == "news"
    # Attribution rendered deterministically from the URL host.
    assert entries[0].attribution == "In nytimes.com"


def test_parse_knowledge_drops_entry_with_unknown_url() -> None:
    hit = _hit()
    raw = _wrap(
        {
            "entries": [
                {
                    "claim_index": 0,
                    "source_kind": "news",
                    "body": "Some claim about cars.",
                    "url": "https://hallucinated.example/never",
                    "confidence": 0.5,
                }
            ]
        }
    )
    assert _parse_knowledge_for_tests(raw, brief=_brief(), kept_hits=[hit]) == []


def test_parse_knowledge_drops_entry_with_fabricated_quote() -> None:
    hit = _hit(snippet="EPA reports show private cars consume vast urban land.")
    raw = _wrap(
        {
            "entries": [
                {
                    "claim_index": 0,
                    "source_kind": "news",
                    "body": 'The report says "cars cause global warming directly".',
                    "url": hit.result.url,
                    "confidence": 0.9,
                }
            ]
        }
    )
    assert _parse_knowledge_for_tests(raw, brief=_brief(), kept_hits=[hit]) == []


def test_parse_knowledge_keeps_entry_with_verbatim_quote() -> None:
    hit = _hit(snippet="EPA reports show private cars consume vast urban land.")
    raw = _wrap(
        {
            "entries": [
                {
                    "claim_index": 0,
                    "source_kind": "news",
                    "body": 'EPA notes "private cars consume vast urban land".',
                    "url": hit.result.url,
                    "confidence": 0.9,
                }
            ]
        }
    )
    entries = _parse_knowledge_for_tests(raw, brief=_brief(), kept_hits=[hit])
    assert len(entries) == 1


def test_parse_knowledge_drops_out_of_range_claim_index() -> None:
    hit = _hit()
    raw = _wrap(
        {
            "entries": [
                {
                    "claim_index": 99,
                    "source_kind": "news",
                    "body": "x.",
                    "url": hit.result.url,
                    "confidence": 0.5,
                }
            ]
        }
    )
    assert _parse_knowledge_for_tests(raw, brief=_brief(), kept_hits=[hit]) == []


def test_parse_knowledge_drops_overlong_body() -> None:
    hit = _hit()
    long_body = " ".join(f"w{i}" for i in range(40))
    raw = _wrap(
        {
            "entries": [
                {
                    "claim_index": 0,
                    "source_kind": "news",
                    "body": long_body,
                    "url": hit.result.url,
                    "confidence": 0.5,
                }
            ]
        }
    )
    assert _parse_knowledge_for_tests(raw, brief=_brief(), kept_hits=[hit]) == []


def test_parse_knowledge_garbage_returns_empty() -> None:
    assert _parse_knowledge_for_tests("garbage", brief=_brief(), kept_hits=[]) == []


def test_parse_knowledge_overrides_mismatched_source_kind_from_hit() -> None:
    """If the LLM lies about source_kind, the deterministic value from
    the FilteredHit wins."""
    hit = _hit()  # source_kind="news"
    raw = _wrap(
        {
            "entries": [
                {
                    "claim_index": 0,
                    "source_kind": "paper",  # LLM-claimed; will be overridden
                    "body": "Cars consume disproportionate urban land.",
                    "url": hit.result.url,
                    "confidence": 0.9,
                }
            ]
        }
    )
    entries = _parse_knowledge_for_tests(raw, brief=_brief(), kept_hits=[hit])
    assert len(entries) == 1
    assert entries[0].source_kind == "news"
    assert entries[0].attribution == "In nytimes.com"


def test_parse_knowledge_enforces_per_claim_cap() -> None:
    hits = [_hit(url=f"https://example{i}.com/x", source_kind="other") for i in range(5)]
    raw = _wrap(
        {
            "entries": [
                {
                    "claim_index": 0,
                    "source_kind": "other",
                    "body": f"Bullet {i}.",
                    "url": h.result.url,
                    "confidence": 0.5,
                }
                for i, h in enumerate(hits)
            ]
        }
    )
    entries = _parse_knowledge_for_tests(raw, brief=_brief(), kept_hits=hits)
    assert len(entries) == MAX_ENTRIES_PER_CLAIM


def test_parse_knowledge_enforces_total_cap() -> None:
    hits: list[FilteredHit] = []
    payload_entries: list[dict[str, Any]] = []
    for i in range(15):
        url = f"https://example{i}.com/x"
        hits.append(_hit(url=url, source_kind="other", supports_claim=i % 3))
        payload_entries.append(
            {
                "claim_index": i % 3,
                "source_kind": "other",
                "body": f"Bullet {i}.",
                "url": url,
                "confidence": 0.5,
            }
        )
    raw = _wrap({"entries": payload_entries})
    entries = _parse_knowledge_for_tests(raw, brief=_brief(), kept_hits=hits)
    # 3 claims * 2 each = 6 entries, well below the global cap; we should
    # be limited by the per-claim cap for this fixture.
    assert len(entries) <= MAX_KNOWLEDGE_ENTRIES
    per_claim: dict[int, int] = {}
    for e in entries:
        per_claim[e.claim_index] = per_claim.get(e.claim_index, 0) + 1
    assert all(c <= MAX_ENTRIES_PER_CLAIM for c in per_claim.values())


def test_parse_knowledge_drops_duplicate_urls() -> None:
    hit = _hit()
    raw = _wrap(
        {
            "entries": [
                {
                    "claim_index": 0,
                    "source_kind": "news",
                    "body": "First bullet.",
                    "url": hit.result.url,
                    "confidence": 0.9,
                },
                {
                    "claim_index": 1,
                    "source_kind": "news",
                    "body": "Duplicate URL bullet.",
                    "url": hit.result.url,
                    "confidence": 0.7,
                },
            ]
        }
    )
    entries = _parse_knowledge_for_tests(raw, brief=_brief(), kept_hits=[hit])
    assert len(entries) == 1


# --- synthesise_knowledge (LLM call) ----------------------------------------


def test_synthesise_knowledge_uses_system_prompt_and_temperature() -> None:
    hit = _hit()
    raw = _wrap(
        {
            "entries": [
                {
                    "claim_index": 0,
                    "source_kind": "news",
                    "body": "EPA data shows cars consume disproportionate urban land.",
                    "url": hit.result.url,
                    "confidence": 0.9,
                }
            ]
        }
    )
    client = _ScriptedClient([raw])
    entries = synthesise_knowledge(client, _brief(), [hit])
    assert len(entries) == 1
    assert client.calls[0][0]["content"] == KNOWLEDGE_SYSTEM_PROMPT
    assert client.options[0] == {"temperature": 0.2, "num_predict": 512}


def test_synthesise_knowledge_skips_llm_call_when_no_hits() -> None:
    client = _ScriptedClient([])  # no responses → would raise if called
    entries = synthesise_knowledge(client, _brief(), [])
    assert entries == []
    assert client.calls == []


def test_synthesise_knowledge_returns_empty_on_llm_error() -> None:
    entries = synthesise_knowledge(_BoomClient(), _brief(), [_hit()])
    assert entries == []


def test_synthesise_knowledge_returns_empty_on_garbage() -> None:
    client = _ScriptedClient(["not json at all"])
    entries = synthesise_knowledge(client, _brief(), [_hit()])
    assert entries == []


def test_synthesise_knowledge_passes_model_when_provided() -> None:
    captured: dict[str, Any] = {}

    class _Client:
        def stream_chat(
            self,
            messages: list[dict[str, Any]],
            *,
            options: dict[str, Any] | None = None,
            model: str | None = None,
        ) -> Iterator[str]:
            captured["model"] = model
            yield _wrap({"entries": []})

    synthesise_knowledge(_Client(), _brief(), [_hit()], model="gemma3:4b")
    assert captured["model"] == "gemma3:4b"


# --- persistence ------------------------------------------------------------


def test_persist_knowledge_writes_file(tmp_path: Path) -> None:
    entry = KnowledgeEntry(
        claim_index=0,
        source_kind="news",
        attribution="In nytimes.com",
        body="EPA data shows cars consume disproportionate urban land.",
        url="https://www.nytimes.com/x",
        confidence=0.9,
    )
    path = persist_knowledge(
        [entry],
        run_root=tmp_path,
        run_id="run-1",
        agent_id="offender",
    )
    assert path == tmp_path / "run-1" / "research" / "offender.knowledge.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert len(data) == 1
    assert data[0]["claim_index"] == 0
    assert data[0]["attribution"] == "In nytimes.com"


def test_persist_knowledge_writes_empty_list(tmp_path: Path) -> None:
    path = persist_knowledge([], run_root=tmp_path, run_id="run-2", agent_id="defender")
    assert json.loads(path.read_text(encoding="utf-8")) == []


def test_synthesise_knowledge_persists_when_run_root_supplied(tmp_path: Path) -> None:
    hit = _hit()
    raw = _wrap(
        {
            "entries": [
                {
                    "claim_index": 0,
                    "source_kind": "news",
                    "body": "EPA data shows cars consume disproportionate urban land.",
                    "url": hit.result.url,
                    "confidence": 0.9,
                }
            ]
        }
    )
    client = _ScriptedClient([raw])
    synthesise_knowledge(
        client,
        _brief(),
        [hit],
        run_root=tmp_path,
        run_id="run-3",
    )
    written = tmp_path / "run-3" / "research" / "offender.knowledge.json"
    assert written.exists()
    data = json.loads(written.read_text(encoding="utf-8"))
    assert len(data) == 1
