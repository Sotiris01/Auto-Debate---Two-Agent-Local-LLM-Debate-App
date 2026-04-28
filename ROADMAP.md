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
| 16 | Repository layout refactor | `auto_debate/` package, v0.3 TODO stubs, no behaviour change | 223 | ✅ || 17 | Agentic-research literature review | `docs/research/agentic_research.md` design doc + Mermaid pipeline diagram + risk register | 223 | ✅ |
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
| 16 | Repository layout | groundwork | all later — ✅ shipped |
| 17 | Agentic-research literature review | research | 18-21 — ✅ shipped |
| 18 | Topic analysis & per-agent stance | implementation | 19 |
| 19 | Stance-driven query planner | implementation | 20 |
| 20 | Per-result favourability filter | implementation | 21 |
| 21 | Structured, attributed Knowledge synthesis | implementation | — |
| 22 | Run metadata & transcript auto-save | polish | — |

---

### Phase 16 — Repository Layout Refactor _(✅ shipped)_

**Outcome:** All loose root modules now live under the `auto_debate/`
package; only `app.py` (the Streamlit entry point) remains at the
project root. Phase-11 research is split into a sub-package that
re-exports the public surface and ships TODO-only stubs for Phases
18-21. CI: ruff + ruff format + mypy strict (19 files) + pytest **223
/ 223** all green; no new third-party deps.

> **Layout note:** The shipped layout keeps `memory.py`,
> `reflection.py`, `quality.py`, and `judge.py` as flat modules under
> `auto_debate/` rather than promoting each to its own sub-package as
> originally sketched. The sub-package treatment is reserved for
> `auto_debate/research/`, which is the only area v0.3 actively
> expands. This is a deliberate scope reduction to avoid churn on
> stable modules.

| Item | Status |
|---|---|
| Move modules via `git mv` (history preserved) | ✅ |
| Re-export shim (`auto_debate.research`) | ✅ |
| Update imports across `app.py`, `tests/`, `scripts/` | ✅ |
| `pyproject.toml` mypy `files = ["auto_debate"]` | ✅ |
| TODO stubs `stance.py` / `planner.py` / `filter.py` / `knowledge.py` | ✅ |
| README layout table refreshed | ✅ |
| `runs/` added to `.gitignore` | ✅ (incidental) |

---

### Phase 17 — Agentic-Research Literature Review _(✅ shipped)_

**Outcome:** [docs/research/agentic_research.md](docs/research/agentic_research.md) committed and linked from the README. Eight sources surveyed (six adopted, two deliberately rejected — iterative-deepening and LangGraph-as-a-dep). The decision log pins the prompt shape, strict JSON output schema, failure mode, and hard cap for each of the four pipeline stages (stance / plan / filter / synthesise). Mermaid pipeline diagram + per-agent LLM-call budget (≤ 28 calls) + top-5 risk register all in one doc. No production code changes shipped this phase.

| Item | Status |
|---|---|
| `docs/research/agentic_research.md` committed | ✅ |
| README links to the design doc | ✅ |
| ≥ 6 sources cited with one-line takeaways | ✅ (8 sources) |
| Decision log: prompt shape + JSON schema for all 4 stages | ✅ (§2.1-2.4) |
| Mermaid pipeline diagram | ✅ (§3) |
| Risk register (top 5) with mitigations | ✅ (§4) |
| Phases 18-21 reference the §-numbers fixed here | ✅ (forward-refs added below) |

> **Key decisions binding Phases 18-21:**
> 1. Pipeline is a fixed four-stage DAG: `stance → plan → filter → synthesise`. No agent-to-agent chat during research; no iterative deepening; no tool use beyond `SearchAdapter`.
> 2. Every stage is exactly one LLM call (filter is one-call-per-hit). Total per-agent worst case: `3 + N` calls where `N ≤ max_queries × max_results_per_query`.
> 3. Strict JSON output gated by stage-specific delimiters (`<STANCE>`, `<PLAN>`, `<FILTER>`, `<KNOWLEDGE>`); parser failures degrade gracefully (drop / fallback) — never crash the debate.
> 4. Citation hallucination defence is layered: fixed attribution templates per `source_kind` (LLM never names outlets) + Phase-21 deterministic citation linter.

---

### Phase 18 — Topic Analysis & Per-Agent Stance _(planned)_

**Goal:** Before any search runs, each agent reads the topic through a
short LLM pass that emits a **structured stance brief**: what the agent
is being asked to defend, what its core claims are, and what counter-
claims to expect. This is the input every later research stage consumes.
Directly fixes the topic-mismatch root cause from §1 of the post-mortem.

> **Design contract:** [docs/research/agentic_research.md §2.1](docs/research/agentic_research.md) fixes the prompt shape, strict JSON schema, failure mode, and hard caps for this stage. Implementation MUST match §2.1 verbatim or update the doc first.

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

> **Design contract:** [docs/research/agentic_research.md §2.2](docs/research/agentic_research.md) fixes the planner prompt, `<PLAN>` JSON schema, the Jaccard-≥0.6 diversity rule, and the 3-query fallback (topic / thesis / entity+thesis).

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

> **Design contract:** [docs/research/agentic_research.md §2.3](docs/research/agentic_research.md) fixes the `<RESULT>`-delimiter injection guard, the keep-requires-`supports_claim` rule, `temperature=0.0` gating, and the deterministic source-kind URL heuristic.

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

> **Design contract:** [docs/research/agentic_research.md §2.4](docs/research/agentic_research.md) fixes the `<KNOWLEDGE>` JSON schema, the fixed attribution templates per `source_kind` (LLM never invents outlet names), and the deterministic citation linter that rejects any quoted phrase absent from the source snippet (§4 risk #1).

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
