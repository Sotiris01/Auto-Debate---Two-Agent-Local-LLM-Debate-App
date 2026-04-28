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

### Phase 12 — Pre-Turn Memory Reflection 📋

**Goal:** Before each turn, the speaking agent runs a dedicated
**reflection prompt** that reads the opponent's latest answer and
updates its own `## Observations` and `## Strategy` sections — *then* it
generates the actual debate turn. Targets **Q4 looping 2/5** in
[report.md](report.md).

**Steps**

1. **12.1 — Reflection prompt fragment.** New role-like fragment
   `REFLECTOR` with a strict output schema:
   ```
   <UPDATE>
   add_observations: ["..."]
   add_strategy: ["..."]
   drop_observations: [<index>, ...]
   drop_strategy: [<index>, ...]
   </UPDATE>
   ```
   The reflection LLM call sees: role, current memory, opponent's last
   turn. It does not see the conversation history — its only job is to
   diff the memory.
2. **12.2 — Memory mutator.** `MemoryStore.apply_update(memory, update)`
   — strict validator (drops out-of-range indices, caps additions at 5
   per turn, dedupes against existing entries). Returns a new
   `AgentMemory`; never mutates in place.
3. **12.3 — Engine wiring.** `DebateEngine.run_one_turn(speaker)` becomes
   a two-stage pipeline:
   - **Stage A (silent):** call reflection prompt → apply update → save
     memory. Skipped on turn 1 (no opponent text yet).
   - **Stage B (streamed):** call speaking prompt with the *updated*
     memory injected → stream tokens to UI.
   Stage A runs with `stream=False` and a low `num_predict` cap (e.g.
   200 tokens) — it's a small, cheap call.
4. **12.4 — UI surface.** Each chat bubble shows a tiny "🧠 reflected"
   chip with hover-to-reveal diff (`+2 observations, +1 strategy,
   -1 dropped`). Memory expanders update live between turns.
