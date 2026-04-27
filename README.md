# Auto Debate

A local two-agent LLM debate app: two Gemma-3 personas (Offender vs Defender)
argue a user-supplied topic, streamed live in a Streamlit chat UI, powered by
[Ollama](https://ollama.com) running on your own machine.

> **Status:** scaffolding in progress. See [ROADMAP.md](ROADMAP.md) for the
> phase-by-phase execution plan and [PROJECT.md](PROJECT.md) for the spec.

## Quick start

```powershell
# 1. Clone, then run the one-shot installer (assumes Ollama is installed
#    and the server is running):
python scripts/install_defaults.py --yes

# 2. Activate the venv and launch the UI:
.\.venv\Scripts\Activate.ps1
streamlit run app.py
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

## Project layout

See [PROJECT.md §5](PROJECT.md) for the canonical file tree. The top-level
modules (filled in across Phases 2–6):

| File          | Role                                            |
| ------------- | ----------------------------------------------- |
| `config.py`   | Typed settings loader (env / `.env`).           |
| `prompts.py`  | Role system prompts and topic sanitization.    |
| `llm.py`      | Thin Ollama client wrapper.                     |
| `engine.py`   | Pure debate orchestration (no UI).              |
| `app.py`      | Streamlit UI.                                   |

## License

[MIT](LICENSE).
