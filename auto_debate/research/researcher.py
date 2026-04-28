"""
research.py — Pre-debate web research (Phase 11).

Part of the Auto Debate project. See PROJECT.md and ROADMAP.md.

Before turn 1, each agent runs a small research routine that:

    1. Asks the LLM to plan 3-5 search queries for its role stance.
    2. Calls a :class:`SearchAdapter` for each query.
    3. Asks the LLM to summarise each result and tag it as
       supports / contradicts / irrelevant.
    4. Appends approved summaries (with URLs) to the agent's
       :class:`memory.AgentMemory.knowledge` tuple.

The orchestration is pure Python — the only LLM I/O happens through a
``stream_chat``-shaped client (same Protocol the engine uses). Tests
inject a deterministic fake; a live Ollama server is never required for
CI. The :class:`OfflineFixtureAdapter` likewise removes any network
dependency from the search step.

Hard caps (queries per agent, results per query, total wall-clock) are
enforced inside :class:`Researcher` so a runaway provider can't burn the
debate budget.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from collections.abc import Iterable, Iterator
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Final, Literal, Protocol

from auto_debate.memory import AgentId, AgentMemory, MemoryStore
from auto_debate.research.planner import (
    QueryPlan,
    plan_queries,
)
from auto_debate.research.stance import (
    StanceBrief,
    analyse_topic,
    render_stance_lines,
)

__all__ = [
    "DuckDuckGoAdapter",
    "OfflineFixtureAdapter",
    "ResearchAdapterError",
    "ResearchLimits",
    "Researcher",
    "SearchAdapter",
    "SearchResult",
]

_log = logging.getLogger(__name__)

_CACHE_TTL_SECONDS: Final[float] = 24 * 60 * 60.0
_DEFAULT_MAX_QUERIES: Final[int] = 5
_DEFAULT_MAX_RESULTS_PER_QUERY: Final[int] = 5
_DEFAULT_BUDGET_SECONDS: Final[float] = 60.0
_SUMMARY_WORD_CAP: Final[int] = 40

_VALID_TAGS: Final[frozenset[str]] = frozenset({"supports", "contradicts", "irrelevant"})


class ResearchAdapterError(RuntimeError):
    """Raised when a search adapter cannot satisfy a query."""


# --- search results ---------------------------------------------------------


@dataclass(frozen=True)
class SearchResult:
    """A single search hit. Adapters normalise to this shape."""

    title: str
    url: str
    snippet: str
    fetched_at: str  # ISO-8601 UTC

    def as_dict(self) -> dict[str, str]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SearchResult:
        return cls(
            title=str(data.get("title", "")).strip(),
            url=str(data.get("url", "")).strip(),
            snippet=str(data.get("snippet", "")).strip(),
            fetched_at=str(data.get("fetched_at", "")).strip(),
        )


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# --- adapters --------------------------------------------------------------


class SearchAdapter(Protocol):
    """Search transport. Implementations must be deterministic per ``query``."""

    name: str

    def search(self, query: str, *, max_results: int) -> list[SearchResult]: ...


@dataclass
class OfflineFixtureAdapter:
    """Returns canned results from an in-memory mapping. Used in CI + offline demo.

    The fixture maps a query string (case-insensitive, whitespace-collapsed)
    to a list of :class:`SearchResult`. Unknown queries return an empty list
    rather than raising — the planner is allowed to over-generate queries.
    """

    fixture: dict[str, list[SearchResult]] = field(default_factory=dict)
    name: str = "offline"

    def search(self, query: str, *, max_results: int) -> list[SearchResult]:
        if max_results <= 0:
            return []
        key = _normalize_query(query)
        results = self.fixture.get(key, [])
        return list(results[:max_results])


def _normalize_query(query: str) -> str:
    return re.sub(r"\s+", " ", query.strip().lower())


@dataclass
class DuckDuckGoAdapter:
    """Live DuckDuckGo adapter. Lazily imports ``duckduckgo_search`` on first use.

    Intentionally not a hard runtime dependency — installs that don't need
    web research can omit the package. Calling :meth:`search` without it
    raises :class:`ResearchAdapterError` with the install command.
    """

    name: str = "duckduckgo"
    region: str = "wt-wt"
    safesearch: str = "moderate"

    def search(self, query: str, *, max_results: int) -> list[SearchResult]:
        if max_results <= 0:
            return []
        try:
            from duckduckgo_search import DDGS
        except ImportError as exc:  # pragma: no cover - exercised only with live deps
            raise ResearchAdapterError(
                "duckduckgo-search is not installed. "
                "Install it with: pip install duckduckgo-search",
            ) from exc

        try:  # pragma: no cover - live network path, never hit by CI
            with DDGS() as ddgs:
                raw_hits: Iterable[dict[str, Any]] = ddgs.text(
                    query,
                    region=self.region,
                    safesearch=self.safesearch,
                    max_results=max_results,
                )
                fetched_at = _now_iso()
                return [
                    SearchResult(
                        title=str(hit.get("title", "")).strip(),
                        url=str(hit.get("href") or hit.get("url", "")).strip(),
                        snippet=str(hit.get("body") or hit.get("snippet", "")).strip(),
                        fetched_at=fetched_at,
                    )
                    for hit in raw_hits
                    if hit.get("href") or hit.get("url")
                ]
        except Exception as exc:  # pragma: no cover - network errors
            raise ResearchAdapterError(f"duckduckgo search failed: {exc}") from exc


# --- limits + LLM transport ------------------------------------------------


@dataclass(frozen=True)
class ResearchLimits:
    """Hard caps applied per agent during a research pass."""

    max_queries: int = _DEFAULT_MAX_QUERIES
    max_results_per_query: int = _DEFAULT_MAX_RESULTS_PER_QUERY
    wall_clock_budget_seconds: float = _DEFAULT_BUDGET_SECONDS

    def __post_init__(self) -> None:
        if self.max_queries <= 0:
            raise ValueError(f"max_queries must be > 0, got {self.max_queries!r}")
        if self.max_results_per_query <= 0:
            raise ValueError(
                f"max_results_per_query must be > 0, got {self.max_results_per_query!r}",
            )
        if self.wall_clock_budget_seconds <= 0:
            raise ValueError(
                f"wall_clock_budget_seconds must be > 0, got {self.wall_clock_budget_seconds!r}",
            )


class _LLMClient(Protocol):
    """Subset of :class:`engine.LLMClient` we need for query planning + summarising."""

    def stream_chat(
        self,
        messages: list[dict[str, Any]],
        *,
        options: dict[str, Any] | None = ...,
        model: str | None = ...,
    ) -> Iterator[str]: ...


_RoleStance = Literal["offender", "defender"]


_PLANNER_SYSTEM = (
    "You are a research assistant supporting a debate agent. Given a debate "
    "topic and the agent's role stance, produce 3-5 short web-search queries "
    "the agent could run to back up its side. Output STRICTLY a JSON array of "
    "strings. No prose, no commentary, no code fences."
)


def _planner_user_message(topic: str, role: _RoleStance) -> str:
    direction = "argues AGAINST the topic" if role == "offender" else "argues FOR the topic"
    return (
        f'Topic: "{topic}"\n'
        f"Role: the agent {direction}.\n"
        "Return 3-5 search queries as a JSON array of strings."
    )


_SUMMARY_SYSTEM = (
    "You summarise a single search result for a debate agent. Reply with a "
    "single JSON object on one line: "
    '{"summary": "<= 40 words neutral paraphrase", '
    '"tag": "supports" | "contradicts" | "irrelevant"}. '
    "No markdown, no code fences, no extra keys."
)


def _summary_user_message(
    topic: str,
    role: _RoleStance,
    result: SearchResult,
) -> str:
    direction = "AGAINST" if role == "offender" else "FOR"
    return (
        f'Topic: "{topic}"\n'
        f"Role stance: {direction} the topic.\n"
        f"Search result title: {result.title}\n"
        f"URL: {result.url}\n"
        f"Snippet: {result.snippet}\n"
        "Reply with the JSON object."
    )


# --- cache ------------------------------------------------------------------


@dataclass(frozen=True)
class _SearchCache:
    """SHA1-keyed JSON cache under ``runs/<run_id>/cache/search/``."""

    root: Path
    ttl_seconds: float = _CACHE_TTL_SECONDS

    def _path_for(self, query: str) -> Path:
        digest = hashlib.sha1(_normalize_query(query).encode("utf-8")).hexdigest()
        return self.root / f"{digest}.json"

    def load(self, query: str) -> list[SearchResult] | None:
        path = self._path_for(query)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        ts = float(payload.get("cached_at", 0))
        if ts <= 0 or (time.time() - ts) > self.ttl_seconds:
            return None
        items = payload.get("results", [])
        if not isinstance(items, list):
            return None
        return [SearchResult.from_dict(item) for item in items if isinstance(item, dict)]

    def save(self, query: str, results: list[SearchResult]) -> None:
        path = self._path_for(query)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "query": _normalize_query(query),
            "cached_at": time.time(),
            "results": [r.as_dict() for r in results],
        }
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


# --- helpers: parsing LLM output -------------------------------------------


_JSON_ARRAY_RE: Final[re.Pattern[str]] = re.compile(r"\[[\s\S]*?\]")
_JSON_OBJECT_RE: Final[re.Pattern[str]] = re.compile(r"\{[\s\S]*?\}")


def _consume_chat(client: _LLMClient, messages: list[dict[str, Any]]) -> str:
    return "".join(client.stream_chat(messages))


def _strip_code_fence(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"```\s*$", "", text)
    return text.strip()


def _parse_query_plan(raw: str, *, fallback_topic: str) -> list[str]:
    """Best-effort JSON-array parse. Falls back to ``[fallback_topic]``."""
    cleaned = _strip_code_fence(raw)
    candidates: list[str] = []
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        match = _JSON_ARRAY_RE.search(cleaned)
        if match is None:
            _log.warning("planner output was not JSON, falling back to topic")
            return [fallback_topic]
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            _log.warning("planner output JSON-array re-parse failed, falling back")
            return [fallback_topic]
    if not isinstance(data, list):
        return [fallback_topic]
    for item in data:
        if isinstance(item, str) and item.strip():
            candidates.append(item.strip())
    return candidates or [fallback_topic]


def _parse_summary(raw: str) -> tuple[str, str] | None:
    """Return ``(summary, tag)`` or ``None`` if the response is malformed."""
    cleaned = _strip_code_fence(raw)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        match = _JSON_OBJECT_RE.search(cleaned)
        if match is None:
            return None
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    if not isinstance(data, dict):
        return None
    summary = str(data.get("summary", "")).strip()
    tag = str(data.get("tag", "")).strip().lower()
    if not summary or tag not in _VALID_TAGS:
        return None
    words = summary.split()
    if len(words) > _SUMMARY_WORD_CAP:
        summary = " ".join(words[:_SUMMARY_WORD_CAP])
    return summary, tag


# --- researcher -------------------------------------------------------------


def _format_knowledge_entry(summary: str, tag: str, result: SearchResult) -> str:
    return f"[{tag}] {summary} (source: {result.url})"


@dataclass
class Researcher:
    """Drives the research pass for a single debate run.

    The :class:`Researcher` is intentionally stateless beyond construction:
    each call to :meth:`populate_for_agent` is a self-contained pass that
    reads from / writes to the underlying :class:`MemoryStore` and the
    on-disk search cache. The same instance can be reused across two
    agents in one debate.
    """

    llm_client: _LLMClient
    adapter: SearchAdapter
    memory_store: MemoryStore
    run_id: str
    limits: ResearchLimits = field(default_factory=ResearchLimits)
    stance_enabled: bool = False
    model: str | None = None

    # --- public API ----------------------------------------------------

    def populate_for_agent(
        self,
        agent_id: AgentId,
        *,
        topic: str,
        progress_callback: Any = None,
    ) -> AgentMemory:
        """Run the planner + fetch + summarise loop for ``agent_id``.

        Loads (or creates) the agent's memory, appends de-duplicated
        knowledge entries, and persists the result. Returns the updated
        :class:`AgentMemory`. Errors from a single search/summary do
        not abort the whole pass — they are logged and skipped.
        """
        deadline = time.monotonic() + self.limits.wall_clock_budget_seconds
        memory = self.memory_store.load(self.run_id, agent_id)
        existing = set(memory.knowledge)

        # Phase 18: optional stance brief is computed first so future
        # phases can condition planner / filter / synthesis on it.
        # Until those phases land, the brief is rendered into the
        # memory's `## Stance` section so the speaking prompt still
        # benefits from a structured topic reading.
        stance_lines: tuple[str, ...] = memory.stance
        brief: StanceBrief | None = None
        plan: QueryPlan | None = None
        if self.stance_enabled:
            brief = analyse_topic(
                self.llm_client,
                topic,
                agent_id,
                model=self.model,
            )
            if brief is not None:
                stance_lines = render_stance_lines(brief)
                _log.info(
                    "stance brief produced for agent=%s (%d claims, %d counterclaims)",
                    agent_id,
                    len(brief.key_claims),
                    len(brief.expected_counterclaims),
                )
                # Phase 19: stance-driven query planner. Persisted to
                # ``runs/<run_id>/research/<agent>.plan.json`` for audit.
                plan = plan_queries(
                    self.llm_client,
                    brief,
                    model=self.model,
                    run_root=self.memory_store.root,
                    run_id=self.run_id,
                )
                _log.info(
                    "query plan produced for agent=%s (%d queries)",
                    agent_id,
                    len(plan.queries),
                )

        queries = list(plan.texts()) if plan is not None else self._plan_queries(topic, agent_id)
        queries = queries[: self.limits.max_queries]
        new_entries: list[str] = []

        for query_idx, query in enumerate(queries, start=1):
            if time.monotonic() >= deadline:
                _log.warning(
                    "research budget exhausted before query %d for agent=%s",
                    query_idx,
                    agent_id,
                )
                break
            if progress_callback is not None:
                try:
                    progress_callback(agent_id, query_idx, len(queries), query)
                except Exception:
                    _log.exception("progress_callback raised; ignoring")
            results = self._search_with_cache(query)
            results = results[: self.limits.max_results_per_query]
            for result in results:
                if time.monotonic() >= deadline:
                    break
                summary = self._summarise(topic, agent_id, result)
                if summary is None:
                    continue
                entry = _format_knowledge_entry(summary[0], summary[1], result)
                if entry in existing:
                    continue
                existing.add(entry)
                new_entries.append(entry)

        if new_entries or stance_lines != memory.stance:
            updated = AgentMemory(
                agent_id=memory.agent_id,
                knowledge=tuple(memory.knowledge) + tuple(new_entries),
                observations=memory.observations,
                strategy=memory.strategy,
                stance=stance_lines,
                turn_index=memory.turn_index,
            )
            self.memory_store.save(self.run_id, updated)
            _log.info(
                "research populated %d new knowledge entries for agent=%s",
                len(new_entries),
                agent_id,
            )
            return updated
        return memory

    # --- internals -----------------------------------------------------

    def _plan_queries(self, topic: str, agent_id: AgentId) -> list[str]:
        messages = [
            {"role": "system", "content": _PLANNER_SYSTEM},
            {"role": "user", "content": _planner_user_message(topic, agent_id)},
        ]
        try:
            raw = _consume_chat(self.llm_client, messages)
        except Exception:
            _log.exception("query planner LLM call failed; falling back to topic")
            return [topic]
        return _parse_query_plan(raw, fallback_topic=topic)

    def _search_with_cache(self, query: str) -> list[SearchResult]:
        cache = _SearchCache(root=self._cache_root())
        cached = cache.load(query)
        if cached is not None:
            _log.debug("search cache hit for %r", query)
            return cached
        try:
            results = self.adapter.search(
                query,
                max_results=self.limits.max_results_per_query,
            )
        except ResearchAdapterError:
            _log.exception("adapter %s failed for query %r", self.adapter.name, query)
            return []
        cache.save(query, results)
        return results

    def _summarise(
        self,
        topic: str,
        agent_id: AgentId,
        result: SearchResult,
    ) -> tuple[str, str] | None:
        messages = [
            {"role": "system", "content": _SUMMARY_SYSTEM},
            {"role": "user", "content": _summary_user_message(topic, agent_id, result)},
        ]
        try:
            raw = _consume_chat(self.llm_client, messages)
        except Exception:
            _log.exception("summary LLM call failed for %s", result.url)
            return None
        parsed = _parse_summary(raw)
        if parsed is None:
            _log.warning("malformed summary for %s; skipping", result.url)
            return None
        if parsed[1] == "irrelevant":
            return None
        return parsed

    def _cache_root(self) -> Path:
        return self.memory_store.root / self.run_id / "cache" / "search"
