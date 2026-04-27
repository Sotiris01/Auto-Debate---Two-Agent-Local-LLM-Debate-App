# Auto Debate — Implementation Roadmap

This roadmap is the execution plan for the project described in
[PROJECT.md](PROJECT.md). It is split into **8 phases**, each with concrete
steps, file-level deliverables, and an explicit "done when…" checklist.

The order is deliberate: we first guarantee the **environment is ready**, then
**scaffold every file empty**, then **fill in layers from the bottom up**
(config → llm → prompts → engine → UI), then harden and ship.

> Convention: `[script]` = something that runs from a terminal, `[file]` =
> something that gets created/edited, `[manual]` = a one-time human action.

---

## Phase 0 — System & Environment Bootstrap

**Goal:** Before a single line of app code is written, prove the machine can
actually run the project, and produce a working virtual environment with all
dependencies pinned.

### Step 0.1 — Hardware / OS spec check `[script]`

Create `scripts/check_system.py`. It must report and gate on:

- **OS & arch** — `platform.system()`, `platform.machine()`. Warn if not
  Windows / Linux / macOS on x86_64 or arm64.
- **Python version** — require `>= 3.10` (we use PEP 604 unions, `match`,
  modern typing). Hard-fail otherwise.
- **CPU cores** — `os.cpu_count()`. Warn if `< 4` (Gemma 3:4b will be slow).
- **RAM** — via `psutil.virtual_memory().total`. Warn if `< 8 GB`, hard-fail
  if `< 4 GB`.
- **Free disk** — `shutil.disk_usage(".")`. Warn if `< 10 GB` free
  (Gemma 3:4b ~3.3 GB, plus venv).
- **GPU detection (optional)** — try `nvidia-smi` (NVIDIA), `rocminfo` (AMD),
  detect Apple Silicon. Print which Ollama backend will be used.
- **Network reachability** — `HEAD https://ollama.com` and
  `HEAD https://registry.ollama.ai`. Soft warn on failure.

Output: a colored summary table and an exit code (`0` ok, `1` warning, `2`
fatal).

**Done when:** running `python scripts/check_system.py` on a fresh clone
prints a green "System OK" or a clear actionable message.

### Step 0.2 — Ollama presence check `[script]`

Add to `scripts/check_ollama.py`:

- **API-first probe.** Try `GET {OLLAMA_HOST}/api/tags` (timeout 2 s). A
  reachable server proves Ollama is installed *and* running, independent of
  the current shell's `PATH`.
- **Binary fallback only when the API is unreachable.** Use
  `shutil.which("ollama")` plus Windows-installer fallback paths
  (`%LOCALAPPDATA%\Programs\Ollama\ollama.exe`, `%ProgramFiles%\Ollama\ollama.exe`)
  because the Windows installer updates `PATH` only for *new* shells, so an
  already-open terminal would otherwise falsely report `MISSING_OLLAMA`.
- If binary missing → print the OS-specific install hint
  (Windows: winget cmd, macOS: brew/dmg, Linux: curl one-liner).
- If binary found but API unreachable → instruct the user to run
  `ollama serve` (or launch the Windows app).
- If API reachable but `MODEL_NAME` (default `gemma3:4b`) not in the list →
  print exactly `ollama pull gemma3:4b`.
- **Do not auto-pull.** Pulling is several GB; it must be a conscious user
  action.

**Done when:** the script ends with one of four states clearly printed:
`MISSING_OLLAMA`, `OLLAMA_DOWN`, `MODEL_MISSING`, or `READY`.

### Step 0.3 — Virtualenv bootstrap `[script]`

Create `scripts/bootstrap_env.py` and a thin `scripts/bootstrap.ps1` /
`scripts/bootstrap.sh` wrapper. It must:

1. Detect if `.venv/` exists. If not, run `python -m venv .venv`.
2. Resolve the venv's Python executable (Windows: `.venv\Scripts\python.exe`,
   POSIX: `.venv/bin/python`).
3. Upgrade pip: `python -m pip install --upgrade pip`.
4. Install from `requirements.txt` (created in Step 0.4) **only if** the
   installed package versions don't already satisfy the pins (use
   `pip install --dry-run` parsing or just always `pip install -r`).
5. Print a "next step" hint telling the user how to activate the venv on
   their shell.

**Done when:** running the wrapper on a fresh clone produces a venv with all
deps installed and prints the activation command.

### Step 0.4 — Requirements & lock files `[file]`

