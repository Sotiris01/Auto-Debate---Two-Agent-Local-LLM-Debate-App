# Auto Debate

A local two-agent LLM debate app: two Gemma-3 personas (Offender 🗡️ vs
Defender 🛡️) argue a user-supplied topic, streamed live in a Streamlit chat
UI, powered by [Ollama](https://ollama.com) running on your own machine.

> **Status:** v0.1.0 — feature-complete per
> [PROJECT.md §13](PROJECT.md). See [ROADMAP.md](ROADMAP.md) for the full
> phase-by-phase build log and [PROJECT.md](PROJECT.md) for the spec.

## What it is

- 100% local. No cloud calls, no telemetry. Your debate stays on your box.
- Two agents driven by a single Ollama chat model. The engine maintains
  two parallel chat histories and mirrors each turn into the opponent's
  history so that one model can play both sides without role confusion.
- Token-streamed UI with a typewriter cursor, working **Stop** button
  (halts within one token), and a one-click **Download transcript (.md)**
  export.

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
                ┌────────────┐
                │  app.py    │  Streamlit UI (sidebar, chat bubbles, Stop)
                │ (Phase 6)  │
                └─────┬──────┘
                      │ stream_chat tokens
                ┌─────▼──────┐
                │ engine.py  │  DebateEngine: two histories, mirroring trick,
                │ (Phase 5)  │  run_one_turn() generator, run() top-level loop
                └─────┬──────┘
        prompts.py    │    llm.py
        (Phase 3)     │    (Phase 4)
        ┌─────────────┴────────────┐
        │ build_system_prompt()    │ OllamaClient.stream_chat()
        │ sanitize_topic()         │ ensure_model_available()
        └────────────┬─────────────┘
                     │
                ┌────▼─────┐
                │ Ollama   │  Local server, default http://localhost:11434
                └──────────┘
```

The full diagram and message-flow examples live in
[PROJECT.md §4](PROJECT.md). Layer order is: **config → prompts → llm →
engine → app**, each one fully tested before the next is built.

## Project layout

> **Phase 16 (v0.3 track):** Source modules live under the
> `auto_debate/` package. The repository root keeps only `app.py` (the
> Streamlit entry point) and tooling.

| Path                              | Role                                              |
| --------------------------------- | ------------------------------------------------- |
| `app.py`                          | Streamlit UI (entry point).                       |
| `auto_debate/config.py`           | Typed settings loader (env / `.env`) + logging.   |
| `auto_debate/prompts/`            | Role system prompts, persona/behavior library.    |
| `auto_debate/llm.py`              | Thin Ollama client wrapper (mockable).            |
| `auto_debate/engine.py`           | Pure debate orchestration, no UI.                 |
| `auto_debate/memory.py`           | Per-agent memory store.                           |
| `auto_debate/reflection.py`       | Pre-turn reflection / memory updates.             |
| `auto_debate/quality.py`          | n-gram novelty / TF-IDF adherence / loop detect.  |
| `auto_debate/judge.py`            | 9-dimension judge / evaluator.                    |
| `auto_debate/research/`           | Pre-debate web research (Phase 11 + v0.3 stubs).  |
| `run.ps1`                         | Windows launcher (checks + Streamlit).            |
| `scripts/ci.ps1`                  | Lint + format + mypy + pytest, one command.       |
| `scripts/bench.py`                | Performance sanity benchmark.                     |
| `scripts/dry_run.py`              | Engine-only CLI debate (no Streamlit).            |
| `scripts/check_*.py`              | System / Ollama readiness probes.                 |

See [PROJECT.md §5](PROJECT.md) for the canonical file tree.

## Personas & behaviors

Each agent's system prompt is composed at run time from a **role**
fragment (Offender / Defender), a **persona** fragment (voice / tone),
and a **behavior** fragment (procedural directives). Fragments live as
JSON files under `prompts/library/`.

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
`prompts/library/personas/` with the schema:

```json
{
  "name": "my_voice",
  "tone": "short tone description",
  "signature_phrases": ["optional", "stock phrases"],
  "extra_directives": ["short imperative directives, one per line"]
}
```

Behaviors use the same shape under `prompts/library/behaviors/` with a
`directives` array. The registry picks them up automatically on next
import — no code change required.

## Judge agent (optional)

Toggle **Enable judge** in the sidebar to run a third LLM pass after the
final turn. The judge sees only the topic and the rendered transcript
(no memory files, no system prompts) and emits a strict JSON scorecard
with one score per dimension Q1-Q9, mirroring the rubric in
[report.md](report.md):

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
`runs/<run_id>/report.md` (GitHub-renderable, structurally identical to
the manual `report.md`). Malformed judge output, LLM errors, and
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

The build was executed in 8 phases (env bootstrap → scaffold → config →
prompts → llm → engine → UI → hardening → docs/release). See
[ROADMAP.md](ROADMAP.md) for the per-phase exit criteria and evidence.

## License

[MIT](LICENSE).
