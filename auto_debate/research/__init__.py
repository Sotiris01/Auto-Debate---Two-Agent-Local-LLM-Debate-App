"""Research subpackage.

Houses the pre-debate web-research pipeline.

In Phase 16 this package contains a single module, :mod:`researcher`,
which is the verbatim Phase-11 implementation moved from the old
top-level ``research.py``. The remaining modules in this package
(:mod:`stance`, :mod:`planner`, :mod:`filter`, :mod:`knowledge`) are
deliberate TODO stubs that will be implemented in the v0.3 track:

* ``stance``    — Phase 18, per-agent topic stance briefs.
* ``planner``   — Phase 19, stance-driven query planner.
* ``filter``    — Phase 20, per-result favourability filter.
* ``knowledge`` — Phase 21, attributed Knowledge synthesis.

The package re-exports the public Phase-11 surface so existing call
sites only need to update the dotted import path::

    from auto_debate.research import (
        DuckDuckGoAdapter,
        OfflineFixtureAdapter,
        ResearchAdapterError,
        ResearchLimits,
        Researcher,
        SearchAdapter,
        SearchResult,
    )
"""

from __future__ import annotations

from auto_debate.research.filter import (
    FILTER_SYSTEM_PROMPT,
    FilteredHit,
    classify_source_kind,
    filter_result,
    persist_filter_outcomes,
)
from auto_debate.research.knowledge import (
    FALLBACK_KNOWLEDGE_LINE,
    KNOWLEDGE_SYSTEM_PROMPT,
    KnowledgeEntry,
    citation_lint,
    format_knowledge_entry,
    persist_knowledge,
    render_knowledge_lines,
    synthesise_knowledge,
)
from auto_debate.research.planner import (
    PLANNER_SYSTEM_PROMPT,
    PlannedQuery,
    QueryPlan,
    plan_queries,
)
from auto_debate.research.researcher import (
    DuckDuckGoAdapter,
    OfflineFixtureAdapter,
    ResearchAdapterError,
    Researcher,
    ResearchLimits,
    SearchAdapter,
    SearchResult,
)
from auto_debate.research.stance import (
    STANCE_SYSTEM_PROMPT,
    StanceBrief,
    analyse_topic,
    render_stance_lines,
)

__all__ = [
    "FALLBACK_KNOWLEDGE_LINE",
    "FILTER_SYSTEM_PROMPT",
    "KNOWLEDGE_SYSTEM_PROMPT",
    "PLANNER_SYSTEM_PROMPT",
    "STANCE_SYSTEM_PROMPT",
    "DuckDuckGoAdapter",
    "FilteredHit",
    "KnowledgeEntry",
    "OfflineFixtureAdapter",
    "PlannedQuery",
    "QueryPlan",
    "ResearchAdapterError",
    "ResearchLimits",
    "Researcher",
    "SearchAdapter",
    "SearchResult",
    "StanceBrief",
    "analyse_topic",
    "citation_lint",
    "classify_source_kind",
    "filter_result",
    "format_knowledge_entry",
    "persist_filter_outcomes",
    "persist_knowledge",
    "plan_queries",
    "render_knowledge_lines",
    "render_stance_lines",
    "synthesise_knowledge",
]
