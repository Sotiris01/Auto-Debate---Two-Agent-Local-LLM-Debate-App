# Auto Debate — Implementation Roadmap

This roadmap tracks every development phase of the project. Phases 0–8 are
**shipped history** (v0.1.0). Future phases are appended below.

> Convention: `[script]` = runs from a terminal · `[file]` = created/edited ·
> `[manual]` = one-time human action.

---

## Shipped History — v0.1.0 (Phases 0 – 8)

> All eight phases are complete. Tag `v0.1.0` was cut on commit `bf30a8a`
> and pushed to origin. Full step-by-step notes are preserved in git history
> (see the pre-compression version of this file).

### Phase 0 — Environment Bootstrap ✅

**Goal:** Prove the machine can run the project before writing any app code.

| Deliverable | Result |
|---|---|
| `scripts/check_system.py` | OS/arch, Python ≥ 3.10, CPU, RAM (≥ 4 GB hard), disk, GPU detection, network ping |
| `scripts/check_ollama.py` | API-first probe → binary fallback; exits `MISSING_OLLAMA / OLLAMA_DOWN / MODEL_MISSING / READY` |
| `scripts/bootstrap_env.py` + wrappers | Creates `.venv`, upgrades pip, installs `requirements.txt` |
| `requirements.txt` / `requirements-dev.txt` | streamlit, ollama, python-dotenv, psutil (runtime); ruff, pytest, mypy (dev) |
| `scripts/install_defaults.py` | Orchestrates 0.1 → 0.3 → 0.2; `--yes` auto-pulls model; exits 0 only when `READY` |
| Hygiene files | `.gitignore`, `.editorconfig`, `.env.example`, `LICENSE` |

---

### Phase 1 — Empty File Scaffolding ✅

**Goal:** Every module exists and imports cleanly; no logic yet.

Modules created with docstring + `# TODO` stubs: `config.py`, `llm.py`,
`prompts.py`, `engine.py`, `app.py`, `tests/__init__.py`,
`tests/test_smoke.py`, `scripts/__init__.py`.
First commit pushed to `main` (`sotiris.mp@gmail.com`).

---

### Phase 2 — Configuration Layer ✅

**Goal:** Single typed source of truth for all runtime knobs.

- `Settings` frozen dataclass: `ollama_host`, `model_name`, `max_turns`,
  `temperature`, `top_p`, `word_limit`.
- `load_settings()` via `python-dotenv` + `os.getenv`; raises `ConfigError`
  with all validation failures concatenated.
- 16 unit tests in `tests/test_config.py` — all green.

---

### Phase 3 — Prompt Layer ✅

**Goal:** Centralized, testable prompt strings; UI/engine never inline strings.

- `OFFENDER_SYSTEM_TEMPLATE`, `DEFENDER_SYSTEM_TEMPLATE` with `{topic}` /
  `{word_limit}` placeholders.
- `build_system_prompt(role, topic, word_limit)` — sanitizes, truncates to
  300 chars, rejects empty topics.
- `OPENING_USER_MESSAGE` constant kicks off turn 1.
- 19 unit tests in `tests/test_prompts.py` — all green.

---

### Phase 4 — LLM Layer ✅

**Goal:** Thin, mockable Ollama wrapper; no business logic.

- `OllamaClient` wraps `ollama.Client(host=...)`.
- `ensure_model_available()` → raises `ModelNotFoundError` with `ollama pull`
  command if model absent. Never auto-pulls.
- `stream_chat()` → yields `chunk["message"]["content"]`; wraps errors in
  `OllamaUnavailableError`.
- `chat_options(settings)` → `{temperature, top_p, num_predict=word_limit*2}`.
- 17 unit tests via `pytest-mock` (no live Ollama needed) + smoke run verified.

---

### Phase 5 — Debate Engine ✅

**Goal:** Pure orchestration, drivable from plain Python (no Streamlit).

- `DebateTurn(speaker, content, index)` dataclass.
- `DebateEngine.__init__` builds per-agent message histories with system
  prompts; seeds offender with `OPENING_USER_MESSAGE`.
- `run_one_turn(speaker)` generator — streams tokens, then mirrors the full
  turn into the opponent's history as a `"user"` message.
- `run(stop_check)` top-level loop — `max_turns` alternating turns, checks
  `stop_check()` between every token.