5. **12.5 — Closing-round prompt.** Bonus addressing **Q8 Structure
   3/5** from the report: when `closing_round_enabled=True` and
   `turn_index == max_turns - 1`, swap the speaking behavior fragment
   for `CLOSING` ("Summarise your strongest argument; do not introduce
   new attacks; explicitly acknowledge the strongest opposing point").
6. **12.6 — Tests.** `tests/test_reflection.py` — schema parsing,
   mutator boundary conditions, two-stage pipeline ordering (mocked
   LLM), turn-1 skip rule, closing-round swap.

**Phase 12 Exit Criteria**
- [ ] After 5 turns, each agent's `## Observations` section has grown
  monotonically and references opponent-specific phrases (verified in a
  live smoke run).
- [ ] Reflection failures (malformed JSON, LLM error) degrade
  gracefully: speaking turn proceeds with the previous memory and a
  warning is logged.
- [ ] Closing-round prompt produces visibly different last turns
  (manual QA, captured in updated [report.md](report.md)).

---

### Phase 13 — Repetition & Quality Guards 📋

**Goal:** Address the remaining report.md weakness directly:
quantitatively detect when the debate is looping or drifting and surface
it in the UI. **No model changes** — pure post-processing on the
streamed turns.

**Steps**

1. **13.1 — Novelty scorer.** `auto_debate/quality.py` —
   `ngram_overlap(turn, prev_turns, *, n=3) -> float` returning the
   Jaccard similarity of 3-grams between the new turn and the union of
   the previous 2. Threshold-based label: `LOW / MEDIUM / HIGH novelty`.
2. **13.2 — Topic-adherence scorer.** TF-IDF cosine between each turn
   and the topic string + agent role. No external model — pure
   `sklearn`-free implementation using `collections.Counter`.
3. **13.3 — Per-turn QA chips.** Streamlit renders a faint chip below
   each chat bubble: `novelty 0.78 · adherence 0.62`. Colour-coded
   green/amber/red against thresholds from `Settings`.
4. **13.4 — Loop hint.** When 3 consecutive turns score below the
   novelty threshold, the UI shows a non-blocking `st.info`: "Agents may
   be repeating themselves — consider stopping or enabling closing
   round."
5. **13.5 — Transcript export enrichment.** `engine.to_markdown()` gains
   an optional `include_quality_metrics=True` flag that appends a
   summary table at the end (per-turn novelty + adherence + overall
   weighted score) so future report.md generations can be partially
   automated.
6. **13.6 — Tests.** `tests/test_quality.py` — scorer correctness on
   synthetic transcripts (identical text → 1.0 overlap; disjoint text →
   ~0 overlap), threshold gating, markdown enrichment.

**Phase 13 Exit Criteria**
- [ ] Re-running the v0.1.0 sample debate through the new metrics
  reproduces the report.md verdict (looping flagged at ~Turn 13+).
- [ ] Per-turn chips render correctly in the live UI.
- [ ] Transcript export with metrics is valid Markdown that opens in
  GitHub preview.

---

### Phase 14 — Persona & Behavior Library 📋

**Goal:** Ship a real catalogue of swappable personalities and
behaviors, validating that the Phase 9 composer scales beyond the
default pair.

**Steps**

1. **14.1 — Author 5+ personas.** YAML files under
   `prompts/library/personas/`: `socratic.yaml`, `tabloid.yaml`,
   `professor.yaml`, `politician.yaml`, `comedian.yaml`. Each ≤ 80
   words.
2. **14.2 — Author 4+ behaviors.** `prompts/library/behaviors/`:
   `cite_evidence.yaml` (must reference at least one knowledge entry),
   `steelman.yaml` (must restate opponent before rebutting),
   `concise.yaml` (≤ 50 words/turn), `analytical.yaml` (numbered
   bullets).
3. **14.3 — Persona × persona compatibility check.** Optional
   one-shot validator that warns if a persona/behavior combo is
   contradictory (e.g. `concise` + `analytical_with_5_bullets`). Pure
   heuristic, no LLM call.
4. **14.4 — UI: persona presets.** Sidebar "Preset" dropdown with named
   bundles (e.g. "Academic debate" = professor + steelman vs professor
   + cite_evidence; "Tabloid showdown" = tabloid + concise vs
   politician + concise). Custom = manual selection.
5. **14.5 — Persona reproducibility tests.** For each persona, lock a
   seeded run (`temperature=0`, fixed model, fixed topic) and snapshot
   the first turn's first 200 chars; CI compares snapshots to detect
   accidental persona drift after future prompt edits.
6. **14.6 — Docs.** README "Personas" section with one-line description
   per persona and a screenshot of the sidebar.

**Phase 14 Exit Criteria**
- [ ] 5+ personas and 4+ behaviors loadable from the registry.
- [ ] At least 3 named presets selectable in the UI.
- [ ] Snapshot tests for every persona pass on `gemma3:4b`.
- [ ] README documents how to add a new persona without touching code.

---

### Phase 15 — Optional Judge / Evaluator Agent 📋

**Goal:** Automate the report.md rubric: a third agent reads the full
transcript and scores it against the 9 dimensions from
[report.md](report.md). Optional, off by default.

**Steps**

1. **15.1 — Judge role fragment.** New `JUDGE` role with rubric and
   strict JSON output schema (one score per Q1-Q9 plus a verdict
   string).
2. **15.2 — Post-debate hook.** When `judge_enabled=True`, after the
   final turn the engine runs the judge with the full transcript +
   memory files as context, parses the JSON, and renders the scorecard
   as a Streamlit table directly below the debate.
3. **15.3 — Persisted report.** Save the judge output to
   `runs/<run_id>/report.json` and a rendered `report.md` next to the
   transcript — same format as the manual report.md, partially
   automating future quality reviews.
4. **15.4 — Sanity check.** Run the judge against the v0.1.0 sample
   transcript; the produced scores should land within ±1 of the manual
   scores in [report.md](report.md). If not, iterate on the rubric
   prompt.
5. **15.5 — Tests.** `tests/test_judge.py` — schema validation,
   scorecard rendering, persistence path, error handling when the
   judge LLM returns malformed JSON.

**Phase 15 Exit Criteria**
- [ ] Toggling "Enable judge" runs a third LLM pass after the debate.
- [ ] Generated `report.md` is structurally identical to the manual one
  and renders correctly in GitHub preview.
- [ ] All scores within ±1 of the human report on the v0.1.0 sample.
- [ ] **v0.2.0 tag cut** once Phases 9-15 exit criteria are all green.

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
| 12 | Pre-turn memory reflection | 📋 planned |
| 13 | Repetition & quality guards | 📋 planned |
| 14 | Persona & behavior library | 📋 planned |
| 15 | Optional judge agent (→ v0.2.0) | 📋 planned |
| 16+ | Future | — |

---

## Cross-Phase Conventions

- **Branch per phase:** `phase/N-name`, merged to `main` when exit criteria are green.
- **Commit prefix:** `[PN]` (e.g. `[P9]`).
- **No phase skipping.** A phase that fails its exit criteria blocks the next.
- **Tests live next to behavior.** New logic ships with at least one test.
