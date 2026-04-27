"""
tests/test_llm.py — Tests for the Ollama wrapper.

Part of the Auto Debate project. See PROJECT.md and ROADMAP.md.

All tests use mocks — no live Ollama server is required.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from config import Settings
from llm import (
    ModelNotFoundError,
    OllamaClient,
    OllamaUnavailableError,
    chat_options,
)

# --- helpers ----------------------------------------------------------------


def _settings(model: str = "gemma3:4b", word_limit: int = 120) -> Settings:
    return Settings(
        ollama_host="http://localhost:11434",
        model_name=model,
        max_turns=10,
        temperature=0.8,
        top_p=0.95,
        word_limit=word_limit,
    )


def _list_response(*model_names: str) -> SimpleNamespace:
    return SimpleNamespace(
        models=[SimpleNamespace(model=name) for name in model_names],
    )


class _FakeClient:
    """Minimal stand-in for ``ollama.Client``."""

    def __init__(
        self,
        *,
        list_response: Any = None,
        list_exc: BaseException | None = None,
        chat_chunks: list[Any] | None = None,
        chat_exc: BaseException | None = None,
    ) -> None:
        self._list_response = list_response
        self._list_exc = list_exc
        self._chat_chunks = chat_chunks or []
        self._chat_exc = chat_exc
        self.chat_kwargs: dict[str, Any] | None = None

    def list(self) -> Any:
        if self._list_exc is not None:
            raise self._list_exc
        return self._list_response

    def chat(self, **kwargs: Any) -> Any:
        self.chat_kwargs = kwargs
        if self._chat_exc is not None:
            raise self._chat_exc
        return iter(self._chat_chunks)


# --- chat_options -----------------------------------------------------------


def test_chat_options_includes_required_fields() -> None:
    opts = chat_options(_settings(word_limit=120))
    assert opts["temperature"] == pytest.approx(0.8)
    assert opts["top_p"] == pytest.approx(0.95)
    assert isinstance(opts["num_predict"], int)
    assert opts["num_predict"] > 120  # cap > word_limit but not insane


def test_num_predict_floor_for_tiny_word_limit() -> None:
    opts = chat_options(_settings(word_limit=30))
    assert opts["num_predict"] >= 64  # never below the floor


# --- ensure_model_available -------------------------------------------------


def test_ensure_model_available_passes_when_present() -> None:
    fake = _FakeClient(list_response=_list_response("gemma3:4b", "llama3:8b"))
    OllamaClient(_settings(), client=fake).ensure_model_available()


def test_ensure_model_available_raises_when_list_empty() -> None:
    fake = _FakeClient(list_response=_list_response())
    with pytest.raises(ModelNotFoundError) as exc:
        OllamaClient(_settings()).__class__(_settings(), client=fake).ensure_model_available()
    assert "ollama pull gemma3:4b" in str(exc.value)


def test_ensure_model_available_raises_when_other_models_present() -> None:
    fake = _FakeClient(list_response=_list_response("llama3:8b"))
    with pytest.raises(ModelNotFoundError):
        OllamaClient(_settings(), client=fake).ensure_model_available()


def test_ensure_model_available_accepts_dict_response() -> None:
    fake = _FakeClient(list_response={"models": [{"model": "gemma3:4b"}]})
    OllamaClient(_settings(), client=fake).ensure_model_available()


def test_ensure_model_available_wraps_connection_error() -> None:
    fake = _FakeClient(list_exc=ConnectionError("refused"))
    with pytest.raises(OllamaUnavailableError) as exc:
        OllamaClient(_settings(), client=fake).ensure_model_available()
    assert "http://localhost:11434" in str(exc.value)


def test_ensure_model_available_wraps_nested_connection_cause() -> None:
    inner = ConnectionRefusedError("nope")
    outer = RuntimeError("ollama wrapped it")
    outer.__cause__ = inner
    fake = _FakeClient(list_exc=outer)
    with pytest.raises(OllamaUnavailableError):
        OllamaClient(_settings(), client=fake).ensure_model_available()


def test_ensure_model_available_passes_through_other_errors() -> None:
    fake = _FakeClient(list_exc=ValueError("boom"))
    with pytest.raises(ValueError):
        OllamaClient(_settings(), client=fake).ensure_model_available()


def test_ensure_model_available_explicit_name_overrides_settings() -> None:
    fake = _FakeClient(list_response=_list_response("llama3:8b"))
    client = OllamaClient(_settings(), client=fake)
    client.ensure_model_available("llama3:8b")  # ok
    with pytest.raises(ModelNotFoundError):
        client.ensure_model_available("nonexistent:1b")


# --- stream_chat ------------------------------------------------------------


def _msg_chunk(content: str) -> SimpleNamespace:
    return SimpleNamespace(message=SimpleNamespace(content=content))


def test_stream_chat_yields_content_only() -> None:
    chunks = [_msg_chunk("Hello"), _msg_chunk(", "), _msg_chunk("world.")]
    fake = _FakeClient(chat_chunks=chunks)
    out = list(
        OllamaClient(_settings(), client=fake).stream_chat(
            [{"role": "user", "content": "hi"}],
        ),
    )
    assert out == ["Hello", ", ", "world."]
    assert fake.chat_kwargs is not None
    assert fake.chat_kwargs["model"] == "gemma3:4b"
    assert fake.chat_kwargs["stream"] is True


def test_stream_chat_skips_empty_chunks() -> None:
    chunks = [_msg_chunk(""), _msg_chunk("ok"), _msg_chunk("")]
    fake = _FakeClient(chat_chunks=chunks)
    out = list(
        OllamaClient(_settings(), client=fake).stream_chat(
            [{"role": "user", "content": "hi"}],
        ),
    )
    assert out == ["ok"]


def test_stream_chat_accepts_dict_chunks() -> None:
    chunks = [{"message": {"content": "abc"}}, {"message": {"content": "def"}}]
    fake = _FakeClient(chat_chunks=chunks)
    out = list(
        OllamaClient(_settings(), client=fake).stream_chat(
            [{"role": "user", "content": "hi"}],
        ),
    )
    assert out == ["abc", "def"]


def test_stream_chat_uses_default_options_when_omitted() -> None:
    fake = _FakeClient(chat_chunks=[_msg_chunk("x")])
    list(
        OllamaClient(_settings(), client=fake).stream_chat(
            [{"role": "user", "content": "hi"}],
        ),
    )
    assert fake.chat_kwargs is not None
    opts = fake.chat_kwargs["options"]
    assert "temperature" in opts and "top_p" in opts and "num_predict" in opts


def test_stream_chat_forwards_explicit_options_and_model() -> None:
    fake = _FakeClient(chat_chunks=[_msg_chunk("x")])
    list(
        OllamaClient(_settings(), client=fake).stream_chat(
            [{"role": "user", "content": "hi"}],
            options={"temperature": 0.1},
            model="gemma3:1b",
        ),
    )
    assert fake.chat_kwargs is not None
    assert fake.chat_kwargs["model"] == "gemma3:1b"
    assert fake.chat_kwargs["options"] == {"temperature": 0.1}


def test_stream_chat_wraps_connection_error() -> None:
    fake = _FakeClient(chat_exc=ConnectionError("refused"))
    with pytest.raises(OllamaUnavailableError):
        list(
            OllamaClient(_settings(), client=fake).stream_chat(
                [{"role": "user", "content": "hi"}],
            ),
        )


def test_stream_chat_passes_through_other_errors() -> None:
    fake = _FakeClient(chat_exc=ValueError("boom"))
    with pytest.raises(ValueError):
        list(
            OllamaClient(_settings(), client=fake).stream_chat(
                [{"role": "user", "content": "hi"}],
            ),
        )