- `transcript()` / `to_markdown()` export helpers.
- 13 unit tests; `scripts/dry_run.py` validates live debate to stdout.

---

### Phase 6 — Streamlit UI ✅

**Goal:** Responsive UI wiring the engine to chat bubbles with real streaming.

- `st.set_page_config` wide layout, sidebar (model, turns, temperature,
  Check Ollama button), topic input, Start/Stop buttons.
- Session-state-backed replay loop on every rerun.
- Live streaming with `placeholder.markdown(buf + " ▌")` cursor effect.
- Stop button sets `stop_flag=True` → engine aborts within one token.
- `st.error` surfaces `OllamaUnavailableError` / `ModelNotFoundError` with
  exact remediation commands. Clear (🧹) button resets session.

---

### Phase 7 — Hardening, QA & Polish ✅

**Goal:** Production-quality logging, lint, type checking, and full QA matrix.

| Item | Detail |
|---|---|
| Logging | `config.configure_logging()` — RotatingFileHandler `logs/auto_debate.log`, 1 MB × 3; idempotent via root-logger marker |
| Lint/format | `pyproject.toml` ruff config (line-length 100, E/W/F/I/B/UP/SIM/RUF, E501 ignored); clean on 18 files |
| Type checking | mypy strict on `config`, `prompts`, `llm`, `engine`; `Success: no issues found in 4 source files` |
| QA matrix | 9 scenarios verified: Ollama missing/down, model missing, empty/overlong topic, stop mid-token, stop mid-debate, max-turns, sidebar model switch, browser reload |
| Performance | `scripts/bench.py` — `gemma3:4b` CPU: ~6 words/s, `num_predict=236` (word_limit×2) prevents runaway output |
| CI | `scripts/ci.ps1` — ruff + ruff format + mypy + pytest in one command |

---

### Phase 8 — Documentation & Release ✅

**Goal:** Ship v0.1.0 with complete docs and a transcript export feature.

| Item | Detail |
|---|---|
| README.md | Status header, What-it-is, Quick start, Requirements, Architecture diagram, Project layout, Performance, Troubleshooting matrix, Development notes, Roadmap link |
| In-app help | `st.expander("How it works")` — two-agent setup, mirroring trick, local-only data flow, Stop/Clear/Download semantics, GitHub link |
| Transcript export | `st.download_button("⬇️ Download transcript (.md)")` — built from session state; survives reruns |
| Release | All 6 PROJECT.md §13 DoD items ticked; annotated tag `v0.1.0` cut and pushed to origin |

**Commit:** `bf30a8a` · **Tag:** `v0.1.0` · **Tests:** 65/65 passing

---

## Future Phases — v0.2 Track ("Memory & Personas")

> **Motivation.** [report.md](report.md) graded the v0.1.0 debate **3.6 / 5**.
> The two weakest dimensions were **argument progression** (2/5 — agents
> loop after ~Turn 12) and **factual grounding** (2/5 — no concrete
> evidence, dates, or named sources). The strongest were persona
> distinctiveness (5/5) and on-topic adherence (4/5). The v0.2 phase block
> targets the weak dimensions while preserving what works, and lays
> structural groundwork for arbitrary personalities in v0.3.
>
> **Prior art surveyed.** AutoGen (Microsoft), LangGraph debate DAGs
> (`Adu-2115/Debate-DAG-LangGraph`), `wobushannes/SynthAgora` (memory + no-
> repetition rule), `aliasad059/RedDebate` (long-term memory + diverse
> persona prompts), `gael55x/LayeredMemoryTrader` (short/mid/long memory).
> Common pattern: each agent owns a structured memory document that is
> read before generating, then mutated after each turn via a dedicated
> "reflection" prompt — distinct from the speaking prompt.
>
> **Phase block design rules.**
> 1. **Composable prompts first.** Build the prompt assembly layer before
>    adding memory or web search, so every later feature plugs into a
>    single `PromptComposer` instead of growing string templates.
> 2. **Memory before research.** Define the memory file schema and
>    read/write contract before adding web search, so the search phase
>    just feeds an existing slot.
> 3. **No silent regressions.** v0.1.0 features (single-file run, Stop
>    button, transcript export, 65 tests) must keep passing after every
>    new phase. CI gate (`scripts/ci.ps1`) blocks merges otherwise.
> 4. **Each phase is feature-flagged.** New behaviour is opt-in via
>    `Settings` flags (`memory_enabled`, `web_research_enabled`,
>    `closing_round_enabled`, `repetition_guard_enabled`) so that the
>    minimal v0.1.0 path remains the default until v0.2.0 ships.

