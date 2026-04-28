"""
quality.py — Phase 13 post-processing metrics.

Pure-Python scorers that look at the streamed transcript and surface
**repetition** and **topic-drift** signals. No model calls, no external
deps — `collections.Counter` + a couple of regexes.

Two scorers:

* :func:`ngram_overlap` — Jaccard similarity of n-grams between a turn
  and the union of preceding turns. High overlap = looping.
* :func:`topic_adherence` — TF-IDF cosine between a turn and the topic
  text (plus the agent's role label). Low score = drift.

Both return a float in ``[0.0, 1.0]`` and have a paired
:func:`label_for` helper that buckets them into ``LOW / MEDIUM / HIGH``
against tunable thresholds (see :class:`QualityThresholds`).

The transcript-export enrichment lives here too
(:func:`render_metrics_table`) so :meth:`engine.DebateEngine.to_markdown`
can opt-in via ``include_quality_metrics=True`` without dragging the
engine into stats territory.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Literal

__all__ = [
    "DEFAULT_THRESHOLDS",
    "QualityLabel",
    "QualityThresholds",
    "TurnMetrics",
    "compute_turn_metrics",
    "is_looping",
    "label_for_adherence",
    "label_for_novelty",
    "ngram_overlap",
    "render_metrics_table",
    "topic_adherence",
]


QualityLabel = Literal["LOW", "MEDIUM", "HIGH"]


# --- thresholds -------------------------------------------------------------


@dataclass(frozen=True)
class QualityThresholds:
    """Bucket boundaries for novelty and adherence labels.

    A score ``s`` is labelled:

    * ``HIGH`` when ``s >= high``
    * ``MEDIUM`` when ``low <= s < high``
    * ``LOW`` when ``s < low``

    For *novelty* the score is ``1 - overlap``, so a high score is good
    (lots of new content). For *adherence* the cosine itself is the
    score, so high is also good. The same bucket function works for both.
    """

    novelty_low: float = 0.30
    novelty_high: float = 0.55
    adherence_low: float = 0.10
    adherence_high: float = 0.25
    loop_window: int = 3
    """How many consecutive LOW-novelty turns before :func:`is_looping`
    flags the debate."""

    def __post_init__(self) -> None:
        for name, lo, hi in (
            ("novelty", self.novelty_low, self.novelty_high),
            ("adherence", self.adherence_low, self.adherence_high),
        ):
            if not (0.0 <= lo <= hi <= 1.0):
                msg = f"{name} thresholds must satisfy 0 <= low ({lo}) <= high ({hi}) <= 1"
                raise ValueError(msg)
        if self.loop_window < 1:
            msg = f"loop_window must be >= 1 (got {self.loop_window})"
            raise ValueError(msg)


DEFAULT_THRESHOLDS = QualityThresholds()


# --- tokenisation -----------------------------------------------------------

_TOKEN_RE = re.compile(r"[A-Za-z0-9']+")

# A small built-in stop-word list. We intentionally keep this short — the
# TF-IDF reweighting already suppresses common words across turns, and a
# tiny list keeps short topics like "Is X good?" from getting wiped out.
_STOP_WORDS: frozenset[str] = frozenset(
    {
        "a",
        "an",
        "the",
        "and",
        "or",
        "but",
        "if",
        "then",
        "of",
        "to",
        "in",
        "on",
        "at",
        "for",
        "with",
        "by",
        "as",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "this",
        "that",
        "these",
        "those",
        "it",
        "its",
        "i",
        "you",
        "we",
        "they",
        "he",
        "she",
        "them",
        "us",
        "do",
        "does",
        "did",
        "have",
        "has",
        "had",
        "not",
        "no",
        "so",
        "than",
        "too",
        "very",
        "can",
        "will",
        "just",
    },
)


def _tokenise(text: str) -> list[str]:
    """Lowercase word tokens, stripped of punctuation, no stop-words."""
    return [tok.lower() for tok in _TOKEN_RE.findall(text) if tok.lower() not in _STOP_WORDS]


def _stem_for_adherence(token: str) -> str:
    """Crude length-gated suffix stripper used only by :func:`topic_adherence`.

    Live debates routinely toggle between ``cats`` (the topic noun) and
    ``cat`` (the inflected form a turn naturally uses), and the raw
    TF-IDF cosine then drops to zero. A real stemmer is overkill for
    this — chopping the three most common English plural / 3rd-person
    suffixes off tokens of length > 3 lifts adherence on inflected
    matches without distorting short content words.
    """
    if len(token) > 4 and token.endswith("ies"):
        return token[:-3] + "y"
    if len(token) > 4 and token.endswith("es"):
        return token[:-2]
    if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def _ngrams(tokens: Sequence[str], n: int) -> set[tuple[str, ...]]:
    if n < 1:
        msg = f"n must be >= 1 (got {n})"
        raise ValueError(msg)
    if len(tokens) < n:
        return set()
    return {tuple(tokens[i : i + n]) for i in range(len(tokens) - n + 1)}


# --- novelty ----------------------------------------------------------------


def ngram_overlap(turn: str, prev_turns: Iterable[str], *, n: int = 3) -> float:
    """Jaccard similarity of ``n``-grams between ``turn`` and the union
    of ``prev_turns``.

    Returns ``0.0`` when either side has no n-grams (e.g. the very first
    turn, or a turn shorter than ``n`` tokens after stop-word removal).
    The score lives in ``[0.0, 1.0]``: ``1.0`` means every n-gram in the
    new turn already appeared earlier (heavy repetition); ``0.0`` means
    the new turn is fully novel.
    """
    new_tokens = _tokenise(turn)
    new_grams = _ngrams(new_tokens, n)
    if not new_grams:
        return 0.0

    prev_grams: set[tuple[str, ...]] = set()
    for prev in prev_turns:
        prev_grams |= _ngrams(_tokenise(prev), n)
    if not prev_grams:
        return 0.0

    intersection = new_grams & prev_grams
    union = new_grams | prev_grams
    return len(intersection) / len(union)


def label_for_novelty(
    novelty: float,
    thresholds: QualityThresholds = DEFAULT_THRESHOLDS,
) -> QualityLabel:
    """Bucket a novelty score (1 - overlap) into LOW/MEDIUM/HIGH."""
    if novelty >= thresholds.novelty_high:
        return "HIGH"
    if novelty >= thresholds.novelty_low:
        return "MEDIUM"
    return "LOW"


# --- adherence (TF-IDF cosine, two-document corpus) -------------------------


def _tfidf_vector(
    tokens: Sequence[str],
    doc_freq: Counter[str],
    n_docs: int,
) -> dict[str, float]:
    """Compute a TF-IDF vector for a single document.

    Uses raw term frequency (no log smoothing) and the standard
    ``log((1 + n_docs) / (1 + df)) + 1`` IDF weight. Two-document corpora
    therefore give roughly ``log(3/2) + 1 ≈ 1.405`` for terms that appear
    in both, vs ``log(3/1) + 1 ≈ 2.098`` for unique terms.
    """
    if not tokens:
        return {}
    tf = Counter(tokens)
    return {
        term: count * (math.log((1 + n_docs) / (1 + doc_freq[term])) + 1.0)
        for term, count in tf.items()
    }


def _cosine(a: dict[str, float], b: dict[str, float]) -> float:
    if not a or not b:
        return 0.0
    common = set(a) & set(b)
    dot = sum(a[t] * b[t] for t in common)
    if dot == 0.0:
        return 0.0
    norm_a = math.sqrt(sum(v * v for v in a.values()))
    norm_b = math.sqrt(sum(v * v for v in b.values()))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def topic_adherence(turn: str, topic: str, *, role_hint: str = "") -> float:
    """Cosine similarity between a turn and ``topic`` (+ optional role).

    A score of ``1.0`` means the turn's vocabulary is identical to the
    topic's; ``0.0`` means there is no shared content word at all. The
    optional ``role_hint`` (e.g. ``"offender"`` or ``"defender"``) adds
    the role label to the topic document so a turn that quotes its own
    role still picks up some signal.
    """
    turn_tokens = _tokenise(turn)
    topic_text = f"{topic} {role_hint}".strip()
    topic_tokens = _tokenise(topic_text)
    if not turn_tokens or not topic_tokens:
        return 0.0

    # Normalise inflection (cats/cat, dogs/dog, applies/apply) so the
    # cosine doesn't collapse to ~0 on naturally-phrased turns. Used
    # only here — ngram_overlap deliberately keeps raw tokens.
    turn_tokens = [_stem_for_adherence(t) for t in turn_tokens]
    topic_tokens = [_stem_for_adherence(t) for t in topic_tokens]

    df: Counter[str] = Counter()
    df.update(set(turn_tokens))
    df.update(set(topic_tokens))
    n_docs = 2

    turn_vec = _tfidf_vector(turn_tokens, df, n_docs)
    topic_vec = _tfidf_vector(topic_tokens, df, n_docs)
    return _cosine(turn_vec, topic_vec)


def label_for_adherence(
    adherence: float,
    thresholds: QualityThresholds = DEFAULT_THRESHOLDS,
) -> QualityLabel:
    """Bucket an adherence score into LOW/MEDIUM/HIGH."""
    if adherence >= thresholds.adherence_high:
        return "HIGH"
    if adherence >= thresholds.adherence_low:
        return "MEDIUM"
    return "LOW"


# --- per-turn aggregate -----------------------------------------------------


@dataclass(frozen=True)
class TurnMetrics:
    """Combined novelty + adherence snapshot for a single committed turn."""

    index: int
    novelty: float
    adherence: float
    novelty_label: QualityLabel
    adherence_label: QualityLabel

    def chip_text(self) -> str:
        """One-line summary suitable for a chat-bubble chip."""
        return f"novelty {self.novelty:.2f} · adherence {self.adherence:.2f}"


def compute_turn_metrics(
    *,
    turn_index: int,
    turn_text: str,
    prev_turn_texts: Sequence[str],
    topic: str,
    role_hint: str = "",
    n: int = 3,
    thresholds: QualityThresholds = DEFAULT_THRESHOLDS,
    novelty_window: int = 2,
) -> TurnMetrics:
    """Compute :class:`TurnMetrics` for one turn.

    Only the most recent ``novelty_window`` previous turns feed the
    novelty calculation — looping is a *recent* phenomenon, and folding
    in turn 1 when scoring turn 14 would dilute the signal.
    """
    if novelty_window < 1:
        msg = f"novelty_window must be >= 1 (got {novelty_window})"
        raise ValueError(msg)
    window = list(prev_turn_texts)[-novelty_window:]
    overlap = ngram_overlap(turn_text, window, n=n)
    novelty = 1.0 - overlap
    adherence = topic_adherence(turn_text, topic, role_hint=role_hint)
    return TurnMetrics(
        index=turn_index,
        novelty=novelty,
        adherence=adherence,
        novelty_label=label_for_novelty(novelty, thresholds),
        adherence_label=label_for_adherence(adherence, thresholds),
    )


# --- loop detection ---------------------------------------------------------


def is_looping(
    metrics: Sequence[TurnMetrics],
    thresholds: QualityThresholds = DEFAULT_THRESHOLDS,
) -> bool:
    """``True`` when the last ``loop_window`` turns are all LOW novelty."""
    window = thresholds.loop_window
    if len(metrics) < window:
        return False
    return all(m.novelty_label == "LOW" for m in metrics[-window:])


# --- transcript export enrichment -------------------------------------------


def render_metrics_table(metrics: Sequence[TurnMetrics]) -> str:
    """Render a Markdown table summarising per-turn metrics.

    Used by :meth:`engine.DebateEngine.to_markdown` when
    ``include_quality_metrics=True``.
    """
    if not metrics:
        return ""
    lines = [
        "## Quality metrics",
        "",
        "| Turn | Novelty | Adherence | Labels |",
        "|---|---|---|---|",
    ]
    for m in metrics:
        lines.append(
            f"| {m.index} | {m.novelty:.2f} | {m.adherence:.2f} | "
            f"{m.novelty_label} novelty · {m.adherence_label} adherence |",
        )
    avg_novelty = sum(m.novelty for m in metrics) / len(metrics)
    avg_adherence = sum(m.adherence for m in metrics) / len(metrics)
    lines.append("")
    lines.append(
        f"**Averages:** novelty {avg_novelty:.2f} · adherence {avg_adherence:.2f}",
    )
    return "\n".join(lines) + "\n"
