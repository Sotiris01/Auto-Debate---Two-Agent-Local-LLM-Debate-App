"""
llm.py — Thin, mockable wrapper around the Ollama Python client.

Part of the Auto Debate project. See PROJECT.md and ROADMAP.md.

Phase 4: transport + error translation only. No business logic, no prompt
construction, no debate state — those live in :mod:`engine` / :mod:`prompts`.
The wrapper exists so the rest of the app can be tested without spinning up
a real Ollama server.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Iterator
from typing import Any

import ollama

from config import Settings

__all__ = [
    "ModelNotFoundError",
    "OllamaClient",
    "OllamaUnavailableError",
    "chat_options",
]

_log = logging.getLogger(__name__)


class OllamaUnavailableError(RuntimeError):
    """Raised when the Ollama server is unreachable (connection refused, DNS, timeout)."""


class ModelNotFoundError(RuntimeError):
    """Raised when the configured model is not present locally.

    The message always includes the exact ``ollama pull <model>`` command so
    the UI can surface it verbatim.
    """

    def __init__(self, model_name: str) -> None:
        self.model_name = model_name
        super().__init__(
            f"Model {model_name!r} is not available on this Ollama server. "
            f"Pull it with: ollama pull {model_name}",
        )


# Heuristic: ~1.5 tokens per word, plus a small headroom so the model can
# finish a sentence without being cut mid-word. The cap stops runaway
# generations regardless of the prompt.
def _num_predict_for(word_limit: int) -> int:
    return max(64, int(word_limit * 1.7) + 32)


def chat_options(settings: Settings) -> dict[str, Any]:
    """Build the ``options`` dict passed to ``ollama.Client.chat``."""
    return {
        "temperature": settings.temperature,
        "top_p": settings.top_p,
        "num_predict": _num_predict_for(settings.word_limit),
    }


def _is_connection_error(exc: BaseException) -> bool:
    """True when ``exc`` looks like 'Ollama is not reachable'."""
    if isinstance(exc, (ConnectionError, TimeoutError)):
        return True
    # The ollama-python client wraps httpx errors in RequestError /
    # ResponseError. Anything from httpx with a connect/timeout cause counts.
    name = type(exc).__name__
    if name in {"ConnectError", "ConnectTimeout", "ReadTimeout", "RemoteProtocolError"}:
        return True
    cause = getattr(exc, "__cause__", None)
    if cause is not None and cause is not exc:
        return _is_connection_error(cause)
    return False


def _model_names(list_response: Any) -> list[str]:
    """Extract model name strings from a ``client.list()`` response.

    Tolerates both the modern Pydantic ``ListResponse`` (``.models[i].model``)
    and the legacy dict shape (``{"models": [{"name": "..."}]}``).
    """
    models = getattr(list_response, "models", None)
    if models is None and isinstance(list_response, dict):
        models = list_response.get("models", [])
    if not models:
        return []
    out: list[str] = []
    for m in models:
        name = getattr(m, "model", None) or getattr(m, "name", None)
        if name is None and isinstance(m, dict):
            name = m.get("model") or m.get("name")
        if isinstance(name, str):
            out.append(name)
    return out


class OllamaClient:
    """Thin wrapper around :class:`ollama.Client`.

    The constructor accepts either a :class:`Settings` (preferred) or, for
    tests, an already-constructed ``client`` instance.
    """

    def __init__(
        self,
        settings: Settings,
        *,
        client: Any | None = None,
    ) -> None:
        self.settings = settings
        self._client: Any = (
            client if client is not None else ollama.Client(host=settings.ollama_host)
        )

    # --- model availability -------------------------------------------------

    def ensure_model_available(self, model_name: str | None = None) -> None:
        """Verify ``model_name`` is present on the server.

        Raises:
            OllamaUnavailableError: if the server is unreachable.
            ModelNotFoundError: if the model is not in ``client.list()``.
        """
        name = model_name or self.settings.model_name
        try:
            response = self._client.list()
        except Exception as exc:
            if _is_connection_error(exc):
                raise OllamaUnavailableError(
                    f"Ollama is not reachable at {self.settings.ollama_host}. "
                    "Start it (e.g. `ollama serve`) and try again.",
                ) from exc
            raise

        names = _model_names(response)
        if name not in names:
            raise ModelNotFoundError(name)

    # --- chat streaming -----------------------------------------------------

    def stream_chat(
        self,
        messages: Iterable[dict[str, Any]],
        *,
        options: dict[str, Any] | None = None,
        model: str | None = None,
    ) -> Iterator[str]:
        """Stream assistant content chunks from ``client.chat``.

        Yields the ``message.content`` field of each chunk only. Connection
        problems are translated into :class:`OllamaUnavailableError`.
        """
        target_model = model or self.settings.model_name
        opts = options if options is not None else chat_options(self.settings)
        msg_list = list(messages)
        request_chars = sum(len(str(m.get("content", ""))) for m in msg_list)
        _log.debug(
            "chat request: model=%s messages=%d request_chars=%d options=%s",
            target_model,
            len(msg_list),
            request_chars,
            opts,
        )
        response_chars = 0
        chunk_count = 0
        try:
            stream = self._client.chat(
                model=target_model,
                messages=msg_list,
                stream=True,
                options=opts,
            )
            for chunk in stream:
                content = _chunk_content(chunk)
                if content:
                    response_chars += len(content)
                    chunk_count += 1
                    yield content
        except (OllamaUnavailableError, ModelNotFoundError):
            raise
        except Exception as exc:
            if _is_connection_error(exc):
                raise OllamaUnavailableError(
                    f"Ollama is not reachable at {self.settings.ollama_host}. "
                    "Start it (e.g. `ollama serve`) and try again.",
                ) from exc
            raise
        finally:
            _log.debug(
                "chat response: model=%s chunks=%d response_chars=%d",
                target_model,
                chunk_count,
                response_chars,
            )


def _chunk_content(chunk: Any) -> str:
    """Extract ``message.content`` from a streaming chat chunk.

    Tolerates both Pydantic ``ChatResponse`` and dict-shaped chunks.
    """
    msg = getattr(chunk, "message", None)
    if msg is None and isinstance(chunk, dict):
        msg = chunk.get("message")
    if msg is None:
        return ""
    content = getattr(msg, "content", None)
    if content is None and isinstance(msg, dict):
        content = msg.get("content")
    return content or ""