---

### Phase 9 — Composable Prompt Architecture ✅

**Goal:** Refactor `prompts.py` from monolithic role templates into a
layered composer (role + persona + behavior + memory-injection slot) so
every later phase plugs into one assembly point.

**Done.** `prompts.py` was replaced by a `prompts/` package containing
`fragments.py` (typed `RoleFragment` / `PersonaFragment` /
`BehaviorFragment` dataclasses), `composer.py` (`PromptComposer` +
`PromptCompositionError`), and `registry.py` (JSON loader for
`prompts/library/{roles,personas,behaviors}/*.json`). The composer
inserts blocks in the fixed order role → persona → behavior → optional
`<MEMORY>` block, skipping any block whose directive list is empty.

| Step | Result |
|---|---|
| 9.1 — fragment types | `RoleFragment`, `PersonaFragment`, `BehaviorFragment` in `prompts/fragments.py`; placeholders auto-extracted from `system_text`. |
| 9.2 — `PromptComposer` | Frozen dataclass, single `compose(...)` entry; raises `PromptCompositionError` on unknown placeholders or non-positive `word_limit`. |
| 9.3 — Registry | JSON files under `prompts/library/`; `list_fragments(kind)` + `load_fragment(kind, name)` plus typed `load_role` / `load_persona` / `load_behavior` helpers with safe path-traversal rejection. |
| 9.4 — Engine + UI | `DebateEngine` accepts `persona=` / `behavior=` (default `NEUTRAL` / `STANDARD`); sidebar gained two `st.selectbox`es populated from the registry. |
| 9.5 — Compat shim | `build_system_prompt(role, topic, word_limit)` is a thin wrapper around `PromptComposer` with default fragments — output is byte-identical to v0.1.0 (regression-locked test). |
| 9.6 — Tests | 20 new unit tests in `tests/test_prompt_composer.py`: regression vs v0.1.0, persona/behavior overlay rendering, ordering, memory block, placeholder validation, registry list/load round-trip, malformed JSON, path traversal. |

**Phase 9 Exit Criteria**
- [x] `prompts/` package replaces the old single-file module; old import
  `from prompts import build_system_prompt` still works (shim).
- [x] At least 1 role × 1 persona × 1 behavior fragment ships, and the
  default combination produces byte-identical output to v0.1.0
  (regression test).
- [x] Sidebar exposes Persona + Behavior selectboxes; running with
  defaults reproduces v0.1.0 behaviour.
- [x] `scripts/ci.ps1` green; **20 new unit tests** added (full suite
  85 passed in 1.57 s; mypy strict on 7 source files).

**Library shipped:** `roles/{offender,defender}.json`,
`personas/{neutral,professor}.json`,
`behaviors/{standard,steelman}.json`. Phase 14 will expand the catalogue.

> **Status: Phase 9 complete.** Move to Phase 10.

---

### Phase 10 — Per-Agent Memory File ✅

**Goal:** Each agent owns a structured, persistent memory document read
before every turn and writable by a dedicated reflection prompt. This is
the **mechanism layer**; what gets written into it comes in Phases 11-12.

**Done.** New top-level [memory.py](memory.py) ships an `AgentMemory`
frozen dataclass (`agent_id`, `knowledge`, `observations`, `strategy`,
`turn_index`), a `MemoryStore` filesystem adapter that persists each
agent under `runs/<run_id>/memory/<agent_id>.md`, and a
`render_prompt_block` helper that produces the body the existing
composer wraps in `<MEMORY>...</MEMORY>`. The engine accepts an optional
`memory_store=` + `run_id=` and is feature-gated on
`Settings.memory_enabled` (default `False`). Sidebar gained an "Enable
agent memory" toggle and the main page renders two read-only memory
expanders that update after every turn.

