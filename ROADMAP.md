# Auto Debate — Implementation Roadmap

This roadmap tracks every development phase of the project. Completed phases
are summarised in the table below; full step-by-step notes live in git history.

> Convention: `[script]` = runs from a terminal · `[file]` = created/edited ·
> `[manual]` = one-time human action.

---

## Shipped History

> Full notes for every phase are preserved in git history.
> Tag `v0.1.0` was cut on commit `bf30a8a` after Phase 8.

| Phase | Name | Key deliverable | Tests | Status |
|---|---|---|---|---|
| 0 | Environment bootstrap | `check_system.py`, `check_ollama.py`, bootstrap scripts | — | ✅ |
| 1 | Scaffolding | Empty modules wired and importable | — | ✅ |
| 2 | Configuration layer | `Settings` frozen dataclass + `load_settings()` | 16 | ✅ |
| 3 | Prompt layer | `build_system_prompt` + role templates | 19 | ✅ |
| 4 | LLM layer | `OllamaClient`, `stream_chat`, `ModelNotFoundError` | 17 | ✅ |
| 5 | Debate engine | `DebateEngine`, `run_one_turn`, `transcript()` | 13 | ✅ |
| 6 | Streamlit UI | Chat bubbles, streaming cursor, Stop / Clear | — | ✅ |
| 7 | Hardening & QA | Logging, ruff / mypy, `bench.py`, CI script | — | ✅ |
| 8 | Docs & release | README, in-app help, transcript download | — | ✅ **tag v0.1.0** |
| 9 | Composable prompts | `prompts/` package, `PromptComposer`, fragment registry | 20 | ✅ |
| 10 | Per-agent memory | `AgentMemory`, `MemoryStore`, memory expanders in UI | 18 | ✅ |
| 11 | Pre-debate research | `Researcher`, `DuckDuckGoAdapter`, SHA1 search cache | 22 | ✅ |
| 12 | Pre-turn reflection | `Reflector`, `apply_update`, closing-round behavior | 18 | ✅ |
| 13 | Quality guards | n-gram novelty, TF-IDF adherence, loop detection, UI chips | 23 | ✅ |
| 14 | Persona & behavior library | 6 personas · 6 behaviors · 4 presets · compatibility check | 28 | ✅ |
| 15 | Judge / evaluator agent | `judge.py`, 9-dim scorecard, `report.{json,md}` persistence | 26 | ✅ |

**CI baseline:** 223 / 223 tests passing · mypy strict on 13 source files.

---

## Cross-Phase Conventions

- **Branch per phase:** `phase/N-name`, merged to `main` when exit criteria pass.
- **Commit prefix:** `[PN]` (e.g. `[P15]`).
- **No phase skipping.** A failing phase blocks the next.
- **Tests ship with behavior.** Every new module arrives with at least one test file.
- **Feature flags.** New opt-in capabilities are gated via `Settings` until a minor version ships.

---

## Upcoming — v0.3 Track ("Deep research & structured knowledge")

> Phase 15 is complete. The v0.3 track is driven by the post-mortem in
> [runs/20260428T110241Z/analysis.md](runs/20260428T110241Z/analysis.md):
> the topic-vs-query mismatch, the empty offender Knowledge section, the
> off-topic summaries, and the lack of source attribution all point at
> the same root cause — **the research stage is too thin**. Each agent
> needs to (a) decide what its own thesis is, (b) plan queries against
> *that* thesis, (c) keep only material that supports it, and
> (d) synthesise a structured, attributed Knowledge section.
>
> The original Phase 16 (run metadata + transcript auto-save) is
> deferred to **Phase 22** — it is independent plumbing and should not
> block the research rework.
>
> Phases are sequenced **groundwork → research → design → implement →
> polish**. Each ships behind a feature flag; defaults stay at v0.2.0
> behaviour until the track tags v0.3.0.

| # | Theme | Kind | Blocks |
|---|---|---|---|
| 16 | Repository layout | groundwork | all later |
| 17 | Agentic-research literature review | research | 18-21 |
| 18 | Topic analysis & per-agent stance | implementation | 19 |
| 19 | Stance-driven query planner | implementation | 20 |
| 20 | Per-result favourability filter | implementation | 21 |
| 21 | Structured, attributed Knowledge synthesis | implementation | — |
| 22 | Run metadata & transcript auto-save | polish | — |

---

### Phase 16 — Repository Layout Refactor _(planned)_

**Goal:** Move from "10 loose `.py` files at the project root" to a
proper package layout, *without* changing any behaviour. Lays the
groundwork for v0.3 modules that would otherwise pile more files on top
of an already-flat root. **No new logic, no new tests** — only moves,
re-exports, and TODO stubs for the v0.3 packages.