Create:

- `requirements.txt` — runtime pins:
  ```
  streamlit>=1.39,<2
  ollama>=0.6,<1
  python-dotenv>=1.0,<2
  psutil>=5.9
  ```
- `requirements-dev.txt` — dev tooling: `ruff`, `pytest`, `pytest-mock`,
  `mypy` (optional).
- `.python-version` — `3.11` (recommended interpreter).

**Done when:** `pip install -r requirements.txt` in a clean venv succeeds.

### Step 0.5 — Repo hygiene files `[file]`

- `.gitignore` — `.venv/`, `__pycache__/`, `.env`, `*.log`, `.streamlit/secrets.toml`.
- `.editorconfig` — 4-space indent, LF, UTF-8.
- `.env.example` — exactly as specified in PROJECT.md §8.
- `LICENSE` — MIT (placeholder).

**Done when:** `git status` on a fresh clone after running bootstrap is clean.

### Step 0.6 — One-shot installer `[script]`

Create `scripts/install_defaults.py` that orchestrates Steps 0.1, 0.3, and 0.2
in sequence and installs whatever can be installed safely without elevation:

1. Run `check_system.py` — fail only on FATAL, continue on warnings.
2. Run `bootstrap_env.py` — create `.venv` and install Python deps if absent.
   Pass `--dev` through with `--dev`.
3. Run `check_ollama.py` (in-process via import) — get the current state.
4. If state is `MODEL_MISSING`: prompt the user (or auto-confirm with
   `--yes` / `-y`) and run `ollama pull <MODEL_NAME>`. Use the absolute path
   resolved by `find_ollama_binary()` so the pull works even on stale shells.
5. If state is `MISSING_OLLAMA` or `OLLAMA_DOWN`: print remediation and exit
   with code 1 — the script never installs the Ollama binary itself and
   never starts the server.
6. Re-probe after the pull and exit `0` only when the final state is `READY`.

Flags: `--yes/-y`, `--dev`, `--skip-system`, `--skip-bootstrap`.

**Done when:** `python scripts/install_defaults.py --yes` on a freshly
bootstrapped machine (Ollama already installed and running) ends with
`READY` and exit code 0.

### Phase 0 Exit Criteria

- [x] `python scripts/check_system.py` → green (warns on missing GPU — expected on CPU-only machine).
- [x] `python scripts/check_ollama.py` correctly detects Ollama state via the `/api/tags` probe (API-first gating; binary check is fallback only).
- [x] Bootstrap script produces a working `.venv` end-to-end on Windows (`streamlit`, `ollama`, `python-dotenv`, `psutil` installed).
- [x] All hygiene files created (`.gitignore`, `.editorconfig`, `.env.example`, `LICENSE`, `requirements*.txt`, `.python-version`). Commit pending Phase 1 Step 1.4.
- [x] `python scripts/install_defaults.py --yes` runs all Phase-0 checks and pulls `gemma3:4b` automatically when missing, ending with `READY`.

> **Status: Phase 0 complete.** Move to Phase 1.

---

## Phase 1 — Empty File Scaffolding

**Goal:** Every file from PROJECT.md §5 exists on disk, with a header comment
explaining its purpose and TODO markers for the symbols that will live there.
After this phase the project **imports cleanly** but **does nothing**.

### Step 1.1 — Create the package skeleton `[file]`

Create the following files, **each containing only a docstring and `# TODO`
stubs** — no logic yet.

```
auto_debate/
├── app.py
├── engine.py
├── llm.py
├── prompts.py
├── config.py
├── scripts/
│   ├── __init__.py
│   ├── check_system.py
│   ├── check_ollama.py
│   └── bootstrap_env.py
├── tests/
│   ├── __init__.py
│   ├── test_config.py
│   ├── test_prompts.py
│   ├── test_engine.py
│   └── test_llm.py
├── requirements.txt
├── requirements-dev.txt
├── .env.example
├── .gitignore
├── README.md
├── PROJECT.md         # already exists
└── ROADMAP.md         # already exists
```

### Step 1.2 — File header template

Every `.py` file starts with:

```python
"""
<module name> — <one-line purpose>.

Part of the Auto Debate project. See PROJECT.md and ROADMAP.md.
"""
# TODO(phase-N): <what gets added here>
```

Concrete planned contents (still empty in Phase 1):

