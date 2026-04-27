# Auto Debate — Two‑Agent Local LLM Debate App

A local-first application where two LLM agents (Offender vs Defender) debate any
user-supplied topic. Models run locally through **Ollama** (Gemma family),
orchestrated in **Python**, with a **Streamlit** chat UI.

---

## 1. Goal

Give the user a single text field to drop a topic into (e.g. *"The impact of
remote work on productivity"*), press **Start Debate**, and watch two AI
personas argue in a chat-bubble UI with token-by-token streaming until the user
clicks **Stop Debate**.

---

## 2. Tech Stack (final picks)

| Layer | Choice | Why |
|---|---|---|
| LLM runtime | **Ollama** (local server on `http://localhost:11434`) | Local, no API key, simple HTTP API, native streaming. |
| Model | **`gemma3:4b`** (default) — swappable to `gemma3:1b` (low-VRAM) or `gemma3:12b` (better reasoning) | Gemma 3 supports a real `system` role; small enough for a single GPU/CPU; good instruction-following. |
| Client SDK | **`ollama`** (official Python lib, ≥ 0.6.x) | First-party, supports `stream=True`, `AsyncClient`, custom host. |
| Orchestration | Plain **Python 3.10+** with a small `DebateEngine` class (generator-based) | Project is too small to justify LangChain / LangGraph / CrewAI / AutoGen — they add weight, hidden prompts, and break Streamlit reruns. |
| UI | **Streamlit ≥ 1.39** (`st.chat_message`, `st.write_stream`, `st.session_state`, `st.fragment`) | Native chat primitives, real streaming via generators, no JS needed. |
| Concurrency | Synchronous streaming inside a Streamlit fragment + a **stop flag** in `st.session_state` | Threads + Streamlit are fragile; cooperative cancellation is enough. |
| Config | `.env` via `python-dotenv` (model name, host, max turns, temperature) | Simple, no secrets needed for local Ollama. |
| Packaging | `uv` or `pip` + `requirements.txt`; optional `pyproject.toml` | `uv` is fast and now the de-facto Python package manager. |

### What I deliberately rejected (and why)

- **LangChain / LlamaIndex** — overkill for a 2-agent ping-pong; their
  `ConversationChain` abstractions fight Streamlit's rerun model.
- **AutoGen / CrewAI** — designed for tool-using multi-agent workflows, way more
  surface area than needed; harder to stream into Streamlit cleanly.
- **`requests` direct calls to `/api/chat`** — works, but the official `ollama`
  package already wraps streaming and typing.
- **`asyncio` + `AsyncClient`** — Streamlit's script model makes async painful;
  the sync streaming generator + `st.write_stream` is the idiomatic path.
- **`threading.Thread` for the debate loop** — Streamlit session state is not
  thread-safe; use generator + per-rerun cancellation check instead.
- **WebSockets / FastAPI backend** — unnecessary complexity for a local app.
- **Gemma 2** — superseded; **Gemma 3** has better instruction-following and a
  proper system prompt slot.

---

## 3. User Flow (linear)

1. User starts Ollama (`ollama serve`) and pulls the model once
   (`ollama pull gemma3:4b`).
2. User runs `streamlit run app.py`.
3. Streamlit page shows: topic input, model selector (sidebar), **Start
   Debate** button, **Stop Debate** button, chat area.
4. User types a topic → clicks **Start Debate**.
5. Python builds two system prompts (Offender / Defender), seeds each agent's
   message history with the topic.
6. Loop, until `max_turns` is hit or `stop_flag` is set:
   - Offender turn → stream tokens into a red `st.chat_message("offender")`
     bubble; append the full reply to both histories (with role-swap).
   - Defender turn → stream tokens into a blue `st.chat_message("defender")`
     bubble; append the full reply to both histories.
7. **Stop Debate** flips `st.session_state.stop_flag = True`; the streaming
   generator checks the flag between chunks and returns early.

---

## 4. Architecture

```
┌────────────────────────────┐
│  Streamlit UI (app.py)     │
│  - topic input             │
│  - start / stop buttons    │
│  - st.chat_message bubbles │
│  - st.write_stream(...)    │
└─────────────┬──────────────┘
              │ calls
              ▼
┌────────────────────────────┐
│  DebateEngine (engine.py)  │
│  - build_system_prompts()  │
│  - run() -> generator of   │
│    (speaker, token) tuples │
│  - cooperative stop check  │
└─────────────┬──────────────┘
              │ uses
              ▼
┌────────────────────────────┐
│  OllamaClient (llm.py)     │
│  - thin wrapper around     │
│    ollama.chat(stream=True)│
└─────────────┬──────────────┘
              │ HTTP
              ▼
       Ollama server (localhost:11434)
              │
              ▼
          Gemma 3 model
```

### Key design rules

- **One generator, two speakers.** `DebateEngine.run()` yields `(role, chunk)`
  tuples. The UI layer routes each chunk to the correct chat bubble. This keeps
  orchestration logic out of the UI.
- **Shared transcript, mirrored histories.** Each agent sees its own messages as
  `assistant` and the opponent's as `user` (Ollama/Gemma chat format requires
  alternating user/assistant turns).