**Current root** (10 modules): `app.py`, `config.py`, `engine.py`,
`judge.py`, `llm.py`, `memory.py`, `quality.py`, `reflection.py`,
`research.py`, plus the `prompts/` package.

**Planned target layout**

```
auto_debate/
├── app.py                    # entry point only
├── auto_debate/              # new top-level package
│   ├── __init__.py
│   ├── config.py
│   ├── engine.py
│   ├── llm.py
│   ├── prompts/              # moved as-is
│   ├── memory/
│   │   └── store.py          # ex memory.py
│   ├── reflection/
│   │   └── reflector.py      # ex reflection.py
│   ├── quality/
│   │   └── metrics.py        # ex quality.py
│   ├── judge/
│   │   └── evaluator.py      # ex judge.py
│   └── research/             # ex research.py, split for v0.3
│       ├── __init__.py
│       ├── adapters.py       # SearchAdapter, DuckDuckGo, Offline
│       ├── cache.py          # _SearchCache
│       ├── researcher.py     # Researcher orchestrator
│       ├── stance.py         # TODO stub — Phase 18
│       ├── planner.py        # TODO stub — Phase 19
│       ├── filter.py         # TODO stub — Phase 20
│       └── knowledge.py      # TODO stub — Phase 21
└── tests/                    # mirror layout under tests/
```

**Planned deliverables**

| Item | Detail |
|---|---|
| Move modules | `git mv` each root `.py` into the new package; preserve history. |
| Re-export shim | Keep `from research import Researcher` etc. working via `auto_debate/__init__.py` to avoid breaking external scripts and `tests/`. |
| Update imports | `app.py` and `tests/*` imports adjusted to the new paths in one mechanical sweep. |
| Pyproject | Add `[tool.setuptools.packages.find]` (or equivalent) so `pip install -e .` keeps working. mypy `files` list updated. |
| New empty modules | `stance.py`, `planner.py`, `filter.py`, `knowledge.py` ship with module docstring + `# TODO: Phase N` markers only. |
| README & PROJECT.md | One-line note pointing at the new layout. |

**Phase 16 Exit Criteria**
- [ ] No `.py` source modules remain at the project root other than `app.py`.
- [ ] CI green: ruff + ruff format + mypy strict + **all 223 existing tests pass unchanged**.
- [ ] `git log --follow` on each moved file shows continuous history.
- [ ] No new third-party deps added.

---

### Phase 17 — Agentic-Research Literature Review _(planned, no code)_

**Goal:** Before changing the research pipeline, do an explicit
literature pass on how comparable systems do "agent reads topic →
plans queries → curates results → writes a sourced brief". Output is a
**design doc** that pins decisions for Phases 18-21; no production code
changes ship in this phase.

**Sources to survey** (non-exhaustive starting list)

| Source | What we want from it |
|---|---|
| AutoGen / Magentic-One | Multi-agent search loops, query refinement patterns |
| LangGraph & `Adu-2115/Debate-DAG-LangGraph` | Branching research → debate DAG topology |
| `aliasad059/RedDebate` | Long-term memory + per-stance search |
| Stanford STORM (`assafelovic/gpt-researcher`) | Outline → per-section search → cited synthesis |
| Perplexity / You.com architecture posts | Citation-first answer construction |
| OpenAI "Deep Research" blog + leaks | Iterative-deepening query plans |
| ReAct / Toolformer / Self-Ask papers | Decompose-question-then-search prompting |
| RAG-Fusion / HyDE / Query2Doc | Query expansion / rewriting techniques |

**Planned deliverables**

| Item | Detail |
|---|---|
| `docs/research/agentic_research.md` | 1-2 page synthesis: prior-art summary, what we are stealing, what we are *not* doing. |
| Decision log | For each of the four pipeline stages (stance, plan, filter, synthesise), pin: prompt shape, output schema, failure mode, hard cap. |
| Diagrams | Mermaid flowchart of the v0.3 research pipeline; placed in `docs/research/`. |
| Risk register | Top 5 things that can go wrong (e.g. hallucinated citations, cycle-of-search, prompt-injection from result snippets) with mitigations. |

**Phase 17 Exit Criteria**
- [ ] `docs/research/agentic_research.md` committed and linked from README.
- [ ] At least 6 of the sources above cited with one-line takeaways.
- [ ] Decision log answers: "what is the *exact* prompt shape and JSON schema for each of the four pipeline stages?"
- [ ] Phases 18-21 below are updated to reference the decisions made here.

---

