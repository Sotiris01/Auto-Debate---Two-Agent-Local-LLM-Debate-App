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

from config import ConfigError, Settings, configure_logging, load_settings
from engine import DebateEngine
from llm import ModelNotFoundError, OllamaClient, OllamaUnavailableError

# --- constants --------------------------------------------------------------

_MODEL_CHOICES = ["gemma3:1b", "gemma3:4b", "gemma3:12b"]
_AVATARS = {"offender": "🗡️", "defender": "🛡️"}
_LABELS = {"offender": "Offender", "defender": "Defender"}


# --- page setup -------------------------------------------------------------

configure_logging()

st.set_page_config(
    page_title="Auto Debate",
    page_icon="🗣️",
    layout="wide",
    initial_sidebar_state="expanded",
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
        "messages": [],  # list[{"speaker": str, "content": str}]
        "running": False,
        "stop_flag": False,
        "topic": "",
        "topic_input_nonce": 0,  # bumped on Clear to force-reset the textbox
        "pending_topic": None,  # set by Start, consumed by the run block
        "ollama_status": None,  # ("ok"|"error", message)
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


# --- topic input + Start/Stop/Clear buttons --------------------------------
#
# All three buttons live inside an ``st.form`` so that the topic textbox
# value is committed on submit (no need for the user to press Enter first
# before clicking Start). Multiple ``st.form_submit_button`` are allowed
# per form; we read which one was clicked from their return values.

st.subheader("Topic")

with st.form("debate_form", clear_on_submit=False, border=False):
    topic = st.text_input(
        "Debate topic",
        max_chars=300,
        value=st.session_state.topic,
        placeholder="e.g. Remote work is better than office work",
        disabled=st.session_state.running,
        label_visibility="collapsed",
        key=f"topic_input_{st.session_state.topic_input_nonce}",
    )
    col_start, col_stop, col_reset = st.columns([1, 1, 1])
    with col_start:
        start_clicked = st.form_submit_button(
            "▶️ Start debate",
            type="primary",
            disabled=st.session_state.running,
            use_container_width=True,
        )
    with col_stop:
        stop_clicked = st.form_submit_button(
            "⏹️ Stop",
            disabled=not st.session_state.running,
            use_container_width=True,
        )
    with col_reset:
        reset_clicked = st.form_submit_button(
            "🧹 Clear",
            disabled=st.session_state.running,
            use_container_width=True,
        )

# Treat Start with an empty topic as a no-op (form-submit on empty input).
if start_clicked and not topic.strip():
    start_clicked = False

if stop_clicked:
    # Streamlit reruns the script on any button click; the live generator
    # is destroyed by that rerun, halting streaming within one token. The
    # button row above was rendered with stale ``running=True`` state, so
    # rerun once more to redraw it in the idle state.
    st.session_state.stop_flag = True
    st.session_state.running = False
    st.session_state.pending_topic = None
    st.rerun()

if reset_clicked:
    st.session_state.messages = []
    st.session_state.topic = ""
    st.session_state.last_error = None
    # Bumping the nonce changes the topic textbox's widget key, which
    # forces Streamlit to construct a fresh input on the next rerun and
    # honor ``value=""`` (otherwise the previously-typed value would be
    # retained as widget-owned state).
    st.session_state.topic_input_nonce += 1
    st.rerun()


# --- replay previously committed turns -------------------------------------

st.divider()


def _render_message(speaker: str, content: str) -> None:
    """Render a single chat bubble with a visible speaker label."""
    with st.chat_message(_LABELS[speaker], avatar=_AVATARS[speaker]):
        st.markdown(f"**{_LABELS[speaker]}**\n\n{content}")


for msg in st.session_state.messages:
    _render_message(msg["speaker"], msg["content"])

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
    except ConfigError as exc:
        st.session_state.last_error = f"Invalid input: {exc}"
        return

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
                header = f"**{_LABELS[speaker]}**\n\n"
                placeholder.markdown(header + " ▌")
                for token in engine.run_one_turn(speaker, stop_check=stop_check):  # type: ignore[arg-type]
                    buf.append(token)
                    placeholder.markdown(header + "".join(buf) + " ▌")
                final_text = "".join(buf)
                placeholder.markdown(
                    header + (final_text if final_text else "_(stopped)_"),
                )
            if final_text:
                st.session_state.messages.append(
                    {"speaker": speaker, "content": final_text},
                )
            if stop_check():
                break
            speaker = "defender" if speaker == "offender" else "offender"
    except OllamaUnavailableError as exc:
        st.session_state.last_error = f"Lost connection to Ollama mid-debate.\n\n```\n{exc}\n```"
    except ModelNotFoundError as exc:
        st.session_state.last_error = f"Model became unavailable: {exc}"


# --- start handler ----------------------------------------------------------
#
# Two-step pattern: the Start click only flips ``running`` and stashes the
# topic, then we ``st.rerun()``. On the next run the button row is rendered
# with the fresh ``running=True`` state (Stop enabled, Start disabled),
# *before* ``_run_debate`` blocks the script. That way a mid-debate Stop
# click actually hits an enabled button.

if start_clicked and topic.strip():
    st.session_state.messages = []
    st.session_state.last_error = None
    st.session_state.stop_flag = False
    st.session_state.running = True
    st.session_state.topic = topic.strip()
    st.session_state.pending_topic = topic.strip()
    st.rerun()

if st.session_state.running and st.session_state.pending_topic:
    topic_to_run = st.session_state.pending_topic
    st.session_state.pending_topic = None
    try:
        _run_debate(_runtime_settings(), topic_to_run)
    except Exception as exc:
        st.session_state.last_error = f"Unexpected error: {type(exc).__name__}: {exc}"
    finally:
        st.session_state.running = False
        st.session_state.stop_flag = False
    st.rerun()


# --- help expander ----------------------------------------------------------

with st.expander("How it works"):
    st.markdown(
        "- Two agents (**Offender** 🗡️ and **Defender** 🛡️) take turns "
        "responding to each other about your topic.\n"
        "- Tokens are streamed live from your local Ollama server — "
        "nothing leaves your machine.\n"
        "- Use **Max turns** to cap the debate length; **Stop** halts "
        "streaming within one token.\n"
        "- **Clear** wipes the transcript so you can start a new topic.",
    )
