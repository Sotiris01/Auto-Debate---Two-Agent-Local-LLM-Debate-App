"""Tests for the Phase 13 quality / repetition guards module."""

from __future__ import annotations

import pytest

from auto_debate.quality import (
    DEFAULT_THRESHOLDS,
    QualityThresholds,
    TurnMetrics,
    compute_turn_metrics,
    is_looping,
    label_for_adherence,
    label_for_novelty,
    ngram_overlap,
    render_metrics_table,
    topic_adherence,
)

# --- 13.1 novelty / n-gram overlap -----------------------------------------


def test_ngram_overlap_identical_text_is_one() -> None:
    text = "The reactor cooling system is the strongest argument for safety."
    assert ngram_overlap(text, [text], n=3) == pytest.approx(1.0)


def test_ngram_overlap_disjoint_text_is_zero() -> None:
    a = "Cats prefer warm sunlight on hardwood floors."
    b = "Quantum tunneling enables semiconductor diodes everywhere."
    assert ngram_overlap(a, [b], n=3) == 0.0


def test_ngram_overlap_no_previous_turns_returns_zero() -> None:
    assert ngram_overlap("anything goes here", [], n=3) == 0.0


def test_ngram_overlap_very_short_turn_returns_zero() -> None:
    # Fewer tokens than n after stop-word removal → no n-grams to compare.
    assert ngram_overlap("yes", ["something else entirely longer"], n=3) == 0.0


def test_ngram_overlap_partial_match_lies_between_zero_and_one() -> None:
    a = "renewable energy reduces carbon emissions significantly worldwide today"
    b = "renewable energy reduces costs over time across markets globally"
    score = ngram_overlap(a, [b], n=3)
    assert 0.0 < score < 1.0


def test_ngram_overlap_rejects_invalid_n() -> None:
    with pytest.raises(ValueError, match="n must be"):
        ngram_overlap("hello world test", ["some other text"], n=0)


def test_label_for_novelty_buckets() -> None:
    th = DEFAULT_THRESHOLDS
    assert label_for_novelty(0.9, th) == "HIGH"
    assert label_for_novelty(th.novelty_high, th) == "HIGH"
    assert label_for_novelty(th.novelty_low, th) == "MEDIUM"
    assert label_for_novelty(0.0, th) == "LOW"


# --- 13.2 topic adherence --------------------------------------------------


def test_topic_adherence_high_when_terms_match() -> None:
    topic = "Should nuclear energy expand for climate goals?"
    on_topic = (
        "Nuclear energy should expand because it scales for climate goals "
        "without carbon emissions across the grid."
    )
    score = topic_adherence(on_topic, topic)
    assert score > 0.3


def test_topic_adherence_low_when_offtopic() -> None:
    topic = "Should nuclear energy expand for climate goals?"
    off_topic = "Cats enjoy sunbathing on warm hardwood floors during weekend mornings."
    score = topic_adherence(off_topic, topic)
    assert score < 0.05


def test_topic_adherence_handles_empty_inputs() -> None:
    assert topic_adherence("", "anything") == 0.0
    assert topic_adherence("anything", "") == 0.0


def test_topic_adherence_matches_inflected_forms() -> None:
    """Singular/plural inflection should not collapse the cosine to ~0.

    Regression for the live-UI bug where turns about ``cat``/``dog``
    scored ~0 against the topic ``Cats are better pets than dogs``.
    """
    topic = "Cats are better pets than dogs"
    inflected = "A cat offers a calmer companionship than a dog ever could as a pet."
    score = topic_adherence(inflected, topic)
    assert score > 0.3


def test_label_for_adherence_buckets() -> None:
    th = DEFAULT_THRESHOLDS
    assert label_for_adherence(0.9, th) == "HIGH"
    assert label_for_adherence(th.adherence_high, th) == "HIGH"
    assert label_for_adherence(th.adherence_low, th) == "MEDIUM"
    assert label_for_adherence(0.0, th) == "LOW"


# --- thresholds validation -------------------------------------------------


def test_invalid_thresholds_rejected() -> None:
    with pytest.raises(ValueError, match="novelty thresholds"):
        QualityThresholds(novelty_low=0.6, novelty_high=0.4)
    with pytest.raises(ValueError, match="adherence thresholds"):
        QualityThresholds(adherence_low=-0.1, adherence_high=0.5)
    with pytest.raises(ValueError, match="loop_window"):
        QualityThresholds(loop_window=0)


# --- compute_turn_metrics --------------------------------------------------


def test_compute_turn_metrics_first_turn_is_high_novelty() -> None:
    metrics = compute_turn_metrics(
        turn_index=1,
        turn_text="Nuclear energy reduces emissions and stabilises baseload power.",
        prev_turn_texts=[],
        topic="Should nuclear energy expand?",
    )
    assert metrics.novelty == 1.0
    assert metrics.novelty_label == "HIGH"


