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

## Upcoming — v0.3 Track

> Phase 15 is complete. New phases are listed below.
> Append exit criteria and update Status as implementation progresses.

---

### Phase 16 — Run Metadata & Transcript Auto-save _(planned)_

**Goal:** Every run produces a complete, self-contained record without any
manual download step. Targets the gaps identified in the
`20260428T110241Z` post-mortem analysis.

**Planned deliverables**

| Item | Detail |
|---|---|
| Auto-save transcript | Write `runs/<run_id>/auto_debate_transcript.md` at the end of `_run_debate` when memory is enabled. |
| `run.json` | Persist settings snapshot + `started_at`, `finished_at`, per-phase wall-clock seconds, per-turn seconds. |
| Per-turn timing | Instrument `engine.run_one_turn` with `time.perf_counter` bookends; store on the message dict alongside `metrics`. |
| Research summary | Expose `<query> → N hits` per agent in `run.json` and in a collapsible UI panel. |
| Zero-knowledge warning | Promote the "research populated 0 entries" log to `WARNING`; surface it as `st.warning`. |
| Summariser tightening | Strengthen `_SUMMARY_SYSTEM` prompt to default ambiguous hits to `irrelevant`; add regression test. |

**Phase 16 Exit Criteria**
- [ ] `runs/<run_id>/auto_debate_transcript.md` exists after every completed debate when memory is enabled.
- [ ] `runs/<run_id>/run.json` contains at minimum: `topic`, `started_at`, `finished_at`, `total_seconds`, `settings`, `per_turn_seconds`.
- [ ] CI green (ruff + mypy + pytest).