### Phase 18 — Topic Analysis & Per-Agent Stance _(planned)_

**Goal:** Before any search runs, each agent reads the topic through a
short LLM pass that emits a **structured stance brief**: what the agent
is being asked to defend, what its core claims are, and what counter-
claims to expect. This is the input every later research stage consumes.
Directly fixes the topic-mismatch root cause from §1 of the post-mortem.

**Planned deliverables**

| Item | Detail |
|---|---|
| `auto_debate/research/stance.py` | New `StanceBrief` frozen dataclass: `topic`, `agent_id`, `position` ("for"/"against"), `thesis` (≤ 30 words), `key_claims` (3-5 short strings), `expected_counterclaims` (3-5 strings), `entities` (named nouns/orgs to anchor searches). |
| `STANCE_SYSTEM_PROMPT` | Strict-JSON system prompt; agent role + topic in; `<STANCE>{...}</STANCE>` block out. Hard cap on field lengths. |
| `analyse_topic(client, topic, agent_id) -> StanceBrief \| None` | One LLM call, ~200 tokens, `temperature=0.2`. Returns `None` on parse failure (no crash). |
| Engine wiring | `Researcher.populate_for_agent` calls `analyse_topic` first; brief is stored on memory's new `stance` slot **and** rendered into `<MEMORY>` so the speaking prompt sees the same thesis. |
| UI surface | Memory expander gains a "Stance brief" section above Knowledge. |
| Tests | Parser happy-path / malformed JSON / over-cap fields, end-to-end with offline fixture, `analyse_topic` failure is non-fatal. |