- **Stop = cooperative.** No thread kills. The generator polls
  `st.session_state.stop_flag` between yielded tokens.
- **No tools, no RAG, no memory store.** History lives in `st.session_state`
  for the session only.

---

## 5. Project Layout

```
auto_debate/
├── app.py                  # Streamlit entry point + UI wiring
├── engine.py               # DebateEngine class
├── llm.py                  # Ollama wrapper (stream_chat)
├── prompts.py              # OFFENDER_SYSTEM, DEFENDER_SYSTEM templates
├── config.py               # Settings dataclass loaded from env
├── requirements.txt
├── .env.example
├── README.md
└── PROJECT.md              # this file
```

---

## 6. System Prompts (initial drafts)

Both prompts must:

- pin the role,
- forbid breaking character,
- cap response length (~120 words) to keep the debate watchable,
- forbid markdown headings and bullet lists (cleaner in chat bubbles),
- forbid restating the topic verbatim,
- require addressing the opponent's *last* point.

```text
OFFENDER:
You are THE OFFENDER in a structured debate on the topic: "{topic}".
You argue strictly AGAINST the topic / criticize it.
Rules:
- Stay in character. Never agree with the Defender.
- Respond in <=120 words, plain prose, no bullet lists, no headers.
- Always attack the Defender's most recent argument before adding a new point.
- Be sharp but civil. No slurs, no personal attacks on the user.
- Do not mention that you are an AI or that this is a prompt.

DEFENDER:
You are THE DEFENDER in a structured debate on the topic: "{topic}".
You argue strictly IN FAVOR of the topic / defend it.
Rules: (same as above, mirrored)
```

The opening turn is triggered by sending the Offender a single user message:
`"Open the debate with your first argument."`

---

## 7. Streaming Pattern (the part that usually goes wrong)

```python
# llm.py
from ollama import Client
client = Client(host=settings.ollama_host)

def stream_chat(model, messages, options=None):
    for chunk in client.chat(model=model, messages=messages,
                             stream=True, options=options or {}):
        yield chunk["message"]["content"]
```

```python
# engine.py (sketch)
def run(self):
    speaker = "offender"
    for _ in range(self.max_turns):
        msgs = self._history_for(speaker)
        full = []
        for tok in stream_chat(self.model, msgs):
            if st.session_state.get("stop_flag"):
                return
            full.append(tok)
            yield speaker, tok
        self._commit_turn(speaker, "".join(full))
        speaker = "defender" if speaker == "offender" else "offender"
```

```python
# app.py (sketch of the streaming bit)
with st.chat_message(speaker, avatar="🗡️" if speaker == "offender" else "🛡️"):
    placeholder = st.empty()
    buf = ""
    for role, tok in engine.run_one_turn(speaker):
        buf += tok
        placeholder.markdown(buf)
```

> Use `placeholder.markdown(buf)` in a loop rather than `st.write_stream` when
> you need to interleave two speakers across reruns; `st.write_stream` is
> perfect for a single-speaker turn.

---

## 8. Configuration (`.env.example`)

```env
OLLAMA_HOST=http://localhost:11434
MODEL_NAME=gemma3:4b
MAX_TURNS=10
TEMPERATURE=0.8
TOP_P=0.95
WORD_LIMIT=120
```

---

## 9. Dependencies (`requirements.txt`)

```
streamlit>=1.39
ollama>=0.6
python-dotenv>=1.0
```

That's the whole list. No LangChain, no pydantic-ai, no autogen.

---

## 10. Setup & Run

```powershell
# 1. install Ollama from https://ollama.com/download and start it
ollama serve            # in one terminal
ollama pull gemma3:4b   # one-time

# 2. project setup
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env

# 3. run
streamlit run app.py
```

---

## 11. Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Agents converge / start agreeing | Strong system prompt + inject a turn-prefix like *"Rebut the previous point, then add a new attack."* every N turns. |
| Infinite / runaway generation | Hard `MAX_TURNS` cap + per-turn `num_predict` option in Ollama. |
| Stop button feels laggy | Check `stop_flag` between every yielded token (already in design). |
| Streamlit reruns wipe the loop mid-stream | Keep transcript in `st.session_state`; resume nothing — each click of Start begins fresh; Stop ends cleanly. |
| Gemma too small to argue coherently | Allow user to switch to `gemma3:12b` from sidebar. |
| Prompt injection from the topic field | The topic is only ever interpolated into the system prompt as plain text; never executed; cap topic length to 300 chars. |
| Model not pulled | On startup, call `ollama.list()` and show a friendly error with the exact `ollama pull` command. |

---

## 12. Out of Scope (v1)

- Saving / exporting transcripts.
- Judging / scoring the debate with a third agent.
- Web search or RAG.
- Multi-user / hosted deployment.
- Voice output.

These are good v2 candidates once the core loop is solid.

---

## 13. Definition of Done (v1)

- [ ] User can enter a topic and start a debate.
- [ ] Offender and Defender alternate with visibly different chat bubbles.
- [ ] Tokens stream in real time (no full-response blocking).
- [ ] **Stop Debate** halts generation within ~1 token.
- [ ] App degrades gracefully if Ollama is down or the model is missing.
- [ ] Single `streamlit run app.py` launches everything.