def test_compute_turn_metrics_repeated_turn_is_low_novelty() -> None:
    repeated = "Nuclear energy reduces emissions and stabilises baseload power."
    metrics = compute_turn_metrics(
        turn_index=2,
        turn_text=repeated,
        prev_turn_texts=[repeated],
        topic="Should nuclear energy expand?",
    )
    assert metrics.novelty < 0.1
    assert metrics.novelty_label == "LOW"


def test_compute_turn_metrics_uses_only_recent_window() -> None:
    """A repeated turn after a long gap still scores as repeating
    because the window keeps the most recent neighbours."""
    text = "Renewable subsidies reduce long-run costs across multiple markets."
    distant = "Cat naps and tea breaks regulate weekend household productivity."
    metrics = compute_turn_metrics(
        turn_index=10,
        turn_text=text,
        prev_turn_texts=[text, distant, distant],  # window=2 → distant only
        topic="Subsidies?",
        novelty_window=2,
    )
    assert metrics.novelty == 1.0  # repeated turn is outside the window


def test_compute_turn_metrics_rejects_bad_window() -> None:
    with pytest.raises(ValueError, match="novelty_window"):
        compute_turn_metrics(
            turn_index=1,
            turn_text="x y z",
            prev_turn_texts=[],
            topic="t",
            novelty_window=0,
        )


# --- 13.4 loop detection ---------------------------------------------------


def _mk_metric(idx: int, novelty: float, adherence: float = 0.5) -> TurnMetrics:
    return TurnMetrics(
        index=idx,
        novelty=novelty,
        adherence=adherence,
        novelty_label=label_for_novelty(novelty),
        adherence_label=label_for_adherence(adherence),
    )


def test_is_looping_triggers_after_three_low_novelty_turns() -> None:
    metrics = [
        _mk_metric(1, 0.9),
        _mk_metric(2, 0.8),
        _mk_metric(3, 0.05),
        _mk_metric(4, 0.05),
        _mk_metric(5, 0.05),
    ]
    assert is_looping(metrics) is True


def test_is_looping_false_when_high_turn_breaks_streak() -> None:
    metrics = [
        _mk_metric(1, 0.05),
        _mk_metric(2, 0.05),
        _mk_metric(3, 0.9),  # streak broken
    ]
    assert is_looping(metrics) is False


def test_is_looping_needs_full_window() -> None:
    metrics = [_mk_metric(1, 0.05), _mk_metric(2, 0.05)]
    assert is_looping(metrics) is False  # default window is 3


def test_is_looping_custom_window() -> None:
    th = QualityThresholds(loop_window=2)
    metrics = [_mk_metric(1, 0.9), _mk_metric(2, 0.05), _mk_metric(3, 0.05)]
    assert is_looping(metrics, th) is True


# --- 13.5 transcript export enrichment -------------------------------------


def test_render_metrics_table_includes_header_and_averages() -> None:
    metrics = [_mk_metric(1, 0.9, 0.4), _mk_metric(2, 0.5, 0.3)]
    table = render_metrics_table(metrics)
    assert "## Quality metrics" in table
    assert "| Turn | Novelty | Adherence | Labels |" in table
    assert "| 1 | 0.90 | 0.40 |" in table
    assert "Averages" in table


def test_render_metrics_table_empty_returns_empty_string() -> None:
    assert render_metrics_table([]) == ""


# --- 13.5 engine integration ------------------------------------------------


def test_engine_to_markdown_with_quality_metrics(tmp_path: pytest.TempPathFactory) -> None:
    """Engine.to_markdown(include_quality_metrics=True) appends the table."""
    from collections.abc import Iterator
    from dataclasses import replace as dc_replace
    from typing import Any

    from auto_debate.config import Settings
    from auto_debate.engine import DebateEngine

    class _Client:
        def __init__(self, scripts: list[list[str]]) -> None:
            self._scripts = list(scripts)

        def stream_chat(
            self,
            messages: list[dict[str, Any]],
            *,
            options: dict[str, Any] | None = None,
            model: str | None = None,
        ) -> Iterator[str]:
            yield from self._scripts.pop(0)

    settings = Settings(
        ollama_host="http://localhost:11434",
        model_name="gemma3:4b",
        max_turns=2,
        temperature=0.7,
        top_p=0.9,
        word_limit=120,
    )
    engine = DebateEngine(
        settings,
        _Client(
            scripts=[
                ["Renewable energy scales for climate goals across modern grids."],
                ["Renewable energy scales for climate goals across modern grids."],
            ],
        ),
        topic="Should renewable energy scale for climate goals?",
    )
    list(engine.run_one_turn("offender"))
    list(engine.run_one_turn("defender"))

    plain = engine.to_markdown()
    assert "## Quality metrics" not in plain

    enriched = engine.to_markdown(include_quality_metrics=True)
    assert "## Quality metrics" in enriched
    assert "| 1 |" in enriched
    assert "| 2 |" in enriched

    metrics = engine.compute_quality_metrics()
    assert len(metrics) == 2
    # Identical turn 2 vs turn 1 → low novelty.
    assert metrics[1].novelty_label == "LOW"
    # Touch dc_replace import used elsewhere only conditionally.
    _ = dc_replace