**Phase 18 Exit Criteria**
- [ ] On any debate run, both agents' memory files contain a `## Stance` section listing thesis + 3-5 key claims tied to the *actual* topic.
- [ ] When the topic is ambiguous (e.g. the post-mortem's "Monster ... Red Bull"), each agent commits to one reading and the rest of the pipeline uses *that* reading.
- [ ] Feature flag `stance_analysis_enabled`, default `True` once Phase 19 lands; Phase 18 alone keeps it off-by-default.

---

### Phase 19 — Stance-Driven Query Planner _(planned)_

**Goal:** Replace the current "agent + topic-string → 3-5 queries"
planner with a stance-aware version that produces queries grounded in
the `StanceBrief` from Phase 18. Targets the offender-empty asymmetry
in Issue B of the post-mortem.

**Planned deliverables**

| Item | Detail |
|---|---|
| `auto_debate/research/planner.py` | New `QueryPlan` dataclass: `agent_id`, `queries: tuple[PlannedQuery, ...]`. `PlannedQuery` carries `text`, `target_claim` (back-reference to a key_claim), `expected_source_kinds` (e.g. `["paper", "news", "forum"]`). |
| `plan_queries(client, brief) -> QueryPlan` | One LLM call producing 5-8 queries; each query must reference at least one `key_claim` index. JSON-strict, `<PLAN>{...}</PLAN>`. |
| Diversity rule | Planner prompt forbids near-duplicate queries (cosine-similarity check rejects > 0.9). |
| Fallbacks | If the planner returns < 3 valid queries, append topic-as-query and the agent's thesis-as-query so the pipeline never starves. |
| Persistence | Plan is saved to `runs/<run_id>/research/<agent>.plan.json` for later inspection. |
| Tests | Schema validation, claim-reference enforcement, fallback path, dedup, persistence round-trip. |

**Phase 19 Exit Criteria**
- [ ] Each agent enters the search stage with ≥ 3 distinct queries that reference at least one of its own `key_claims`.
- [ ] No query in the plan is a near-duplicate of another (by token-set Jaccard).
- [ ] `runs/<run_id>/research/<agent>.plan.json` exists after every research pass.

---

### Phase 20 — Per-Result Favourability Filter _(planned)_

**Goal:** After each search returns hits, the agent **keeps only what
supports its stance** and tags everything else for discard. Replaces
the current 3-tag (`supports`/`contradicts`/`irrelevant`) summariser
with a stance-aware filter that defaults to discard when uncertain.
Targets Issue C in the post-mortem (off-topic zhihu hits being kept).

**Planned deliverables**

| Item | Detail |
|---|---|
| `auto_debate/research/filter.py` | New `FilteredHit` dataclass: `result: SearchResult`, `verdict: Literal["keep","drop"]`, `reason: str`, `supports_claim: int \| None` (back-ref to key_claim index), `confidence: float`. |
| `filter_result(client, brief, query, result) -> FilteredHit` | One LLM call per hit; strict JSON. `keep` requires (a) the snippet directly mentions an entity from the brief AND (b) the model can name which claim it supports. |
| Anti-injection guard | The result snippet is rendered inside a clearly-delimited `<RESULT>` block in the prompt; the filter is told to ignore any instructions inside it. |
| Source-kind classifier | Cheap heuristic on the URL → `{paper, news, forum, wiki, blog, other}`; persisted on the `FilteredHit`. |
| Persistence | Per-agent `runs/<run_id>/research/<agent>.hits.json` records every kept hit + reason; dropped hits go to `<agent>.drops.json` for audit. |
| Tests | Off-topic snippet → `drop`, on-topic snippet → `keep`, prompt-injection attempt is logged and dropped, source-kind heuristic, persistence. |

**Phase 20 Exit Criteria**
- [ ] On the post-mortem topic, the zhihu "consumer vs customer" snippets are reproducibly classified `drop` (regression test).
- [ ] Every kept hit has a non-`None` `supports_claim` referencing a brief from Phase 18.
- [ ] No prompt injection in a snippet alters the agent's stance (covered by an injection-corpus test).

---

### Phase 21 — Structured, Attributed Knowledge Synthesis _(planned)_

**Goal:** Take the curated `FilteredHit`s from Phase 20 and synthesise
the agent's `## Knowledge` section as **attributed, source-typed
bullets**. Each bullet renders with a natural-language attribution
prefix the speaking agent can quote verbatim — "On Reddit, …",
"According to *Nature* (2024), …", "In the *Wall Street Journal*, …".

**Planned deliverables**

| Item | Detail |
|---|---|
| `auto_debate/research/knowledge.py` | `KnowledgeEntry` dataclass: `claim_index`, `source_kind`, `attribution` (the rendered prefix), `body` (≤ 30-word paraphrase), `url`, `confidence`. |
| Attribution templates | Per source-kind: paper → `According to {authors_or_outlet} ({year})`; news → `In {outlet}`; forum → `On {site} ({thread_or_subreddit})`; wiki → `Per {site}`; blog → `On {outlet}`; other → `From {domain}`. |
| `synthesise_knowledge(client, brief, kept_hits) -> tuple[KnowledgeEntry, ...]` | One LLM call to deduplicate near-identical claims, group by `claim_index`, and compose the prefix; output is strict JSON. Hard cap of N entries per claim (default 2). |
| Memory rendering | `MemoryStore` Knowledge section now renders `- {attribution}, {body} ({url})` with section sub-headers per `claim_index` so the agent's speak prompt can cite by claim. |
| Citation linter | Lint pass rejects an entry whose `body` quotes a claim that does **not** appear in the source `result.snippet` (mitigates hallucinated citations). |
| Tests | Attribution rendering per source-kind, dedup, citation-lint catches a fabricated quote, memory-block round-trip. |

**Phase 21 Exit Criteria**
- [ ] Re-running the post-mortem topic with v0.3 produces a Knowledge section where every line begins with one of the attribution prefixes above.
- [ ] No `KnowledgeEntry.body` contains a quoted phrase absent from the cached search snippet (citation linter passes).
- [ ] The judge's **Q6 Factual grounding** score on a sanity-check topic improves from 2/5 → ≥ 3/5 on the same model (`gemma3:4b`).
- [ ] **v0.3.0 tag cut** when 16-21 are all green.

---

### Phase 22 — Run Metadata & Transcript Auto-save _(deferred from old Phase 16)_

**Goal:** Every run produces a complete, self-contained record without
any manual download step. Independent of the research rework above.

**Planned deliverables**

| Item | Detail |
|---|---|
| Auto-save transcript | Write `runs/<run_id>/auto_debate_transcript.md` at the end of `_run_debate` when memory is enabled. |
| `run.json` | Persist settings snapshot + `started_at`, `finished_at`, per-phase wall-clock seconds, per-turn seconds. |
| Per-turn timing | Instrument `engine.run_one_turn` with `time.perf_counter` bookends; store on the message dict alongside `metrics`. |
| Research summary | Expose `<query> → N hits → M kept` per agent in `run.json` and in a collapsible UI panel (now consumes Phase 19/20 artefacts). |
| Zero-knowledge warning | Promote the "research populated 0 entries" log to `WARNING`; surface it as `st.warning`. |

**Phase 22 Exit Criteria**
- [ ] `runs/<run_id>/auto_debate_transcript.md` exists after every completed debate when memory is enabled.
- [ ] `runs/<run_id>/run.json` contains at minimum: `topic`, `started_at`, `finished_at`, `total_seconds`, `settings`, `per_turn_seconds`, `research_summary`.
- [ ] CI green (ruff + mypy + pytest).