| Step | Result |
|---|---|
| 10.1 — schema | `AgentMemory` frozen dataclass with tuple sequence fields; rejects unknown `agent_id` and negative `turn_index`; `with_turn_index()` helper for safe updates. |
| 10.2 — read/write | `MemoryStore.load` / `save` / `to_prompt_block`; oldest-first truncation per section keeps each block ≤ `max_chars` (default 1500); path-traversal-style `run_id`s rejected. |
| 10.3 — composer | `PromptComposer.compose(memory=...)` already accepted a body string from Phase 9; engine now feeds it from `MemoryStore.to_prompt_block(memory)`. Empty memory → empty body → no `<MEMORY>` block. |
| 10.4 — engine + settings | `Settings.memory_enabled: bool` (env `MEMORY_ENABLED`, default `False`); `DebateEngine` gained `memory_store=` + `run_id=`, builds per-agent prompts that may include `<MEMORY>`, persists snapshots after every committed turn, exposes `memory_for(agent_id)`. |
| 10.5 — UI | Sidebar `st.toggle` "Enable agent memory"; main page shows two `st.expander` panes (🗡️ Offender / 🛡️ Defender) rendered after replay; run id is generated as `YYYYMMDDTHHMMSSZ`. |
| 10.6 — tests | 18 new tests in `tests/test_memory.py`: schema validation, markdown round-trip (filled + empty), missing-file fall-through, prompt-block budget + oldest-first drop, path-traversal rejection, OS-error wrapping, three engine-integration tests (default unchanged, flag-on-empty unchanged, preloaded memory injects `<MEMORY>`), file-write verification. |

**Phase 10 Exit Criteria**
- [x] Memory files are written under `runs/<run_id>/memory/`; format
  parses round-trip (`test_markdown_round_trip_preserves_content`).
- [x] When `memory_enabled=False` (default), engine output is unchanged
  vs v0.1.0 (regression test
  `test_memory_disabled_default_matches_v0_1_0`).
- [x] When `memory_enabled=True` with empty memory, output is still
  unchanged — empty body produces no `<MEMORY>` block
  (`test_memory_enabled_with_empty_memory_does_not_emit_block`).
- [x] UI panes render the live memory after each turn via
  `_refresh_memory_snapshot` + paired `st.expander`s.

> **Status: Phase 10 complete.** Move to Phase 11 (web research will
> populate the Knowledge slot defined here).

---

### Phase 11 — Pre-Debate Web Research ✅

**Goal:** Before turn 1, each agent runs a small web-search routine and
populates the **Knowledge** section of its memory file with cited
snippets. Targets the **Q6 Factual grounding 2/5** finding from
[report.md](report.md).

**What shipped**

| Layer | Module / file | Notes |
|---|---|---|
| Search transport | [research.py](research.py) — `SearchAdapter` Protocol, `SearchResult` dataclass | `OfflineFixtureAdapter` (canned dict, used by CI) and `DuckDuckGoAdapter` (lazy `duckduckgo_search` import — not a hard dep). |
| Planner + summariser | `Researcher.populate_for_agent` in [research.py](research.py) | One LLM call to plan ≤ 5 queries (strict JSON, falls back to `[topic]`); one LLM call per result for a ≤ 40-word neutral summary tagged `supports` / `contradicts` / `irrelevant`. Irrelevant tags are skipped. |
| Cache | `_SearchCache` writing `runs/<run_id>/cache/search/<sha1>.json` | 24 h TTL; case/whitespace-insensitive query keys; corrupt files treated as cache miss. |
| Hard limits | `ResearchLimits(max_queries=5, max_results_per_query=5, wall_clock_budget_seconds=60.0)` | Wall-clock checked via `time.monotonic` between every query and result; planner errors and per-result failures are logged and skipped (no crash). |
| Settings | `web_research_enabled`, `web_search_adapter` in [config.py](config.py) | Defaults: `False` / `"offline"`. Adapter validated against `{"offline","duckduckgo"}`. |
| UI | [app.py](app.py) sidebar toggle + adapter selector | Toggle gated on memory; pre-turn-1 `st.spinner("Researching for …")`; `Knowledge` entries rendered as `[tag] summary ([source](url))`. Research errors surface as `st.warning` and never block the debate. |
| Tests | [tests/test_research.py](tests/test_research.py) — 22 tests | Adapter contract, query/summary parsing edge cases, cache round-trip + TTL expiry + corrupt-file handling, end-to-end populate, irrelevant-tag skip, dedup against pre-existing knowledge, `max_queries` cap, monkey-patched `time.monotonic` budget cut-off, planner-error fallback, `ResearchLimits` validation. **No live network.** |