| File           | Will contain (later phases)                                                        |
| -------------- | ---------------------------------------------------------------------------------- |
| `config.py`  | `Settings` dataclass, `load_settings()`                                        |
| `llm.py`     | `OllamaClient`, `stream_chat()`, `ensure_model_available()`                  |
| `prompts.py` | `OFFENDER_SYSTEM`, `DEFENDER_SYSTEM`, `build_system_prompt(role, topic)`     |
| `engine.py`  | `DebateTurn` dataclass, `DebateEngine` class with `run_one_turn()` generator |
| `app.py`     | Streamlit page, sidebar, start/stop buttons, chat-bubble loop                      |

### Step 1.3 — Smoke import test `[script]`

Add `tests/test_smoke.py` that does `import config, llm, prompts, engine` and
asserts `True`. This guarantees the empty scaffolding is at least syntactically
valid Python.

### Step 1.4 first commit `[manual]`

- first compit to `main` with all files empty but present, and the smoke test.
- https://github.com/Sotiris01/Auto-Debate---Two-Agent-Local-LLM-Debate-App.git
- sotiris.mp@gmail.com

> Local first commit landed on `main` as `[P1] scaffold: empty modules +
> smoke test` (28 files, identity `sotiris.mp@gmail.com`). Pushing to the
> GitHub remote is left as a conscious manual action.

### Phase 1 Exit Criteria

- [x] `pytest -q tests/test_smoke.py` passes (1 passed in 0.06s).
- [x] `streamlit run app.py` launches and shows a blank page (no crash) —
  verified headless on port 8599.
- [x] No module has implementation logic yet — only docstrings & TODOs.

> **Status: Phase 1 complete.** Move to Phase 2.

---

## Phase 2 — Configuration Layer (`config.py`)

**Goal:** A single, typed source of truth for all runtime knobs, loaded once.

### Step 2.1 — Define `Settings`

A `@dataclass(frozen=True)` with fields matching `.env.example`:
`ollama_host: str`, `model_name: str`, `max_turns: int`, `temperature: float`,
`top_p: float`, `word_limit: int`.

### Step 2.2 — Implement `load_settings()`

- Use `python-dotenv` to load `.env` if present.
- Read each var with `os.getenv` + a typed default.
- Validate: `max_turns >= 1`, `0 < temperature <= 2`, `0 < top_p <= 1`,
  `word_limit >= 30`, `ollama_host` starts with `http`.
- Raise a single `ConfigError` with all problems concatenated.

### Step 2.3 — Tests `tests/test_config.py`

- Default values when env empty.
- Override via env var.
- Validation errors for each bad field.

### Phase 2 Exit Criteria

- [x] `from config import load_settings; load_settings()` returns a valid
  `Settings` on a clean `.env` (verified — defaults match `.env.example`).
- [x] All validation tests pass (`pytest -q tests/test_config.py` →
  16 passed in 0.20s).

> **Status: Phase 2 complete.** Move to Phase 3.

---

## Phase 3 — Prompt Layer (`prompts.py`)

**Goal:** Centralized, testable prompt construction. UI and engine never write
prompt strings inline.

### Step 3.1 — Constants

`OFFENDER_SYSTEM_TEMPLATE` and `DEFENDER_SYSTEM_TEMPLATE` — the exact
strings from PROJECT.md §6, with `{topic}` and `{word_limit}` placeholders.

### Step 3.2 — `build_system_prompt(role: Literal["offender","defender"], topic: str, word_limit: int) -> str`

- Sanitize `topic`: strip, collapse whitespace, truncate to 300 chars, reject
  if empty after stripping.
- Format the right template.

### Step 3.3 — `OPENING_USER_MESSAGE`

Constant string used to kick off the offender on turn 1: `"Open the debate with your first argument."`

### Step 3.4 — Tests `tests/test_prompts.py`

- Each role produces a string containing the topic.
- Empty / whitespace-only topic → `ValueError`.
- Topic > 300 chars is truncated.
- The two role prompts differ.

### Phase 3 Exit Criteria

- [ ] `build_system_prompt` covered by tests, all green.

---

## Phase 4 — LLM Layer (`llm.py`)

**Goal:** A thin, mockable wrapper around Ollama. **No business logic here.**

### Step 4.1 — `OllamaClient`

Class wrapping `ollama.Client(host=...)`, constructed from `Settings`.

### Step 4.2 — `ensure_model_available(model_name: str) -> None`

