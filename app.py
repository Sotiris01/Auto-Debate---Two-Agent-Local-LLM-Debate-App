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
from datetime import datetime, timezone
from typing import Any, cast

import streamlit as st

from auto_debate.config import ConfigError, Settings, configure_logging, load_settings
from auto_debate.engine import DebateEngine
from auto_debate.judge import Judge, JudgeReport, render_report_markdown, save_report
from auto_debate.llm import ModelNotFoundError, OllamaClient, OllamaUnavailableError
from auto_debate.memory import AgentMemory, MemoryStore
from auto_debate.prompts import (
    DEFAULT_BEHAVIOR_NAME,
    DEFAULT_PERSONA_NAME,
    NEUTRAL_PERSONA,
    STANDARD_BEHAVIOR,
    check_compatibility,
    list_fragments,
    list_presets,
    load_behavior,
    load_persona,
    preset_by_name,
)
from auto_debate.reflection import Reflector
from auto_debate.research import (
    DuckDuckGoAdapter,
    OfflineFixtureAdapter,
    Researcher,
    SearchAdapter,
)


def _build_search_adapter(name: str) -> SearchAdapter:
    """Return a :class:`SearchAdapter` instance for the configured name."""
    if name == "duckduckgo":
        return DuckDuckGoAdapter()
    return OfflineFixtureAdapter()


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
        "run_id": None,  # str | None — set when a debate starts
        "memory_snapshot": {},  # dict[agent_id, AgentMemory]
        "judge_report": None,  # JudgeReport | None — Phase 15
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
    st.caption("Prompt composition (Phase 9)")

    _preset_objs = list_presets()
    _preset_choices = ["Custom", *(p.name for p in _preset_objs)]
    preset_choice = st.selectbox(
        "Preset",
        _preset_choices,
        index=0,
        disabled=st.session_state.running,
        help=(
            "Pre-vetted (offender, defender) bundles. 'Custom' uses the "
            "single Persona + Behavior pair selected below for both agents."
        ),
    )
    _selected_preset = preset_by_name(preset_choice) if preset_choice != "Custom" else None
    if _selected_preset is not None:
        st.caption(f"_{_selected_preset.description}_")

    _persona_choices = list_fragments("personas") or [DEFAULT_PERSONA_NAME]
    _persona_default_idx = (
        _persona_choices.index(DEFAULT_PERSONA_NAME)
        if DEFAULT_PERSONA_NAME in _persona_choices
        else 0
    )
    persona_name = st.selectbox(
        "Persona",
        _persona_choices,
        index=_persona_default_idx,
        disabled=st.session_state.running or _selected_preset is not None,
        help="Voice / tone overlay applied on top of the role.",
    )

    _behavior_choices = list_fragments("behaviors") or [DEFAULT_BEHAVIOR_NAME]
    _behavior_default_idx = (
        _behavior_choices.index(DEFAULT_BEHAVIOR_NAME)
        if DEFAULT_BEHAVIOR_NAME in _behavior_choices
        else 0
    )
    behavior_name = st.selectbox(
        "Behavior",
        _behavior_choices,
        index=_behavior_default_idx,
        disabled=st.session_state.running or _selected_preset is not None,
        help="Procedural directives layered after the persona.",
    )

    # When a preset is active its persona/behavior pair takes over for the
    # offender; the defender override happens later in `_run_debate`.
    if _selected_preset is not None:
        offender_persona_name = _selected_preset.offender.persona
        offender_behavior_name = _selected_preset.offender.behavior
        defender_persona_name = _selected_preset.defender.persona
        defender_behavior_name = _selected_preset.defender.behavior
    else:
        offender_persona_name = persona_name
        offender_behavior_name = behavior_name
        defender_persona_name = persona_name
        defender_behavior_name = behavior_name

    _compat_warnings = check_compatibility(
        persona=offender_persona_name,
        behavior=offender_behavior_name,
        other_persona=defender_persona_name,
        other_behavior=defender_behavior_name,
    )
    for _msg in _compat_warnings:
        st.warning(_msg, icon="⚠️")

    memory_enabled = st.toggle(
        "Enable agent memory",
        value=bool(base_settings.memory_enabled),
        disabled=st.session_state.running,
        help=(
            "Persist a structured memory document per agent under "
            "`runs/<run_id>/memory/`. Phase 10 mechanism only \u2014 the memory "
            "stays empty until Phase 11 (research) and Phase 12 (reflection) "
            "populate it."
        ),
    )

    web_research_enabled = st.toggle(
        "Pre-debate web research",
        value=bool(base_settings.web_research_enabled),
        disabled=st.session_state.running or not memory_enabled,
        help=(
            "Before turn 1, each agent runs a small search routine and "
            "populates its `## Knowledge` section with cited snippets. "
            "Requires agent memory to be enabled."
        ),
    )

    _web_adapter_choices = ["offline", "duckduckgo"]
    _web_adapter_default = (
        base_settings.web_search_adapter
        if base_settings.web_search_adapter in _web_adapter_choices
        else "offline"
    )
    web_search_adapter = st.selectbox(
        "Search adapter",
        _web_adapter_choices,
        index=_web_adapter_choices.index(_web_adapter_default),
        disabled=st.session_state.running or not web_research_enabled,
        help=(
            "`offline` uses canned fixtures (safe default). `duckduckgo` hits "
            "the live API and requires `pip install duckduckgo-search`."
        ),
    )

    reflection_enabled = st.toggle(
        "Pre-turn reflection",
        value=bool(memory_enabled),
        disabled=st.session_state.running or not memory_enabled,
        help=(
            "Before each speaking turn (skipped on turn 1), the agent runs "
            "a silent LLM call that reads the opponent's last answer and "
            "updates its `## Observations` and `## Strategy` sections. "
            "Requires agent memory to be enabled."
        ),
    )

    closing_round_enabled = st.toggle(
        "Closing round",
        value=bool(base_settings.closing_round_enabled),
        disabled=st.session_state.running,
        help=(
            "On each agent's final scheduled turn, swap the speaking "
            "behaviour for a closing-statement directive: summarise, "
            "acknowledge the strongest opposing point, conclude."
        ),
    )

    judge_enabled = st.toggle(
        "Enable judge",
        value=bool(base_settings.judge_enabled),
        disabled=st.session_state.running,
        help=(
            "After the final turn, run a third LLM pass that scores the "
            "debate on nine quality dimensions (Q1-Q9) and renders a "
            "scorecard below the chat. When agent memory is enabled the "
            "report is also persisted to runs/<run_id>/report.{json,md}."
        ),
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
        memory_enabled=bool(memory_enabled),
        web_research_enabled=bool(memory_enabled and web_research_enabled),
        web_search_adapter=str(web_search_adapter),
        closing_round_enabled=bool(closing_round_enabled),
        judge_enabled=bool(judge_enabled),
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
    st.session_state.run_id = None
    st.session_state.memory_snapshot = {}
    st.session_state.judge_report = None
    # Bumping the nonce changes the topic textbox's widget key, which
    # forces Streamlit to construct a fresh input on the next rerun and
    # honor ``value=""`` (otherwise the previously-typed value would be
    # retained as widget-owned state).
    st.session_state.topic_input_nonce += 1
    st.rerun()


# --- replay previously committed turns -------------------------------------

st.divider()


_QUALITY_COLORS: dict[str, str] = {"HIGH": "#3fb950", "MEDIUM": "#d29922", "LOW": "#f85149"}


def _quality_chip_html(metrics: dict[str, Any] | None) -> str:
    """Render a faint per-turn quality chip below a chat bubble.

    ``metrics`` is the small dict stored on each message
    (``{novelty, adherence, novelty_label, adherence_label}``). Returns
    an empty string when no metrics are available.
    """
    if not metrics:
        return ""
    nov_color = _QUALITY_COLORS.get(metrics.get("novelty_label", ""), "#8b949e")
    adh_color = _QUALITY_COLORS.get(metrics.get("adherence_label", ""), "#8b949e")
    return (
        f"<div style='font-size:0.78em;opacity:0.78;margin-top:0.25em;'>"
        f"<span style='color:{nov_color};'>● novelty {metrics['novelty']:.2f}</span>"
        f" &nbsp;·&nbsp; "
        f"<span style='color:{adh_color};'>● adherence {metrics['adherence']:.2f}</span>"
        f"</div>"
    )


def _render_message(
    speaker: str,
    content: str,
    *,
    reflection: str | None = None,
    metrics: dict[str, Any] | None = None,
) -> None:
    """Render a single chat bubble with a visible speaker label."""
    with st.chat_message(_LABELS[speaker], avatar=_AVATARS[speaker]):
        chip = f" &nbsp;·&nbsp; 🧠 _reflected: {reflection}_" if reflection else ""
        st.markdown(f"**{_LABELS[speaker]}**{chip}\n\n{content}")
        quality_html = _quality_chip_html(metrics)
        if quality_html:
            st.markdown(quality_html, unsafe_allow_html=True)


def _refresh_memory_snapshot(engine: DebateEngine) -> None:
    """Copy the engine's live memory into session state for replay rendering."""
    snapshot: dict[str, AgentMemory] = {}
    offender_mem = engine.memory_for("offender")
    defender_mem = engine.memory_for("defender")
    if offender_mem is not None:
        snapshot["offender"] = offender_mem
    if defender_mem is not None:
        snapshot["defender"] = defender_mem
    st.session_state.memory_snapshot = snapshot


def _linkify_knowledge(item: str) -> str:
    """Convert ``(source: <url>)`` suffixes into clickable Markdown links."""
    import re as _re

    return _re.sub(
        r"\(source:\s*(https?://[^\s)]+)\s*\)",
        lambda m: f"([source]({m.group(1)}))",
        item,
    )


def _render_memory_section(memory: AgentMemory) -> str:
    """Format an :class:`AgentMemory` as Markdown for an `st.expander`."""
    parts = [f"_Reflects turn **{memory.turn_index}**._", ""]

    def _block(title: str, items: tuple[str, ...], *, linkify: bool = False) -> None:
        parts.append(f"**{title}**")
        if items:
            for item in items:
                rendered = _linkify_knowledge(item) if linkify else item
                parts.append(f"- {rendered}")
        else:
            parts.append("_(empty)_")
        parts.append("")

    _block("Knowledge", memory.knowledge, linkify=True)
    _block("Observations", memory.observations)
    _block("Strategy", memory.strategy)
    return "\n".join(parts).rstrip()


for msg in st.session_state.messages:
    _render_message(
        msg["speaker"],
        msg["content"],
        reflection=msg.get("reflection"),
        metrics=msg.get("metrics"),
    )

# Phase 13.4: non-blocking loop hint when several recent turns scored LOW novelty.
_recent_metrics = [msg.get("metrics") for msg in st.session_state.messages if msg.get("metrics")]
if len(_recent_metrics) >= 3 and all(
    (m or {}).get("novelty_label") == "LOW" for m in _recent_metrics[-3:]
):
    st.info(
        "Agents may be repeating themselves — consider stopping or enabling the closing round.",
        icon="🔁",
    )

if st.session_state.last_error is not None:
    st.error(st.session_state.last_error)


# --- live memory panes (Phase 10) -------------------------------------------

if memory_enabled and st.session_state.memory_snapshot:
    st.divider()
    st.caption("Agent memory (read-only — populated by Phases 11 & 12).")
    mem_col_off, mem_col_def = st.columns(2)
    snapshot: dict[str, AgentMemory] = st.session_state.memory_snapshot
    with mem_col_off, st.expander("🗡️ Offender memory", expanded=False):
        off_mem = snapshot.get("offender")
        if off_mem is None:
            st.markdown("_No memory recorded yet._")
        else:
            st.markdown(_render_memory_section(off_mem))
    with mem_col_def, st.expander("🛡️ Defender memory", expanded=False):
        def_mem = snapshot.get("defender")
        if def_mem is None:
            st.markdown("_No memory recorded yet._")
        else:
            st.markdown(_render_memory_section(def_mem))


# --- transcript export ------------------------------------------------------


def _transcript_markdown(*, include_quality_metrics: bool = False) -> str:
    """Build a Markdown export from the committed session messages."""
    lines = [f"# Debate: {st.session_state.topic or '(no topic)'}", ""]
    for i, msg in enumerate(st.session_state.messages, start=1):
        label = _LABELS[msg["speaker"]]
        lines.append(f"### Turn {i} — {label}")
        lines.append("")
        lines.append(str(msg["content"]).strip())
        lines.append("")
    body = "\n".join(lines).rstrip() + "\n"
    if include_quality_metrics:
        from auto_debate.quality import (
            QualityLabel,
            TurnMetrics,
            render_metrics_table,
        )

        metrics_objs: list[TurnMetrics] = []
        for i, msg in enumerate(st.session_state.messages, start=1):
            m = msg.get("metrics")
            if not m:
                continue
            metrics_objs.append(
                TurnMetrics(
                    index=i,
                    novelty=float(m["novelty"]),
                    adherence=float(m["adherence"]),
                    novelty_label=cast(QualityLabel, m["novelty_label"]),
                    adherence_label=cast(QualityLabel, m["adherence_label"]),
                ),
            )
        table = render_metrics_table(metrics_objs)
        if table:
            body = body + "\n" + table
    return body


if st.session_state.messages and not st.session_state.running:
    include_metrics = st.checkbox(
        "Include quality metrics in export",
        value=False,
        key="export_with_metrics",
        help="Append per-turn novelty + adherence table to the downloaded Markdown.",
    )
    st.download_button(
        "⬇️ Download transcript (.md)",
        data=_transcript_markdown(include_quality_metrics=bool(include_metrics)),
        file_name="auto_debate_transcript.md",
        mime="text/markdown",
        use_container_width=False,
    )


# --- judge scorecard --------------------------------------------------------


def _render_judge_scorecard(report: JudgeReport) -> None:
    """Render a judge :class:`JudgeReport` as a Streamlit panel."""
    st.subheader("⚖️ Judge scorecard")
    st.caption(
        f"Overall **{report.overall:.1f} / 5** · judge model `{report.model or 'unknown'}`",
    )
    rows: list[dict[str, Any]] = [
        {
            "#": s.qid,
            "Dimension": s.title,
            "Score": f"{s.score} / 5",
            "Comment": s.comment,
        }
        for s in report.scores
    ]
    st.table(rows)
    if report.verdict:
        st.markdown(f"> {report.verdict}")
    st.download_button(
        "⬇️ Download judge report (.md)",
        data=render_report_markdown(report),
        file_name="report.md",
        mime="text/markdown",
        use_container_width=False,
        key="download_judge_report",
    )


_judge_report = st.session_state.get("judge_report")
if _judge_report is not None and not st.session_state.running:
    _render_judge_scorecard(_judge_report)


# --- live streaming ---------------------------------------------------------


def _run_judge(
    client: OllamaClient,
    settings: Settings,
    engine: DebateEngine,
    topic_text: str,
) -> JudgeReport | None:
    """Run a single post-debate judge pass and return the parsed report."""
    transcript = [(t.speaker, t.content) for t in engine.transcript()]
    judge = Judge(llm_client=client, model=settings.model_name)
    try:
        return judge.evaluate(topic=topic_text, transcript=transcript)
    except Exception as exc:  # defensive: judge failures must not crash the UI
        st.warning(f"Judge failed: {type(exc).__name__}: {exc}")
        return None


def _run_debate(settings: Settings, topic_text: str) -> None:
    """Drive a full debate, rendering tokens into chat-message placeholders."""
    try:
        client = OllamaClient(settings)
        client.ensure_model_available()
        # Phase 9: compose the prompt from sidebar-selected persona + behavior.
        # Phase 14: when a preset is active these are the *offender* fragments;
        # the defender override is computed below.
        try:
            persona = load_persona(offender_persona_name)
        except Exception:
            # Fall back to neutral on any registry error.
            persona = NEUTRAL_PERSONA
        try:
            behavior = load_behavior(offender_behavior_name)
        except Exception:
            # Fall back to standard on any registry error.
            behavior = STANDARD_BEHAVIOR
        # Phase 14: optional defender overrides (only differ from the
        # offender side when a preset is selected).
        defender_persona_obj = None
        defender_behavior_obj = None
        if (
            defender_persona_name != offender_persona_name
            or defender_behavior_name != offender_behavior_name
        ):
            try:
                defender_persona_obj = load_persona(defender_persona_name)
            except Exception:
                defender_persona_obj = None
            try:
                defender_behavior_obj = load_behavior(defender_behavior_name)
            except Exception:
                defender_behavior_obj = None
        # Phase 10: optional per-agent memory store.
        memory_store: MemoryStore | None = None
        run_id: str | None = None
        if settings.memory_enabled:
            memory_store = MemoryStore()
            run_id = st.session_state.run_id
        # Phase 11: optional pre-debate web research populates the
        # Knowledge section of each agent's memory before the engine
        # builds its system prompts. Requires memory to be enabled.
        if settings.web_research_enabled and memory_store is not None and run_id is not None:
            adapter = _build_search_adapter(settings.web_search_adapter)
            researcher = Researcher(
                llm_client=client,
                adapter=adapter,
                memory_store=memory_store,
                run_id=run_id,
            )
            for agent_id in ("offender", "defender"):
                with st.spinner(
                    f"Researching for {_LABELS[agent_id]} via `{settings.web_search_adapter}`…",
                ):
                    try:
                        researcher.populate_for_agent(agent_id, topic=topic_text)
                    except Exception as exc:
                        st.warning(
                            f"Research failed for {_LABELS[agent_id]}: {type(exc).__name__}: {exc}",
                        )
        engine = DebateEngine(
            settings,
            client,
            topic_text,
            persona=persona,
            behavior=behavior,
            defender_persona=defender_persona_obj,
            defender_behavior=defender_behavior_obj,
            memory_store=memory_store,
            run_id=run_id,
            reflector=(
                Reflector(llm_client=client, topic=topic_text, model=settings.model_name)
                if (memory_store is not None and reflection_enabled)
                else None
            ),
        )
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
                diff = engine.last_reflection_for(speaker)  # type: ignore[arg-type]
                reflection_label = (
                    diff.summary() if (diff is not None and not diff.is_empty) else None
                )
                # Phase 13: capture novelty + adherence for the just-appended turn.
                turn_metrics = engine.compute_quality_metrics()
                latest = turn_metrics[-1] if turn_metrics else None
                metrics_payload: dict[str, Any] | None = (
                    {
                        "novelty": latest.novelty,
                        "adherence": latest.adherence,
                        "novelty_label": latest.novelty_label,
                        "adherence_label": latest.adherence_label,
                    }
                    if latest is not None
                    else None
                )
                st.session_state.messages.append(
                    {
                        "speaker": speaker,
                        "content": final_text,
                        "reflection": reflection_label,
                        "metrics": metrics_payload,
                    },
                )
            _refresh_memory_snapshot(engine)
            if stop_check():
                break
            speaker = "defender" if speaker == "offender" else "offender"
    except OllamaUnavailableError as exc:
        st.session_state.last_error = f"Lost connection to Ollama mid-debate.\n\n```\n{exc}\n```"
    except ModelNotFoundError as exc:
        st.session_state.last_error = f"Model became unavailable: {exc}"
    else:
        # Phase 15: optional post-debate judge pass.
        if settings.judge_enabled and engine.transcript() and not stop_check():
            with st.spinner(
                "Judge is scoring the debate… (one extra LLM pass — "
                "this can take a couple of minutes on a CPU model)",
            ):
                report = _run_judge(client, settings, engine, topic_text)
            if report is not None:
                st.session_state.judge_report = report
                if memory_store is not None and run_id is not None:
                    # Persist alongside the run, NOT inside the per-run
                    # ``memory/`` subfolder — the report describes the
                    # whole debate, not a single agent's memory.
                    try:
                        save_report(report, run_dir=memory_store.root / run_id)
                    except OSError as exc:
                        st.warning(
                            f"Judge report could not be saved: {type(exc).__name__}: {exc}",
                        )


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
    st.session_state.run_id = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    st.session_state.memory_snapshot = {}
    st.session_state.judge_report = None
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
        "**Auto Debate** runs two local LLM personas against a topic of your choice:\n\n"
        "- **Offender** 🗡️ argues *against* the topic; **Defender** 🛡️ argues *for* it.\n"
        "- They take turns. Each turn is streamed token-by-token from your local "
        "[Ollama](https://ollama.com) server — **nothing leaves your machine**.\n"
        "- The engine maintains two parallel chat histories and uses an "
        "alternating-role mirroring trick so a single chat model can play both sides.\n"
        "- **Max turns** caps the debate length (per side); **Stop** halts streaming "
        "within one token; **Clear** wipes the transcript.\n"
        "- After a debate finishes, use **Download transcript** to save the conversation "
        "as Markdown.\n\n"
        "Source code & full design docs: "
        "[GitHub repo](https://github.com/Sotiris01/Auto-Debate---Two-Agent-Local-LLM-Debate-App).",
    )
