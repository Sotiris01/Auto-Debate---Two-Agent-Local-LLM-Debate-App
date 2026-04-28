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
| 16 | Repository layout refactor | `auto_debate/` package, v0.3 TODO stubs, no behaviour change | 223 | ✅ |
| 17 | Agentic-research literature review | `docs/research/agentic_research.md` design doc + Mermaid pipeline diagram + risk register | 223 | ✅ |
| 18 | Topic analysis & per-agent stance | `StanceBrief` + `analyse_topic` + `AgentMemory.stance` + `<MEMORY>` rendering | 242 | ✅ |
| 19 | Stance-driven query planner | `QueryPlan` + `plan_queries` + Jaccard dedup + `runs/.../<agent>.plan.json` | 261 | ✅ |
| 20 | Per-result favourability filter | `FilteredHit` + `filter_result` + URL source-kind heuristic + `runs/.../<agent>.{hits,drops}.json` | 297 | ✅ |
| 21 | Structured, attributed Knowledge synthesis | `KnowledgeEntry` + `synthesise_knowledge` + citation linter + per-source-kind attribution + `runs/.../<agent>.knowledge.json` | 333 | ✅ |
| 22 | Run metadata & transcript auto-save | `RunMetadata` + `ResearchSummary` + per-turn timing + `runs/.../auto_debate_transcript.md` + `runs/.../run.json` | 353 | ✅ |
**CI baseline:** 353 / 353 tests passing · mypy strict on 20 source files.

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
| 18 | Topic analysis & per-agent stance | implementation | 19 — ✅ shipped |
| 19 | Stance-driven query planner | implementation | 20 — ✅ shipped |
| 20 | Per-result favourability filter | implementation | 21 — ✅ shipped |
| 21 | Structured, attributed Knowledge synthesis | implementation | — ✅ shipped |
| 22 | Run metadata & transcript auto-save | polish | — ✅ shipped |

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

### Phase 18 — Topic Analysis & Per-Agent Stance _(✅ shipped)_

**Outcome:** Each agent now reads the topic through one short LLM pass before any search runs. The pass produces a structured `StanceBrief` (thesis ≤ 30 words + 3-5 `key_claims` + 3-5 `expected_counterclaims` + 3-8 `entities`), persisted to memory's new `## Stance` section and rendered first in the `<MEMORY>` prompt block so the speaking prompt always sees the agent's own thesis. The stage is one LLM call (`temperature=0.2`, `num_predict=256`), gated by a `<STANCE>{...}</STANCE>` strict-JSON delimiter; parser/validation failures degrade gracefully (the legacy Phase-11 path still runs). Feature flag `stance_analysis_enabled` defaults `False` (off-by-default per the original exit criteria — Phase 19 will flip the default once stance-driven planning lands). CI: ruff + ruff format + mypy strict (19 files) + pytest **242 / 242** all green; no new third-party deps.

| Item | Status |
|---|---|
| `auto_debate/research/stance.py` — `StanceBrief` + `STANCE_SYSTEM_PROMPT` + `analyse_topic` + `render_stance_lines` | ✅ |
| `AgentMemory.stance` field + `## Stance` markdown round-trip + `<MEMORY>` rendering (stance first) | ✅ |
| `Settings.stance_analysis_enabled` flag (env `STANCE_ANALYSIS_ENABLED`, default `False`) | ✅ |
| `Researcher` wires the flag and calls `analyse_topic` before `_plan_queries`; failures non-fatal | ✅ |
| Sidebar toggle (gated on memory + web-research) and "Stance" section in the memory expander | ✅ |
| Tests (`tests/test_stance.py` ×17 + 2 new in `test_config.py`) | ✅ |
| Design contract `docs/research/agentic_research.md` §2.1 honoured verbatim | ✅ |

---

### Phase 19 — Stance-Driven Query Planner _(✅ shipped)_

**Outcome:** When `stance_analysis_enabled` is on and a `StanceBrief` was produced, the legacy topic-string planner is bypassed in favour of `plan_queries(client, brief)`. The new planner is one LLM call (`temperature=0.3`, `num_predict=384`) gated by `<PLAN>{...}</PLAN>` strict-JSON; every query references at least one `key_claim` index and contains at least one entity from the brief; near-duplicate queries are dropped deterministically by token-set Jaccard ≥ 0.6. When fewer than 3 queries survive validation, a deterministic 3-query fallback (topic / thesis / entity+thesis) is appended so the search stage never starves. The plan is persisted to `runs/<run_id>/research/<agent>.plan.json` for audit. Failures (LLM raise, garbage JSON, schema mismatch) degrade to fallback only — the debate never crashes. CI: ruff + ruff format + mypy strict (19 files) + pytest **261 / 261** all green; no new third-party deps.

