"""
tests/test_config.py — Tests for the typed configuration loader.

Part of the Auto Debate project. See PROJECT.md and ROADMAP.md.
"""

from __future__ import annotations

import pytest

from auto_debate.config import ConfigError, Settings, load_settings

# Every test runs with a clean slate. We monkeypatch each env var to None
# (delenv) so neither the developer's real environment nor a stray .env
# in the repo root can leak into the test.
_ENV_VARS = (
    "OLLAMA_HOST",
    "MODEL_NAME",
    "MAX_TURNS",
    "TEMPERATURE",
    "TOP_P",
    "WORD_LIMIT",
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    for var in _ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    # Run from a temp cwd so a parent-directory .env is never auto-loaded.
    monkeypatch.chdir(tmp_path)


def test_defaults_when_env_empty() -> None:
    s = load_settings()
    assert isinstance(s, Settings)
    assert s.ollama_host == "http://localhost:11434"
    assert s.model_name == "gemma3:4b"
    assert s.max_turns == 10
    assert s.temperature == pytest.approx(0.8)
    assert s.top_p == pytest.approx(0.95)
    assert s.word_limit == 120


def test_settings_is_frozen() -> None:
    s = load_settings()
    with pytest.raises(AttributeError):  # FrozenInstanceError subclasses AttributeError
        s.max_turns = 99  # type: ignore[misc]


def test_env_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OLLAMA_HOST", "http://example.com:11434")
    monkeypatch.setenv("MODEL_NAME", "gemma3:1b")
    monkeypatch.setenv("MAX_TURNS", "3")
    monkeypatch.setenv("TEMPERATURE", "1.2")
    monkeypatch.setenv("TOP_P", "0.5")
    monkeypatch.setenv("WORD_LIMIT", "60")

    s = load_settings()
    assert s.ollama_host == "http://example.com:11434"
    assert s.model_name == "gemma3:1b"
    assert s.max_turns == 3
    assert s.temperature == pytest.approx(1.2)
    assert s.top_p == pytest.approx(0.5)
    assert s.word_limit == 60


@pytest.mark.parametrize(
    ("var", "value", "fragment"),
    [
        ("OLLAMA_HOST", "localhost:11434", "OLLAMA_HOST"),
        ("MAX_TURNS", "0", "MAX_TURNS"),
        ("MAX_TURNS", "-5", "MAX_TURNS"),
        ("TEMPERATURE", "0", "TEMPERATURE"),
        ("TEMPERATURE", "2.5", "TEMPERATURE"),
        ("TOP_P", "0", "TOP_P"),
        ("TOP_P", "1.5", "TOP_P"),
        ("WORD_LIMIT", "10", "WORD_LIMIT"),
    ],
)
def test_invalid_values_raise(
    monkeypatch: pytest.MonkeyPatch, var: str, value: str, fragment: str
) -> None:
    monkeypatch.setenv(var, value)
    with pytest.raises(ConfigError) as exc:
        load_settings()
    assert fragment in str(exc.value)


def test_non_numeric_int_reports_problem(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAX_TURNS", "abc")
    with pytest.raises(ConfigError) as exc:
        load_settings()
    assert "MAX_TURNS" in str(exc.value)


def test_non_numeric_float_reports_problem(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEMPERATURE", "hot")
    with pytest.raises(ConfigError) as exc:
        load_settings()
    assert "TEMPERATURE" in str(exc.value)


def test_multiple_problems_concatenated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAX_TURNS", "0")
    monkeypatch.setenv("TOP_P", "5")
    monkeypatch.setenv("WORD_LIMIT", "5")
    with pytest.raises(ConfigError) as exc:
        load_settings()
    msg = str(exc.value)
    assert "MAX_TURNS" in msg
    assert "TOP_P" in msg
    assert "WORD_LIMIT" in msg


def test_dotenv_path_is_loaded(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    env_file = tmp_path / "custom.env"
    env_file.write_text("MODEL_NAME=gemma3:12b\nMAX_TURNS=4\n", encoding="utf-8")
    s = load_settings(dotenv_path=env_file)
    assert s.model_name == "gemma3:12b"
    assert s.max_turns == 4
