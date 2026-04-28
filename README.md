# Auto Debate

A local two-agent LLM debate app: two Gemma-3 personas (Offender 🗡️ vs
Defender 🛡️) argue a user-supplied topic, streamed live in a Streamlit chat
UI, powered by [Ollama](https://ollama.com) running on your own machine.

> **Status:** v0.3 track ready to tag — Phases 0-22 shipped, **353 / 353
> tests** passing, mypy strict on 20 source files. The four-stage agentic
> research DAG (stance → plan → filter → synthesise) and run-level
> persistence (auto-saved transcript + `run.json`) are now in. See
> [ROADMAP.md](ROADMAP.md) for the per-phase build log,
> [PROJECT.md](PROJECT.md) for the original spec, and
> [docs/research/agentic_research.md](docs/research/agentic_research.md)
> for the v0.3 research design (Phase 17).

## What it is

- **100 % local.** No cloud calls, no telemetry — your debate, memory,
  reflections, research notes, judge report, and run metadata stay on
  your machine.
- **Two agents through one Ollama chat model.** The engine maintains two
  parallel chat histories and mirrors each turn into the opponent's
  history so a single model can play both sides without role confusion.
- **Token-streamed UI** with a typewriter cursor, a real **Stop** button
  (halts within one token), and a one-click **Download transcript (.md)**
  export.
- **Optional layered features**, all gated by `Settings` flags so the
  default v0.1 behaviour is preserved unless you opt in:
  - `MEMORY_ENABLED` — per-agent persistent memory at
    `runs/<run_id>/<agent>.md`.
  - `WEB_RESEARCH_ENABLED` + `WEB_SEARCH_ADAPTER` — pre-debate research
    via a DuckDuckGo or offline-fixture adapter, with a SHA1 search
    cache.
  - `STANCE_ANALYSIS_ENABLED` — turns research into the v0.3 four-stage
    pipeline (stance brief → query plan → per-result filter → attributed
    Knowledge synthesis), each stage one strict-JSON LLM call with
    deterministic fallbacks.
  - `CLOSING_ROUND_ENABLED` — forces the final turn into the `closing`
    behavior fragment (summary, no new evidence).
  - `JUDGE_ENABLED` — a third LLM pass scores the transcript on 9
    dimensions and writes `report.{json,md}` next to the run.
- **Reproducible audit trail.** Every run with memory enabled writes a
  full directory under `runs/<run_id>/`: `auto_debate_transcript.md`,
  `run.json` (topic, timestamps, per-turn seconds, settings snapshot,
  per-agent research summary), `<agent>.md` (memory), the v0.3 research
  artefacts (`<agent>.{plan,hits,drops,knowledge}.json`), and the judge
  report when enabled.

## Quick start

```powershell
# 1. Clone, then run the one-shot installer (assumes Ollama is installed
#    and the server is running):
python scripts/install_defaults.py --yes

# 2. Activate the venv and launch the UI:
.\.venv\Scripts\Activate.ps1
streamlit run app.py

# Or use the all-in-one Windows launcher (runs system+Ollama checks first):
./run.ps1
```

The installer will:

1. Run the system / hardware sanity check.
2. Create `.venv/` and install pinned Python dependencies.
3. Probe the Ollama API and pull `gemma3:4b` if missing.

It will **never** install the Ollama binary itself or start the server —
those remain conscious user actions.

## Requirements

- Python ≥ 3.10 (3.11 recommended; see `.python-version`).
- [Ollama](https://ollama.com) installed and running locally.
- ~10 GB free disk for the model + venv.
- See `scripts/check_system.py` for the full check matrix.

## Architecture

```
                ┌───────────────────────────────────────────────────────┐
                │  app.py                                               │
                │  Streamlit UI — sidebar, chat bubbles, Stop, expanders │
                │  (Phase 6, expanded through Phases 10-22)              │
                └────────┬───────────────────────────────────────┬──────┘
                         │ stream_chat tokens                    │ snapshots
                         │                                       ▼
                ┌────────▼──────────┐                   ┌─────────────────┐
                │ DebateEngine      │                   │ run_metadata    │
                │ run_one_turn()    │  per-turn         │ persist_*()     │
                │ + perf_counter    │─────────────────▶ │ run.json        │
                │ (P5 + P22)        │  seconds          │ transcript.md   │
                └─┬─────┬───────┬───┘                   └─────────────────┘
                  │     │       │
        prompts/  │     │       │  reflection.py / quality.py / judge.py
        (P3,P9,P14)     │       │  memory.py     (P10/P12/P13/P15)
                        │       │
                        ▼       ▼
                ┌───────────────────────────────────────┐
                │ research/  (Phase 11 + v0.3 P18-P21)  │
                │ stance → planner → filter → knowledge │
                │ + Researcher / SearchAdapter          │
                └────────────────┬──────────────────────┘
                                 │ chat / stream_chat
                                 ▼
                          ┌────────────┐
                          │ llm.py     │  OllamaClient
                          │ (P4)       │  http://localhost:11434
                          └────────────┘
```

Layer order is **config → prompts → llm → engine → research / memory /
reflection / quality / judge / run_metadata → app**, each module fully
tested before the next is built. The engine has no Streamlit
dependency; the app has no direct Ollama dependency. Full message-flow
examples live in [PROJECT.md §4](PROJECT.md).

## Project layout

> **Phase 16 (v0.3 track):** All source modules live under the
> `auto_debate/` package. The repository root keeps only `app.py` (the
> Streamlit entry point) and tooling.

| Path                                | Role                                                           |
| ----------------------------------- | -------------------------------------------------------------- |
| `app.py`                            | Streamlit UI (entry point).                                    |
| `auto_debate/config.py`             | Typed `Settings` loader (env / `.env`) + rotating-file logging. |
| `auto_debate/llm.py`                | Thin streaming Ollama client (mockable in tests).              |
| `auto_debate/engine.py`             | `DebateEngine`, `run_one_turn`, per-turn `perf_counter` timing. |
| `auto_debate/memory.py`             | `AgentMemory` + `MemoryStore` (per-agent markdown files).      |
| `auto_debate/reflection.py`         | Pre-turn `Reflector` + structured memory updates.              |
| `auto_debate/quality.py`            | n-gram novelty / TF-IDF adherence / loop detection.            |
| `auto_debate/judge.py`              | 9-dimension judge / scorecard renderer.                        |
| `auto_debate/run_metadata.py`       | `RunMetadata` + `ResearchSummary` + `persist_*` helpers (P22). |
| `auto_debate/prompts/`              | `PromptComposer`, role / persona / behavior fragment registry. |
| `auto_debate/prompts/library/`      | JSON catalogue: 2 roles · 6 personas · 6 behaviors.            |
| `auto_debate/research/researcher.py`| Pre-debate web research orchestrator + DuckDuckGo / offline adapters + SHA1 cache. |
| `auto_debate/research/stance.py`    | v0.3 stance brief — `analyse_topic`, `<STANCE>` JSON.          |
| `auto_debate/research/planner.py`   | v0.3 stance-driven query planner — `<PLAN>` JSON.              |
| `auto_debate/research/filter.py`    | v0.3 per-result favourability filter — `<FILTER>` JSON.        |
| `auto_debate/research/knowledge.py` | v0.3 attributed Knowledge synthesis — `<KNOWLEDGE>` JSON + citation linter. |
| `tests/`                            | 17 test modules, 353 tests (pytest).                           |
| `run.ps1`                           | Windows launcher (`check_system` + `check_ollama` + Streamlit).|
| `scripts/install_defaults.py`       | One-shot installer (sanity check + venv + deps + model pull).  |
| `scripts/ci.ps1`                    | Lint + format + mypy + pytest, one command.                    |
| `scripts/bench.py`                  | Performance sanity benchmark.                                  |
| `scripts/dry_run.py`                | Engine-only CLI debate (no Streamlit).                         |
| `scripts/check_*.py`                | System / Ollama readiness probes.                              |
| `runs/<run_id>/`                    | Per-debate audit trail (transcript, run.json, memory, research, judge report). |
| `docs/research/agentic_research.md` | Phase 17 design doc for the v0.3 research DAG.                 |

See [PROJECT.md §5](PROJECT.md) for the canonical file tree.

## Personas & behaviors

Each agent's system prompt is composed at run time from a **role**
fragment (Offender / Defender), a **persona** fragment (voice / tone),
and a **behavior** fragment (procedural directives). Fragments live as
JSON files under `auto_debate/prompts/library/`.

| Persona | Voice |
| --- | --- |
| `neutral` | Calm, balanced, no overlay (default) |
| `professor` | Formal academic, citations and named studies |
| `socratic` | Probing, question-driven, exposes assumptions |
| `tabloid` | Punchy, sensational, headline-grabbing |
| `politician` | Rhetorical, audience-aware, frames around values |
| `comedian` | Dry, irreverent observational humour |

| Behavior | Effect |
| --- | --- |
| `standard` | No extra directives (default) |
| `steelman` | Restate opponent's strongest version before rebutting |
| `closing` | Final-statement summary used on the last round |
| `cite_evidence` | Name a specific source / Knowledge entry per turn |
| `concise` | Hard cap ~50 words, one main point only |
| `analytical` | 2–4 numbered points with framing + conclusion |

The sidebar's **Preset** selector picks a pre-vetted (offender, defender)
bundle — for example *Academic debate* pairs `professor + steelman` vs
`professor + cite_evidence`. Choosing **Custom** falls back to a single
persona/behavior pair shared by both agents. The UI shows a warning
when the selected combination is flagged as incompatible by
`prompts.check_compatibility` (e.g. `analytical + concise`).

**Add your own persona** by dropping a new `<name>.json` file under
`auto_debate/prompts/library/personas/` with the schema:

```json
{
  "name": "my_voice",
  "tone": "short tone description",
  "signature_phrases": ["optional", "stock phrases"],
  "extra_directives": ["short imperative directives, one per line"]
}
```

Behaviors use the same shape under `auto_debate/prompts/library/behaviors/` with a
`directives` array. The registry picks them up automatically on next
import — no code change required.

## Configuration

All knobs live in `Settings` (`auto_debate/config.py`) and are loaded
once at startup from process environment + `.env`. Real env vars win
over `.env` (twelve-factor). Validation problems are collected and
raised together as a single `ConfigError`.

| Variable                   | Default                  | Notes                                                                    |
| -------------------------- | ------------------------ | ------------------------------------------------------------------------ |
| `OLLAMA_HOST`              | `http://localhost:11434` | Must start with `http://` or `https://`.                                 |
| `MODEL_NAME`               | `gemma3:4b`              | Any model your Ollama server can serve.                                  |
| `MAX_TURNS`                | `10`                     | `>= 1`. Total turns across both agents.                                  |
| `TEMPERATURE`              | `0.8`                    | `(0, 2]`.                                                                |
| `TOP_P`                    | `0.95`                   | `(0, 1]`.                                                                |
| `WORD_LIMIT`               | `120`                    | `>= 30`. `num_predict` is capped at `word_limit * 2`.                    |
| `MEMORY_ENABLED`           | `false`                  | Per-agent persistent memory under `runs/<run_id>/`.                      |
| `WEB_RESEARCH_ENABLED`     | `false`                  | Pre-debate research (Phase 11). Requires memory.                         |
| `WEB_SEARCH_ADAPTER`       | `offline`                | `offline` (fixture) or `duckduckgo` (live, no key).                      |
| `STANCE_ANALYSIS_ENABLED`  | `false`                  | v0.3 four-stage research DAG. Requires memory + web research.            |
| `CLOSING_ROUND_ENABLED`    | `false`                  | Force final turn into the `closing` behavior.                            |
| `JUDGE_ENABLED`            | `false`                  | Run the 9-dimension judge after the final turn.                          |

The sidebar mirrors every flag, so you can flip them per-run without
editing `.env`. See [`.env.example`](.env.example) for the canonical
template.

## Memory, reflection & quality guards (Phases 10 / 12 / 13)

When `MEMORY_ENABLED` is on, each agent gets its own markdown file at
`runs/<run_id>/<agent>.md` with sections for **Stance**, **Strategy**,
**Knowledge**, and **Notes**. Before every turn a short `Reflector`
LLM pass produces a `MemoryUpdate` (strict JSON), which is applied to
the file via `apply_update`; the rendered memory is then injected into
the next prompt inside a `<MEMORY>…</MEMORY>` block.

After every committed turn the `quality` module computes:

- **Novelty** — n-gram overlap against the agent's own recent turns.
- **Adherence** — TF-IDF cosine similarity to the topic.
- **Loop score** — sliding-window repetition detector across both speakers.

Each turn carries its `TurnMetrics` into the UI as small chips under
the chat bubble. Per-turn wall-clock seconds (Phase 22) are stamped
alongside the metrics so you can see exactly how long each side took.

## Research pipeline

The research stage is layered. Both layers are gated by `Settings`
flags and silently no-op when off; both are best-effort and never
crash the debate.

**Legacy path (Phase 11)** — enabled by `WEB_RESEARCH_ENABLED`. The
`Researcher` runs a small fixed query expansion against the chosen
`SearchAdapter` (`offline` fixture or `duckduckgo`), summarises each
hit into 3 short tags, and writes the result into the agent's
**Knowledge** memory section. Search calls are SHA1-cached on disk
so reruns of the same topic are free.

**v0.3 four-stage DAG (Phases 18-21)** — enabled by
`STANCE_ANALYSIS_ENABLED`. Each stage is exactly one strict-JSON
LLM call (the filter is one call per hit) gated by stage-specific
delimiters; parser failures degrade to a deterministic fallback.

| Stage          | Module                          | Delimiter      | Output                                              |
| -------------- | ------------------------------- | -------------- | --------------------------------------------------- |
| 1. Stance      | `research/stance.py`            | `<STANCE>`     | `StanceBrief` — thesis + key claims + counterclaims + entities. |
| 2. Plan        | `research/planner.py`           | `<PLAN>`       | `QueryPlan` — entity-grounded queries, Jaccard dedup, 8-cap. |
| 3. Filter      | `research/filter.py`            | `<FILTER>`     | `FilteredHit` per hit — `keep` / `drop` + claim index. |
| 4. Synthesise  | `research/knowledge.py`         | `<KNOWLEDGE>`  | ≤ 10 attributed `KnowledgeEntry` bullets, ≤ 2 per claim. |

Citation hallucinations are blocked at two layers: source attribution
is rendered **deterministically** from the URL host + per-source-kind
template (the LLM never names an outlet), and a deterministic citation
linter rejects any entry whose quoted phrase is not present
verbatim in the matched search snippet. Per-agent worst-case budget:
`3 + N` LLM calls where `N ≤ max_queries × max_results_per_query`.

Each stage persists a per-agent JSON artefact for audit (see below).
The full design contract is [docs/research/agentic_research.md](docs/research/agentic_research.md).

## Run artefacts (Phase 22)

When `MEMORY_ENABLED` is on, every debate writes a self-contained
directory at `runs/<run_id>/` regardless of whether the run completed,
was Stop-clicked, or aborted on a mid-debate LLM error:

```
runs/20260428T120530Z/
├── auto_debate_transcript.md         # rendered transcript + quality metrics
├── run.json                          # topic, ISO timestamps, total + per-turn seconds,
│                                     #   settings snapshot, per-agent research summary
├── offender.md                       # agent memory (Stance / Strategy / Knowledge / Notes)
├── defender.md
├── research/                         # v0.3 audit trail (when stance flag is on)
│   ├── offender.plan.json
│   ├── offender.hits.json
│   ├── offender.drops.json
│   ├── offender.knowledge.json
│   └── …                             # same four files for the defender
├── report.json                       # judge scorecard (when JUDGE_ENABLED)
└── report.md                         # GitHub-renderable judge report
```

The Streamlit app surfaces the same data live: a collapsible
**🔎 Research summary** expander shows per-agent
`<query> → N hits → M kept` lines before the debate begins, and a
non-fatal `st.warning` fires whenever an agent finishes the research
stage with `kept_hits == 0`.

## Judge agent (optional)

Toggle **Enable judge** in the sidebar to run a third LLM pass after the
final turn. The judge sees only the topic and the rendered transcript
(no memory files, no system prompts) and emits a strict JSON scorecard
with one score per dimension Q1-Q9, one of which is persisted as
`runs/<run_id>/report.md`:

| # | Dimension | What it measures |
| --- | --- | --- |
| Q1 | On-topic adherence | Drift vs anchored to topic |
| Q2 | Logical connection | Each turn rebuts/builds on the previous |
| Q3 | Persona distinctiveness | Offender vs Defender voices |
| Q4 | Argument progression | New ground vs looping |
| Q5 | Language quality | Lexical variety, prose cleanliness |
| Q6 | Factual grounding | Concrete, named, checkable facts |
| Q7 | Fallacy frequency | 5 = few or none |
| Q8 | Structure & conclusion | Pacing and a real closing statement |
| Q9 | Safety / on-rails | Slurs, role breaks, PII, etc. |

Scores are 1–5 (excellent), an unweighted mean is shown as **Overall**,
and a one-paragraph headline verdict appears below the table. When
agent memory is enabled, the same report is persisted alongside each
run as `runs/<run_id>/report.json` (machine-readable) and
`runs/<run_id>/report.md` (GitHub-renderable). Malformed judge output, LLM errors, and
out-of-range scores degrade gracefully — the debate transcript is
unaffected.

The judge runs as a single extra LLM pass after the final turn and is
budgeted for ~700 tokens. On a CPU-only `gemma3:4b` it typically takes
**1–3 minutes** to return; the UI shows a spinner the whole time.

## Performance

Reference numbers from a local CPU run of `scripts/bench.py` against
`gemma3:4b` (Ollama default settings):

- Single offender turn: **~87 words / ~14 s ≈ 6 words/s** sustained.
- `num_predict` is automatically capped at `word_limit * 2` (236 by
  default) inside `llm.chat_options`, which prevents runaway generations.

GPU-accelerated runs typically move 3–10x faster; numbers vary by hardware
and model. Use `python scripts/bench.py [--turns N]` to measure on your
machine.

## Troubleshooting

| Symptom                                          | Likely cause / fix                                                                |
| ------------------------------------------------ | --------------------------------------------------------------------------------- |
| `MISSING_OLLAMA` from `check_ollama.py`          | Install Ollama from <https://ollama.com/download>.                                |
| `OLLAMA_DOWN` / "Ollama is not reachable"        | Run `ollama serve` (or launch the Ollama desktop app), then retry.                |
| `MODEL_MISSING` / `ModelNotFoundError`           | Pull the model: `ollama pull gemma3:4b` (substitute the model name shown).        |
| Streamlit asks for an email on first run         | Already disabled via `.streamlit/config.toml`; ensure that file ships with repo.  |
| Debate is unbearably slow                        | Try a smaller model (`gemma3:1b`) or run on a GPU-accelerated Ollama install.    |
| `streamlit run app.py` errors with `ConfigError` | Check your `.env` against `.env.example`; all numeric values must parse.          |
| Stop doesn't halt                                | The current generator finishes the in-flight HTTP chunk; halt is at next token.   |

## Development

Run the full lint + type-check + test suite in one command:

```powershell
./scripts/ci.ps1            # ruff check + format + mypy + pytest
./scripts/ci.ps1 -SkipMypy  # iterate on tests only
```

Manual single-turn debate from the CLI (no Streamlit):

```powershell
python scripts/dry_run.py "Remote work beats office work" --max-turns 1
```

## Roadmap

The build is tracked phase-by-phase. **v0.1.0** (Phases 0-8) shipped
the engine and Streamlit UI. **v0.2.x** (Phases 9-15) added composable
prompts, per-agent memory, pre-debate research, pre-turn reflection,
quality guards, the persona / behavior library, and the optional
judge. **v0.3** (Phases 16-22) reorganised the codebase into the
`auto_debate/` package and shipped the agentic research DAG plus
run-level persistence — the four research stages all live behind
`STANCE_ANALYSIS_ENABLED` and the audit trail is now complete. The
remaining v0.3.0 exit step is flipping the stance flag default to
`True` and cutting the tag.

Current CI baseline: **353 / 353 tests · ruff clean · mypy strict on
20 source files.** See [ROADMAP.md](ROADMAP.md) for the per-phase
deliverables checklist and exit criteria.

## License

[MIT](LICENSE).
