"""
app.py — Streamlit UI for the Auto Debate two-agent app.

Part of the Auto Debate project. See PROJECT.md and ROADMAP.md.

Phase 6: thin presentation layer. The engine and the LLM client own the
real work; this module only wires them to chat bubbles, a topic input, and
Start/Stop buttons. Streaming is rendered into ``st.empty()`` placeholders
with a blinking cursor; on every Stop click Streamlit reruns the script,
which destroys the live generator and halts streaming within one token.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import streamlit as st

from config import ConfigError, Settings, load_settings
from engine import DebateEngine
from llm import ModelNotFoundError, OllamaClient, OllamaUnavailableError

# --- constants --------------------------------------------------------------

_MODEL_CHOICES = ["gemma3:1b", "gemma3:4b", "gemma3:12b"]
_AVATARS = {"offender": "🗡️", "defender": "🛡️"}
_LABELS = {"offender": "Offender", "defender": "Defender"}


# --- page setup -------------------------------------------------------------

st.set_page_config(
    page_title="Auto Debate",
    page_icon="🗣️",
    layout="wide",
)

st.title("🗣️ Auto Debate")
st.caption(
    "Two local LLM agents debate any topic you give them — one against, one for. "
    "Powered by Ollama, no cloud calls.",
)


# --- settings ---------------------------------------------------------------


@st.cache_data(show_spinner=False)
def _base_settings() -> Settings:
    return load_settings()


try:
    base_settings = _base_settings()
except ConfigError as exc:
    st.error(f"Configuration error:\n\n{exc}")
    st.stop()


# --- session state init -----------------------------------------------------


def _init_state() -> None:
    defaults: dict[str, Any] = {
        "messages": [],          # list[{"speaker": str, "content": str}]
        "running": False,
        "stop_flag": False,
        "engine": None,
        "topic": "",
        "ollama_status": None,   # ("ok"|"error", message)
        "last_error": None,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


_init_state()


# --- sidebar ----------------------------------------------------------------

with st.sidebar:
    st.header("⚙️ Settings")

    default_model = (
        base_settings.model_name
        if base_settings.model_name in _MODEL_CHOICES
        else _MODEL_CHOICES[1]
    )
    model_name = st.selectbox(
        "Model",
        _MODEL_CHOICES,
        index=_MODEL_CHOICES.index(default_model),
        disabled=st.session_state.running,
    )
    max_turns = st.slider(
        "Max turns (per side)",
        min_value=1,
        max_value=20,
        value=int(base_settings.max_turns),
        disabled=st.session_state.running,
    )
    temperature = st.slider(
        "Temperature",
        min_value=0.1,
        max_value=1.5,
        value=float(base_settings.temperature),
        step=0.05,
        disabled=st.session_state.running,
    )

    st.divider()

    if st.button("Check Ollama", disabled=st.session_state.running, use_container_width=True):
        try:
            probe_settings = replace(base_settings, model_name=model_name)
            OllamaClient(probe_settings).ensure_model_available()
        except OllamaUnavailableError as exc:
            st.session_state.ollama_status = ("error", str(exc))
        except ModelNotFoundError as exc:
            st.session_state.ollama_status = ("error", str(exc))
        else:
            st.session_state.ollama_status = ("ok", f"Ready — `{model_name}` available.")

    status = st.session_state.ollama_status
    if status is not None:
        kind, msg = status
        if kind == "ok":
            st.success(msg)
        else:
            st.error(msg)


# --- runtime settings (per-run, derived from sidebar) -----------------------


def _runtime_settings() -> Settings:
    return replace(
        base_settings,
        model_name=model_name,
        max_turns=int(max_turns),
        temperature=float(temperature),
    )


# --- topic input + Start/Stop buttons --------------------------------------

st.subheader("Topic")
topic = st.text_input(
    "Debate topic",
    max_chars=300,
    value=st.session_state.topic,
    placeholder="e.g. Remote work is better than office work",
    disabled=st.session_state.running,
    label_visibility="collapsed",
)

col_start, col_stop, col_reset = st.columns([1, 1, 1])
with col_start:
    start_clicked = st.button(
        "▶️ Start debate",
        type="primary",
        disabled=st.session_state.running or not topic.strip(),
        use_container_width=True,
    )
with col_stop:
    stop_clicked = st.button(
        "⏹️ Stop",
        disabled=not st.session_state.running,
        use_container_width=True,
    )
with col_reset:
    reset_clicked = st.button(
        "🧹 Clear",
        disabled=st.session_state.running,
        use_container_width=True,
    )

if stop_clicked:
    # Streamlit reruns the script on any button click; the live generator
    # is destroyed by that rerun, halting streaming within one token.
    st.session_state.stop_flag = True
    st.session_state.running = False

if reset_clicked:
    st.session_state.messages = []
    st.session_state.engine = None
    st.session_state.topic = ""
    st.session_state.last_error = None
    st.rerun()


# --- replay previously committed turns -------------------------------------

st.divider()

for msg in st.session_state.messages:
    speaker = msg["speaker"]
    with st.chat_message(_LABELS[speaker], avatar=_AVATARS[speaker]):
        st.markdown(msg["content"])

if st.session_state.last_error is not None:
    st.error(st.session_state.last_error)


# --- live streaming ---------------------------------------------------------


def _run_debate(settings: Settings, topic_text: str) -> None:
    """Drive a full debate, rendering tokens into chat-message placeholders."""
    try:
        client = OllamaClient(settings)
        client.ensure_model_available()
        engine = DebateEngine(settings, client, topic_text)
    except OllamaUnavailableError as exc:
        st.session_state.last_error = (
            f"Ollama is not reachable.\n\n```\n{exc}\n```\n"
            "Start it (e.g. run `ollama serve` or launch the Ollama app) and try again."
        )
        return
    except ModelNotFoundError as exc:
        st.session_state.last_error = (
            f"Model is not available.\n\n```\n{exc}\n```\n"
            f"Pull it with: `ollama pull {exc.model_name}`"
        )
        return
    except (ValueError, ConfigError) as exc:
        st.session_state.last_error = f"Invalid input: {exc}"
        return

    st.session_state.engine = engine

    def stop_check() -> bool:
        return bool(st.session_state.get("stop_flag"))

    speaker: str = "offender"
    try:
        for _ in range(settings.max_turns * 2):
            if stop_check():
                break
            with st.chat_message(_LABELS[speaker], avatar=_AVATARS[speaker]):
                placeholder = st.empty()
                buf: list[str] = []
                for token in engine.run_one_turn(speaker, stop_check=stop_check):  # type: ignore[arg-type]
                    buf.append(token)
                    placeholder.markdown("".join(buf) + " ▌")
                final_text = "".join(buf)
                placeholder.markdown(final_text if final_text else "_(stopped)_")
            if final_text:
                st.session_state.messages.append(
                    {"speaker": speaker, "content": final_text},
                )
            if stop_check():
                break
            speaker = "defender" if speaker == "offender" else "offender"
    except OllamaUnavailableError as exc:
        st.session_state.last_error = (
            f"Lost connection to Ollama mid-debate.\n\n```\n{exc}\n```"
        )
    except ModelNotFoundError as exc:
        st.session_state.last_error = f"Model became unavailable: {exc}"


if start_clicked and topic.strip():
    st.session_state.messages = []
    st.session_state.last_error = None
    st.session_state.stop_flag = False
    st.session_state.running = True
    st.session_state.topic = topic.strip()
    try:
        _run_debate(_runtime_settings(), topic.strip())
    finally:
        st.session_state.running = False
        st.session_state.stop_flag = False
    st.rerun()


# --- help expander ----------------------------------------------------------

with st.expander("How it works"):
    st.markdown(
        "- **Offender** argues *against* the topic; **Defender** argues *for* it.\n"
        "- Each agent is the same local Gemma model on Ollama with a different "
        "system prompt and its own message history.\n"
        "- After each turn the assistant message is mirrored as a `user` "
        "message in the opponent's history (the alternating-role trick).\n"
        "- Press **Stop** at any time — Streamlit reruns the script, which "
        "destroys the live generator and halts streaming within one token.",
    )