| Item | Status |
|---|---|
| `auto_debate/research/planner.py` — `PlannedQuery` + `QueryPlan` + `PLANNER_SYSTEM_PROMPT` + `plan_queries` + `persist_plan` | ✅ |
| Strict `<PLAN>{...}</PLAN>` JSON parser with code-fence stripping and bare-object fallback | ✅ |
| Validation enforces 12-word cap, claim-index range, entity-grounding, source-kind whitelist | ✅ |
| Token-set Jaccard ≥ 0.6 deterministic dedup; 8-query hard cap | ✅ |
| Deterministic 3-query fallback when LLM under-delivers (≤ 2 valid queries) | ✅ |
| `Researcher` wires the planner; persists plan to `runs/<run_id>/research/<agent>.plan.json` | ✅ |
| Tests (`tests/test_planner.py` ×19) | ✅ |
| Design contract `docs/research/agentic_research.md` §2.2 honoured verbatim | ✅ |

---

### Phase 20 — Per-Result Favourability Filter _(✅ shipped)_

**Outcome:** When `stance_analysis_enabled` is on and a `StanceBrief` was produced, every search hit is now run through `filter_result(client, brief, query, result)` before reaching the legacy summariser. The filter is one LLM call per hit (`temperature=0.0`, `num_predict=120`) gated by `<FILTER>{...}</FILTER>` strict-JSON; the result snippet is rendered inside an explicit `<RESULT>` block and the system prompt instructs the model to ignore any instructions that appear there. A `keep` verdict is accepted **only** when the model returns a valid `supports_claim` index back into the brief; missing / out-of-range indices, malformed JSON, and LLM exceptions all coerce to `drop` with a structured `reason` (`malformed-filter-output` / `filter-llm-error`). Source-kind classification is a separate deterministic regex over the URL host (`paper|news|forum|wiki|blog|other`) so it cannot inflate the LLM budget. Per-agent kept and dropped hits are persisted to `runs/<run_id>/research/<agent>.hits.json` and `<agent>.drops.json` for audit. The legacy 3-tag summariser path remains as a safety net for the no-stance branch. CI: ruff + ruff format + mypy strict (19 files) + pytest **297 / 297** all green; no new third-party deps.

| Item | Status |
|---|---|
| `auto_debate/research/filter.py` — `FilteredHit` + `FILTER_SYSTEM_PROMPT` + `filter_result` + `classify_source_kind` + `persist_filter_outcomes` | ✅ |
| Strict `<FILTER>{...}</FILTER>` JSON parser with code-fence stripping and bare-object fallback | ✅ |
| Anti-injection guard: snippet rendered inside `<RESULT>` block; system prompt tells model to ignore embedded instructions | ✅ |
| `keep` requires non-null `supports_claim` in range; otherwise coerced to `drop` with `reason="malformed-filter-output"` | ✅ |
| Deterministic URL → source-kind heuristic (paper / news / forum / wiki / blog / other); not an LLM call | ✅ |
| `Researcher` runs the filter between search and summariser; persists `runs/<run_id>/research/<agent>.{hits,drops}.json` | ✅ |
| Tests (`tests/test_filter.py` ×36) | ✅ |
| Design contract `docs/research/agentic_research.md` §2.3 honoured verbatim | ✅ |

---

### Phase 21 — Structured, Attributed Knowledge Synthesis _(✅ shipped)_

**Outcome:** When `stance_analysis_enabled` is on, the legacy per-hit summariser is bypassed entirely on the kept-hits path: a single `synthesise_knowledge(client, brief, kept_hits)` LLM call (`temperature=0.2`, `num_predict=512`) gated by `<KNOWLEDGE>{...}</KNOWLEDGE>` strict-JSON collapses every kept `FilteredHit` into ≤ 10 attributed bullets, grouped by `claim_index`, with at most 2 entries per claim. Attribution prefixes are rendered **deterministically** from the URL host plus the per-source-kind template (`According to {host}`, `In {host}`, `On {host}`, `Per {host}`, `From {host}`) — the LLM never names an outlet, so it cannot hallucinate one. A deterministic citation linter walks each candidate body, extracts every `"..."` quoted phrase, and drops any entry whose quoted phrase does not appear verbatim (case-insensitive, whitespace-collapsed) inside the matched `FilteredHit.result.snippet`. The `Researcher` replaces the agent's `## Knowledge` section wholesale with the rendered bullets (each prefixed `[claim N]`); when zero entries survive, the section reverts to the deterministic `"No verified sources for this turn."` sentinel. Bullets are persisted to `runs/<run_id>/research/<agent>.knowledge.json` for audit. Failures (LLM raise, garbage JSON, total linter rejection) degrade to the empty list — the debate never crashes. CI: ruff + ruff format + mypy strict (19 files) + pytest **333 / 333** all green; no new third-party deps.