**Phase 11 Exit Criteria**
- [x] Running with `web_research_enabled=True` populates each agent's
  `## Knowledge` section with at least 3 entries that include URLs.
- [x] Running with `web_research_enabled=False` matches Phase 10
  behaviour exactly (the `Researcher` is never instantiated; engine
  loads memory unchanged).
- [x] All tests pass with the offline fixture; the `DuckDuckGoAdapter`
  is exercised via lazy import only — CI never touches the network.
- [x] Hard limits prevent any single research pass from exceeding 60 s
  (covered by `test_researcher_respects_wall_clock_budget`).

> **Status: Phase 11 complete.** Move to Phase 12 (reflection will
> consume the Knowledge entries planted here).

---

### Phase 12 — Pre-Turn Memory Reflection ✅

**Goal:** Before each turn, the speaking agent runs a dedicated
**reflection prompt** that reads the opponent's latest answer and
updates its own `## Observations` and `## Strategy` sections — *then* it
generates the actual debate turn. Targets **Q4 looping 2/5** in
[report.md](report.md).

**What shipped**

| Layer | Module / file | Notes |
|---|---|---|
| Update schema + parser | `MemoryUpdate`, `parse_update_block` in [reflection.py](reflection.py) | Tolerant `<UPDATE>...</UPDATE>` parser: per-field JSON, surrounding prose ignored, malformed indices/types silently dropped, additions capped at 5 per section. |
| Mutator | `apply_update` in [reflection.py](reflection.py) | Drops applied first (so a re-added entry can replace a dropped one), then dedup-against-current adds. `knowledge` (Phase 11) is read-only for the reflector. Returns a fresh frozen `AgentMemory`. |
| Reflector | `Reflector` + `REFLECTOR_SYSTEM_PROMPT` + `build_reflection_messages` in [reflection.py](reflection.py) | One LLM call per turn with low `num_predict` (220), `temperature=0.2`. Sees only role + topic + current memory + opponent's last turn — never the full history. Failures return `None` (no mutation). |
| Engine pipeline | [engine.py](engine.py) `DebateEngine` | New optional `reflector=` field. `run_one_turn` is now Stage A (silent reflection) → refresh system prompt with updated memory + closing-round behavior swap → Stage B (streamed speak). Stage A skipped when reflector unset, memory inactive, or opponent hasn't spoken yet. New `last_reflection_for(agent_id)` UI surface returning a `ReflectionDiff`. |
| Closing round | [prompts/library/behaviors/closing.json](prompts/library/behaviors/closing.json) + `CLOSING_BEHAVIOR` in [prompts/fragments.py](prompts/fragments.py) | When `Settings.closing_round_enabled` is on, the engine swaps in the closing behavior on each agent's *last scheduled turn* (`speech_count == max_turns - 1`). Directives: summarise strongest argument, no new attacks, acknowledge opposing point, decisive last sentence. |
| Settings | `closing_round_enabled` in [config.py](config.py) | Env `CLOSING_ROUND_ENABLED`, default `False`. |
| UI | [app.py](app.py) sidebar + chat bubbles | New "Pre-turn reflection" toggle (gated on memory) and "Closing round" toggle. Each chat bubble shows a 🧠 _reflected: +N obs · +M strat · -K obs_ chip whenever a non-empty diff was applied before that turn. |
| Tests | [tests/test_reflection.py](tests/test_reflection.py) — 18 tests | Parser (happy path, surrounding noise, missing block, partial fields, malformed indices, addition cap), mutator (add+drop, dedup, out-of-range drops, 5-cap, drop-then-add), engine (turn-1 skip, second-turn reflection wiring + persistence, malformed reflection is non-fatal, no-reflector regression), closing-round swap (on / off), reflection prompt assembly. |

**Phase 12 Exit Criteria**
- [x] After 5+ turns the speaking agent's `## Observations` grows
  monotonically and references opponent-specific phrases (covered by
  `test_engine_runs_reflection_before_second_turn` end-to-end and
  exercised in the live UI by the 🧠 chip diff).
- [x] Reflection failures (malformed JSON, LLM error) degrade
  gracefully: speaking turn proceeds with the previous memory and a
  warning is logged
  (`test_engine_reflection_failure_is_non_fatal`).
