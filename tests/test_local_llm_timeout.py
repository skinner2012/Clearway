"""Every local chat request is bounded by a timeout.

Without one, a lost response is indistinguishable from slow drafting: the server accepts the request,
never dispatches it, and the client waits in `recv()` with no error and no log line. That stalled a
multi-hour acceptance sweep — the guard here is what turns it into a raised exception the per-case
checkpoint can resume from.

The timeout bounds *waiting*, never sampling, so it cannot change what a reachable model returns. That
is why it is safe to add between frozen runs: at `temperature=0` a draft made with it is byte-identical
to one made without, and the assertions below pin the request shape that carries that property
(temperature still 0, structured output still requested, the `ollama_chat/` prefix still used).
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import BaseModel

from clearway.llm import LocalLLMClient
from clearway.llm.local import _DEFAULT_TIMEOUT_S


class _Schema(BaseModel):
    ok: bool


class _Message:
    content = '{"ok": true}'


class _Choice:
    message = _Message()


class _FakeResponse:
    """The minimal shape `complete_json` reads off a LiteLLM response."""

    choices = (_Choice(),)
    usage = None


@pytest.fixture
def captured(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Capture the kwargs `complete_json` hands to LiteLLM, without making a call."""
    seen: dict[str, Any] = {}

    def _fake_completion(**kwargs: Any) -> _FakeResponse:
        seen.update(kwargs)
        return _FakeResponse()

    import litellm

    monkeypatch.setattr(litellm, "completion", _fake_completion)
    return seen


def test_a_timeout_is_always_sent(captured: dict[str, Any]) -> None:
    """The bound travels on every request — an unbounded call is the failure mode this prevents."""
    LocalLLMClient().complete_json("sys", "user", _Schema)
    assert captured["timeout"] == _DEFAULT_TIMEOUT_S


def test_the_default_is_generous_enough_not_to_truncate_honest_drafting() -> None:
    """It must fire only on a stall. The slowest observed real draft is ~3 min on the longest
    injected prompt, so a bound below that would abort work that was going to succeed."""
    assert _DEFAULT_TIMEOUT_S >= 600.0


def test_the_timeout_is_configurable_by_env_and_argument(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLEARWAY_CHAT_TIMEOUT_S", "42")
    assert LocalLLMClient().timeout_s == 42.0
    assert LocalLLMClient(timeout_s=7.5).timeout_s == 7.5


def test_bounding_the_wait_does_not_change_the_sampling_contract(captured: dict[str, Any]) -> None:
    """The reason this is safe to add between two frozen runs: temperature, structured output and the
    provider prefix are untouched, so a reachable model returns exactly what it returned before."""
    LocalLLMClient().complete_json("sys", "user", _Schema)
    assert captured["temperature"] == 0.0
    assert captured["response_format"] is _Schema
    assert captured["model"].startswith("ollama_chat/")