| Item | Status |
|---|---|
| `auto_debate/research/knowledge.py` — `KnowledgeEntry` + `KNOWLEDGE_SYSTEM_PROMPT` + `synthesise_knowledge` + `citation_lint` + `persist_knowledge` + `render_knowledge_lines` | ✅ |
| Strict `<KNOWLEDGE>{...}</KNOWLEDGE>` JSON parser with code-fence stripping and bare-object fallback | ✅ |
| Per-source-kind attribution templates rendered from the URL host (LLM never names outlets) | ✅ |
| Deterministic citation linter rejects entries whose quoted phrase is absent from the source snippet | ✅ |
| Hard caps: ≤ 2 entries per `claim_index`, ≤ 10 entries total, body ≤ 30 words; LLM-claimed `source_kind` is overridden by the `FilteredHit` value | ✅ |
| `Researcher` runs the synthesiser after the filter loop; replaces `AgentMemory.knowledge` with the rendered bullets; persists `runs/<run_id>/research/<agent>.knowledge.json` | ✅ |
| Tests (`tests/test_knowledge.py` ×36) | ✅ |
| Design contract `docs/research/agentic_research.md` §2.4 honoured verbatim | ✅ |

> **v0.3 track complete.** All four research stages (stance → plan → filter → synthesise) are now implemented behind the `stance_analysis_enabled` flag. The flag still defaults to `False`; flipping it on and tagging `v0.3.0` is the remaining track exit step (alongside the Phase 22 polish work).

---

### Phase 22 — Run Metadata & Transcript Auto-save _(✅ shipped)_

**Outcome:** Every completed debate now produces a self-contained, on-disk record without any manual download step. The new `auto_debate.run_metadata` module exposes two frozen dataclasses (`ResearchSummary`, `RunMetadata`) and two pure persistence helpers (`persist_transcript`, `persist_run_metadata`); the Streamlit app calls them from a `finally:` clause around the debate loop so the artefacts land regardless of whether the run completed, was Stop-clicked, or aborted on a mid-debate LLM error. Per-turn wall-clock seconds are captured by `time.perf_counter()` bookends inside `DebateEngine.run_one_turn` and surfaced via `engine.turn_seconds()` / `engine.last_turn_seconds()`; aborted turns produce no entry. `Researcher` accumulates a per-agent `ResearchSummary` (`<query> → N hits → M kept` lines, plus aggregate `total_hits` / `kept_hits`) accessible via `researcher.summaries`; the app snapshots it after the research pass, surfaces a non-fatal `st.warning` whenever an agent finishes with `kept_hits == 0`, and renders a collapsible "Research summary" expander before the debate begins. The zero-knowledge log line is now `WARNING` (was `INFO`) so users see a clear signal when the synthesiser falls back to the `"No verified sources for this turn."` sentinel. CI: ruff + ruff format + mypy strict (20 source files) + pytest **353 / 353** all green; no new third-party deps.

| Item | Status |
|---|---|
| `auto_debate/run_metadata.py` — `ResearchSummary` + `RunMetadata` + `settings_snapshot` + `persist_transcript` + `persist_run_metadata` | ✅ |
| `DebateEngine.run_one_turn` instrumented with `time.perf_counter()` bookends; `turn_seconds()` / `last_turn_seconds()` accessors | ✅ |
| Per-turn `seconds` field stamped onto each `st.session_state.messages` entry alongside `metrics` | ✅ |
| `Researcher.summaries` populated per agent (`<query> → N hits → M kept`); zero-knowledge log promoted to `WARNING` | ✅ |
| `_run_debate` `finally:` writes `runs/<run_id>/auto_debate_transcript.md` and `runs/<run_id>/run.json` whenever memory is enabled | ✅ |
| `run.json` carries `topic`, `started_at`, `finished_at`, `total_seconds`, `settings` snapshot, `per_turn_seconds`, and `research_summary` | ✅ |
| Sidebar / mid-debate UI surfaces zero-survival as `st.warning` and renders the “Research summary” expander | ✅ |
| Tests (`tests/test_run_metadata.py` ×16 + 3 in `test_engine.py` + 2 in `test_research.py`) | ✅ |

> **v0.3 track ready to tag.** Phases 16-22 are all green; the four-stage research DAG is implemented behind `stance_analysis_enabled` and the audit trail is now complete (`<agent>.{plan,hits,drops,knowledge}.json` plus `run.json` and the auto-saved transcript). Flipping the stance flag to `True` by default and cutting **`v0.3.0`** is the remaining track exit step.