- Call `client.list()`, check if `model_name` is present.
- If missing: raise `ModelNotFoundError(model_name)` with the exact
  `ollama pull` command in the message. **Do not auto-pull.**

### Step 4.3 — `stream_chat(messages, *, options) -> Iterator[str]`

- Calls `client.chat(model=..., messages=..., stream=True, options=...)`.
- Yields `chunk["message"]["content"]` only.
- Wraps connection errors in `OllamaUnavailableError` with a friendly message.

### Step 4.4 — Options builder

Helper `chat_options(settings) -> dict` that returns
`{"temperature": ..., "top_p": ..., "num_predict": <derived from word_limit>}`.

### Step 4.5 — Tests `tests/test_llm.py`

Use `pytest-mock` to patch `ollama.Client`. Verify:

- `ensure_model_available` raises when list is empty.
- `stream_chat` yields the right strings from a fake stream.
- Connection refused → `OllamaUnavailableError`.

### Phase 4 Exit Criteria

- [ ] All tests green with mocks (no live Ollama needed for CI).
- [ ] One manual smoke run against real Ollama succeeds.

---

## Phase 5 — Debate Engine (`engine.py`)

**Goal:** Pure orchestration. Knows nothing about Streamlit. Drivable from a
plain Python script.

### Step 5.1 — `DebateTurn` dataclass

`speaker: Literal["offender","defender"]`, `content: str`, `index: int`.

### Step 5.2 — `DebateEngine.__init__(settings, llm_client, topic)`

- Validate topic via `prompts.build_system_prompt`.
- Build two message histories `_offender_msgs`, `_defender_msgs`, each
  starting with their respective system message.
- Seed the offender with the `OPENING_USER_MESSAGE` user turn.

### Step 5.3 — `run_one_turn(speaker) -> Iterator[str]` (generator)

- Picks the right history.
- Streams tokens via `llm_client.stream_chat(...)`.
- Yields each token to the caller.
- After the stream ends, calls `_commit_turn(speaker, full_text)`:
  - Appends `{"role": "assistant", "content": full_text}` to the speaker's
    own history.
  - Appends `{"role": "user", "content": full_text}` to the opponent's
    history (mirroring trick — required by chat models that need alternating
    roles).

### Step 5.4 — `run(stop_check: Callable[[], bool]) -> Iterator[Tuple[str, str]]`

Top-level loop that yields `(speaker, token)` for `max_turns * 2` turns,
checking `stop_check()` between every token and returning early on True.

### Step 5.5 — Transcript helpers

- `transcript() -> list[DebateTurn]` returns the committed history.
- `to_markdown()` for export (used in Phase 8).

### Step 5.6 — Tests `tests/test_engine.py`

With a mocked `llm_client` that yields a fixed list of tokens:

- After 1 turn, offender history has 2 messages, defender history has 2
  (system + user-mirror).
- Stop callback returning `True` halts within one token.
- Roles always alternate.

### Phase 5 Exit Criteria

- [ ] A small `python -m scripts.dry_run` (added in this phase) prints a
  full debate to stdout with no Streamlit involved.

---

## Phase 6 — Streamlit UI (`app.py`)

**Goal:** Minimal, responsive UI that wires the engine to chat bubbles with
real streaming and a working Stop button.

### Step 6.1 — Page setup

- `st.set_page_config(page_title="Auto Debate", page_icon="🗣️", layout="wide")`.
- Title, short subtitle.

### Step 6.2 — Sidebar

- Model selector (`gemma3:1b` / `gemma3:4b` / `gemma3:12b`).
- Max turns slider (1–20).
- Temperature slider (0.1–1.5).
- "Check Ollama" button → calls `ensure_model_available`, shows status badge.

### Step 6.3 — Session state init

Initialize on first run: `messages=[]`, `running=False`, `stop_flag=False`,
`engine=None`, `topic=""`.

### Step 6.4 — Topic input + Start / Stop buttons

- `st.text_input("Debate topic", max_chars=300)`.
- Two `st.button`s side-by-side. Disable Start while `running`. Disable Stop
  while not `running`.

### Step 6.5 — Replay loop (top of page on every rerun)

Iterate `st.session_state.messages` and render each in
`st.chat_message(speaker, avatar=...)`.

### Step 6.6 — Live streaming loop

When Start is pressed:

1. Set `running=True`, `stop_flag=False`.
2. Build engine via `DebateEngine(...)`.
3. For each turn, open `st.chat_message(speaker, avatar=...)`, create a
   `placeholder = st.empty()`, accumulate `buf`, update via
   `placeholder.markdown(buf + "▌")` for cursor effect.