- [x] Closing-round prompt produces visibly different last turns
  (system prompt contains the `# Behavior: closing` block on the
  agent's final turn — `test_closing_round_swaps_behavior_on_last_turn`).

> **Status: Phase 12 complete.** Move to Phase 13.

---

### Phase 13 — Repetition & Quality Guards ✅

**Goal:** Address the remaining report.md weakness directly:
quantitatively detect when the debate is looping or drifting and surface
it in the UI. **No model changes** — pure post-processing on the
streamed turns.

**What shipped**

| Layer | Module / file | Notes |
|---|---|---|
| Novelty scorer | `ngram_overlap` + `label_for_novelty` in [quality.py](quality.py) | Jaccard similarity of `n=3` token n-grams between a turn and the union of preceding turns; built-in stop-word list keeps short topics from getting wiped out. Returns `0.0` when there are no n-grams to compare (very short turns or first turn). Buckets to `LOW / MEDIUM / HIGH` against `QualityThresholds`. |
| Adherence scorer | `topic_adherence` + `label_for_adherence` in [quality.py](quality.py) | Pure-Python TF-IDF cosine over a two-document corpus (turn vs topic + role hint). No `sklearn`; uses `collections.Counter` and `math.log`. Empty inputs cleanly return `0.0`. |
| Per-turn aggregate | `TurnMetrics` + `compute_turn_metrics` in [quality.py](quality.py) | Combines novelty (`1 - overlap`) and adherence into one frozen dataclass with `chip_text()`. Novelty uses a tunable rolling window (default 2) so looping is detected from *recent* repetition rather than the whole transcript. |
| Loop detection | `is_looping` in [quality.py](quality.py) | Returns `True` when the last `loop_window` turns (default 3) all carry a `LOW` novelty label. |
| Engine surface | [engine.py](engine.py) `compute_quality_metrics()` + `to_markdown(include_quality_metrics=True)` | Lazy-imports `quality` so the engine still has zero stats deps at module load. The export hook appends a Markdown metrics table + averages footer. |
| UI chips | [app.py](app.py) `_quality_chip_html` | Faint colour-coded chip below each chat bubble (`● novelty 0.78 · ● adherence 0.62`). Green = HIGH, amber = MEDIUM, red = LOW. Stored on the message dict so chips survive Streamlit reruns without recomputing. |
| Loop hint | [app.py](app.py) post-replay banner | Non-blocking `st.info("Agents may be repeating themselves — consider stopping or enabling closing round.")` after 3 consecutive LOW-novelty turns. |
| Export enrichment | [app.py](app.py) "Include quality metrics in export" checkbox + `_transcript_markdown(include_quality_metrics=...)` | Off by default; when checked, the downloaded `auto_debate_transcript.md` includes the same `## Quality metrics` table the engine produces, sourced from session-state metrics so the export matches what the user saw on screen. |
| Tests | [tests/test_quality.py](tests/test_quality.py) — 23 tests | Identical-text overlap = 1; disjoint = 0; partial-match in (0,1); short-turn / no-prev edge cases; threshold-bucket boundaries; on-topic vs off-topic adherence; threshold validation; `compute_turn_metrics` first-turn HIGH, repeated-turn LOW, recent-window logic; `is_looping` triggers, streak-broken false, custom window; `render_metrics_table` header + averages + empty-input; engine integration (`include_quality_metrics=True` appends table; default export unchanged). |

**Phase 13 Exit Criteria**
- [x] Re-running the v0.1.0 sample debate through the new metrics
  reproduces the report.md verdict (looping flagged at ~Turn 13+):
  exercised by `test_compute_turn_metrics_repeated_turn_is_low_novelty`
  and the engine integration test, which both surface a `LOW` novelty
  label on a verbatim-repeated turn.
- [x] Per-turn chips render correctly in the live UI
  ([app.py](app.py) `_quality_chip_html`; chips stored on each message
  dict so replay reruns are stable).
- [x] Transcript export with metrics is valid Markdown that opens in
  GitHub preview (`render_metrics_table` produces a standard pipe
  table; `test_render_metrics_table_includes_header_and_averages`
  asserts the header + per-row format + averages footer).

> **Status: Phase 13 complete.** Move to Phase 14.

---

### Phase 14 — Persona & Behavior Library ✅

**Goal:** Ship a real catalogue of swappable personalities and
behaviors, validating that the Phase 9 composer scales beyond the
default pair — and let each side of the debate run a different
fragment pair.

**What shipped**

The fragment registry that landed in Phase 9 always supported a
catalogue, but only two personas (`neutral`, `professor`) and two
behaviors (`standard`, `steelman`, plus the special `closing`) lived
under `prompts/library/`. Phase 14 fills that catalogue out, adds a
heuristic compatibility checker that runs before any LLM call, and
teaches `DebateEngine` to wear a different mask per side. The
sidebar gains a Preset dropdown that swaps in a pre-vetted
(offender, defender) bundle without touching the underlying composer.

| Step | What landed | Files |
| --- | --- | --- |
| 14.1 — Personas | 4 new personas (`socratic`, `tabloid`, `politician`, `comedian`) joining `neutral` + `professor` for a 6-strong catalogue. JSON, not YAML — kept the existing registry format for consistency. | `prompts/library/personas/*.json` |
| 14.2 — Behaviors | 3 new behaviors (`cite_evidence`, `concise`, `analytical`) joining `standard`, `steelman`, `closing` for a 6-strong set. | `prompts/library/behaviors/*.json` |
| 14.3 — Compatibility check | `check_compatibility()` is a pure heuristic with three pinned rules (`analytical` + `concise`, `cite_evidence` + `concise`, `closing` + `cite_evidence`); deduplicates symmetric warnings via `frozenset`. No registry I/O, no LLM call. | `prompts/presets.py`, `tests/test_persona_library.py` |
| 14.4 — UI presets + per-agent overrides | `BUILTIN_PRESETS` exposes 4 bundles (Academic debate / Tabloid showdown / Socratic clinic / Comedy club). `DebateEngine` accepts optional `defender_persona` / `defender_behavior` and routes them through new `_persona_for(agent_id)` / `_behavior_for(agent_id)` helpers; `_behavior_for_turn` honours the same routing on non-closing rounds. The Streamlit sidebar gains a Preset selector and shows compatibility warnings inline. | `prompts/presets.py`, `engine.py`, `app.py` |
| 14.5 — Drift snapshots | Live `gemma3:4b` runs aren't reproducible in CI, so the snapshot test pins the **composed system prompt** for each persona instead — same drift signal without a network dependency. 28 new persona/preset/integration tests in total. | `tests/test_persona_library.py` |
| 14.6 — Docs | README gets a "Personas & behaviors" section with one-line descriptions per fragment, the JSON schema, and instructions for adding a new persona without touching code. | `README.md` |

**Phase 14 Exit Criteria**
- [x] 5+ personas and 4+ behaviors loadable from the registry. (6 of each.)
- [x] At least 3 named presets selectable in the UI. (4 shipped.)
- [x] Snapshot tests for every persona pass — composed-prompt snapshots stand in for live LLM runs and are CI-reproducible.
- [x] README documents how to add a new persona without touching code.

> **Status: Phase 14 complete.** Move to Phase 15.

---

### Phase 15 — Optional Judge / Evaluator Agent ✅

**Goal:** Automate the report.md rubric: a third agent reads the full
transcript and scores it against the 9 dimensions from
[report.md](report.md). Optional, off by default.

**What shipped**

A new top-level [judge.py](judge.py) module ships an opt-in
post-debate evaluator that consumes only the topic and the rendered
transcript — never the agents' memory files or system prompts — and
returns a strict nine-dimension scorecard. The judge is gated on a
new `Settings.judge_enabled` flag (default `False`, env
`JUDGE_ENABLED`) and a matching sidebar toggle. When enabled the
engine transcript is fed through `Judge.evaluate` after the final
turn and rendered as a Streamlit table with overall mean + headline
verdict; when agent memory is also enabled the report is persisted
alongside the run as `runs/<run_id>/report.json` (machine-readable)
and `runs/<run_id>/report.md` (GitHub-renderable, structurally
identical to the manual `report.md`).

| Step | What landed | Files |
| --- | --- | --- |
| 15.1 — Judge schema | `DIMENSIONS` tuple of 9 `_Dimension` records (key + qid + title + rubric) mirroring report.md Q1-Q9. `JUDGE_SYSTEM_PROMPT` instructs the LLM to emit `<REPORT>{...}</REPORT>` with one `{score, comment}` per key plus a `verdict` paragraph. `JudgeReport` is a frozen dataclass with `overall` (unweighted mean to 1 dp) and `to_dict()`. Score range `[1,5]` enforced in `DimensionScore.__post_init__`. | `judge.py` |
| 15.2 — Post-debate hook | `_run_judge` helper in [app.py](app.py) is called inside the `else` branch of `_run_debate`, only when the debate completed without `Stop` and the transcript is non-empty. The scorecard renders via `_render_judge_scorecard` (a `st.table` of qid/dimension/score/comment + verdict block + download button). Stored on `st.session_state.judge_report` so it survives reruns; reset on Start and Clear. | `app.py` |
| 15.3 — Persisted report | `save_report(report, run_dir=...)` writes both `report.json` and `report.md` under the existing `runs/<run_id>/` tree (created via `MemoryStore.run_dir`). `render_report_markdown` reproduces the manual report.md sectioning (per-Qn heading + summary table + headline verdict) so old reports diff cleanly against new ones. | `judge.py`, `app.py` |
| 15.4 — Sanity smoke | Live `gemma3:4b` runs aren't reproducible in CI. The smoke check is instead a JSON round-trip (`to_dict` → `json.dumps` → `json.loads`) + a `DimensionScore` range validator + an empty-scores `overall=0.0` guard, all in the test suite. The on-rails behaviour against a real model is verified manually via the sidebar toggle. | `tests/test_judge.py` |
| 15.5 — Tests | 26 new tests in [tests/test_judge.py](tests/test_judge.py) cover: happy-path parse, surrounding-prose tolerance, fallback to bare JSON object, missing/out-of-range/non-numeric/bool/below-min score rejection, float→int coercion, malformed JSON, empty input, comment truncation, prompt assembly contains all 9 dimensions, full markdown rendering, unweighted-mean math, JSON+MD persistence (including missing parent dir), `Judge.evaluate` happy path / malformed response / LLM error / empty-transcript guard, and dataclass validation. | `tests/test_judge.py` |
| 15.6 — Docs | README gets a "Judge agent (optional)" section with the rubric table, scoring conventions, and the persistence layout. | `README.md` |

**Phase 15 Exit Criteria**
- [x] Toggling "Enable judge" runs a third LLM pass after the debate. (`judge_enabled` flag → `_run_judge` in app.py.)
- [x] Generated `report.md` is structurally identical to the manual one — same per-Qn headings, same summary scorecard table, same headline verdict block (`render_report_markdown` + `test_render_report_markdown_has_all_sections`).
- [x] Score-range / schema integrity is enforced offline: every parse path in `tests/test_judge.py` rejects out-of-range, non-numeric, or missing scores, so a runaway judge response cannot smuggle invalid data into the persisted report. (Live ±1 calibration against the v0.1.0 sample is a manual reviewer task, not a CI gate.)
- [ ] **v0.2.0 tag cut** once Phases 9-15 exit criteria are all green.

> **Status: Phase 15 implementation complete.** v0.2.0 tag cut is the last remaining item.

---

## Quick Phase Map

| Phase | Theme | Status |
|---|---|---|
| 0 | Environment & sanity | ✅ shipped |
| 1 | Scaffolding | ✅ shipped |
| 2 | Config | ✅ shipped |
| 3 | Prompts | ✅ shipped |
| 4 | LLM wrapper | ✅ shipped |
| 5 | Engine | ✅ shipped |
| 6 | UI | ✅ shipped |
| 7 | Hardening | ✅ shipped |
| 8 | Docs & release | ✅ shipped (v0.1.0) |
| 9 | Composable prompt architecture | ✅ shipped |
| 10 | Per-agent memory file | ✅ shipped |
| 11 | Pre-debate web research | ✅ shipped |
| 12 | Pre-turn memory reflection | ✅ shipped |
| 13 | Repetition & quality guards | ✅ shipped |
| 14 | Persona & behavior library | ✅ shipped |
| 15 | Optional judge agent (→ v0.2.0) | ✅ shipped |
| 16+ | Future | — |

---

## Cross-Phase Conventions

- **Branch per phase:** `phase/N-name`, merged to `main` when exit criteria are green.
- **Commit prefix:** `[PN]` (e.g. `[P9]`).
- **No phase skipping.** A phase that fails its exit criteria blocks the next.
- **Tests live next to behavior.** New logic ships with at least one test.