4. After each turn append a `{role, content}` dict to
   `st.session_state.messages` so it survives reruns.
5. Between every token check `st.session_state.stop_flag`; break if set.
6. Finally set `running=False` and `st.rerun()`.

### Step 6.7 — Stop button wiring

`if stop_clicked: st.session_state.stop_flag = True`. The currently running
generator (running on the same script execution) sees it on the next token.

### Step 6.8 — Error UI

Catch `OllamaUnavailableError` and `ModelNotFoundError`; render `st.error`
with the exact remediation command.

### Phase 6 Exit Criteria

- [ ] Full debate runs end-to-end with visible streaming.
- [ ] Stop halts within one token.
- [ ] Refreshing the page resets cleanly.
- [ ] Errors from a stopped Ollama server show a helpful message, not a
  stack trace.

---

## Phase 7 — Hardening, QA & Polish

### Step 7.1 — Logging

Add a small `logging` config in `config.py`. Engine logs every committed turn
at INFO; LLM layer logs request/response sizes at DEBUG. Logs go to
`logs/auto_debate.log` (rotating, 1 MB × 3).

### Step 7.2 — Linting & formatting

- `ruff check .` and `ruff format .` clean.
- Add `pyproject.toml` `[tool.ruff]` config (line-length 100).

### Step 7.3 — Type checking (optional)

`mypy --strict auto_debate/` clean on `config.py`, `prompts.py`, `llm.py`,
`engine.py`. UI module excluded (Streamlit's stubs are noisy).

### Step 7.4 — Manual QA matrix

Run through each scenario and tick off:

- [ ] Ollama not installed.
- [ ] Ollama installed but not running.
- [ ] Model not pulled.
- [ ] Topic empty / 1 char / 301 chars.
- [ ] Stop pressed mid-first-token.
- [ ] Stop pressed mid-debate.
- [ ] Max turns reached naturally.
- [ ] Switching model in sidebar mid-session.
- [ ] Reload browser tab while debate is running.

### Step 7.5 — Performance sanity

- Measure tokens/sec on `gemma3:4b`. Document in README.
- Verify `num_predict` cap prevents runaway generations.

### Phase 7 Exit Criteria

- [ ] All QA matrix items pass.
- [ ] Lint + tests green in one command (`scripts/ci.ps1`).

---

## Phase 8 — Documentation & Release

### Step 8.1 — README.md

Sections: What it is, 30-second demo GIF, Requirements, Install, Run,
Troubleshooting, Architecture diagram (copy from PROJECT.md), Roadmap link.

### Step 8.2 — In-app help

A collapsible `st.expander("How it works")` on the main page summarizing the
two-agent setup and linking to the GitHub repo.

### Step 8.3 — Transcript export (stretch)

Button "Download transcript (.md)" that calls `engine.to_markdown()` and
serves it via `st.download_button`.

### Step 8.4 — Tagging

`git tag v0.1.0` once Definition of Done in PROJECT.md §13 is fully checked.

### Phase 8 Exit Criteria

- [ ] All boxes in PROJECT.md §13 ticked.
- [ ] README renders correctly on GitHub.
- [ ] `v0.1.0` tag pushed.

---

## Cross-Phase Conventions

- **Branch per phase:** `phase/0-bootstrap`, `phase/1-scaffold`, …, merged to
  `main` only when the phase exit criteria are green.
- **Commit prefix:** `[P3]` for Phase 3 commits, etc.
- **No phase skipping.** A phase that fails its exit criteria blocks the next
  one.
- **Tests live next to behavior.** New logic ships with at least one test in
  the same PR.

---

## Quick Phase Map

| Phase | Theme                | Primary Output                          |
| ----- | -------------------- | --------------------------------------- |
| 0     | Environment & sanity | bootstrap scripts, working venv         |
| 1     | Scaffolding          | every file empty but importable         |
| 2     | Config               | `config.py` typed + tested            |
| 3     | Prompts              | `prompts.py` typed + tested           |
| 4     | LLM wrapper          | `llm.py` typed + mocked tests         |
| 5     | Engine               | `engine.py` runs a debate via stdout  |
| 6     | UI                   | `app.py` runs the debate in Streamlit |
| 7     | Hardening            | logging, lint, QA matrix                |
| 8     | Docs & release       | README, v0.1.0 tag                      |
