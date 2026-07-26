"""Probe the one link in the image path that nothing has ever exercised: LiteLLM.

`LocalLLMClient.complete_json` reaches the local model through `litellm.completion(model=
"ollama_chat/…")` with a `response_format` schema, and that module's own docstring records that the
sibling `ollama/` prefix **silently drops structured output and returns markdown**. So the provider
layer is known to be lossy in exactly the way that would be invisible here: an image part it does not
understand can be dropped without an error, leaving a request that looks fine, parses fine, and
carries no picture.

Nothing establishes that this provider carries a multimodal content part, a `response_format` schema
and the model's own thinking in ONE request — the earlier hand probe went straight to Ollama's
`/api/chat` and bypassed LiteLLM entirely. This issues exactly one request through the real client
path, with the real `_LLMDraft` schema, and freezes what came back.

    uv run python scripts/probe_multimodal_litellm.py

One model call, against the local stack, declared in the run count. If it fails, wiring the image
into the drafter is a different ticket — bypass or patch LiteLLM — and that has to be settled before
a measured pass is spent on it.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import time
import urllib.request
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from clearway.drafter.llm import _LLMDraft, _system_prompt
from clearway.eval.image_reachability import ASSETS
from clearway.llm.local import LocalLLMClient

RECEIPT = Path(__file__).resolve().parents[1] / "benchmark" / "reports" / "multimodal_transport_probe.json"

# The W3C logo: one of the pool's three images, and one the earlier hand probe already spent, so this
# probe puts no new held-out case at risk. It is 1 927 bytes, which keeps the request small.
PROBE_IMAGE = ASSETS / "test-assets" / "shared" / "w3c-logo.png"

# Deliberately not the pipeline's finding prompt. The question here is whether the TRANSPORT carries
# the parts, so the request is the smallest one that still uses the real schema and the real system
# prompt; running the real per-finding prompt is the wiring ticket's smoke test, not this.
_USER_TEXT = (
    "An image is attached. Name what the image actually shows in the remediation field, then draft "
    "the verdict for an alt-text quality review of it. Candidate WCAG success criteria: 1.1.1."
)


# One earlier attempt reached the model and came back before this script crashed while writing its
# receipt — an attribute error, not a transport failure, but it cost a real call. Declared here rather
# than dropped from the run count, because a spend that leaves no artifact is the easiest kind to lose.
_CALLS_ALREADY_SPENT = 1


def _model_digest(base_url: str, model: str) -> str | None:
    """The served model's digest, for provenance continuity with the runs that came before. A
    metadata request, not an inference one — and best-effort, like usage: never worth failing over."""
    try:
        with urllib.request.urlopen(f"{base_url}/api/tags", timeout=30) as response:  # noqa: S310  # local URL
            served = json.loads(response.read())["models"]
        return next(str(entry["digest"])[:12] for entry in served if entry["name"] == model)
    except Exception:  # noqa: BLE001 — provenance is best-effort; the probe's result does not depend on it
        return None


def _multimodal_user_content(image: bytes, media_type: str) -> list[dict[str, Any]]:
    """The OpenAI-shaped content-part list LiteLLM translates for the provider. `base64` is stdlib —
    carrying an image adds no dependency."""
    encoded = base64.b64encode(image).decode()
    return [
        {"type": "text", "text": _USER_TEXT},
        {"type": "image_url", "image_url": {"url": f"data:{media_type};base64,{encoded}"}},
    ]


def main() -> None:
    import litellm

    client = LocalLLMClient()
    base_url = os.getenv("CLEARWAY_OLLAMA_BASE_URL") or "http://localhost:11434"
    image = PROBE_IMAGE.read_bytes()
    started = time.perf_counter()
    response = litellm.completion(
        model=f"ollama_chat/{client.model}",
        api_base=base_url,
        messages=[
            {"role": "system", "content": _system_prompt()},
            {"role": "user", "content": _multimodal_user_content(image, "image/png")},
        ],
        response_format=_LLMDraft,
        temperature=0.0,
        timeout=client.timeout_s,
    )
    latency_ms = (time.perf_counter() - started) * 1000.0
    message = response.choices[0].message
    content: str = message.content or ""

    try:
        draft = _LLMDraft.model_validate_json(content)
        parsed: dict[str, Any] | None = draft.model_dump(mode="json")
        error: str | None = None
    except ValidationError as invalid:
        parsed, error = None, str(invalid)

    receipt = {
        "probe": "multimodal transport through LiteLLM to the local chat model",
        "ran_at": datetime.now(timezone.utc).isoformat(),
        "model": client.model,
        "model_digest": _model_digest(base_url, client.model),
        "provider_prefix": "ollama_chat/",
        "litellm_version": version("litellm"),
        "model_calls_spent": _CALLS_ALREADY_SPENT + 1,
        "schema": _LLMDraft.__name__,
        "temperature": 0.0,
        "image": {
            "path": str(PROBE_IMAGE.relative_to(Path.cwd())),
            "bytes": len(image),
            "sha256": hashlib.sha256(image).hexdigest(),
            "media_type": "image/png",
        },
        "schema_valid_json_returned": parsed is not None,
        "validation_error": error,
        "content": content,
        "parsed": parsed,
        # Descriptive, never a gate: whether the model's own words show it saw the picture. The
        # transport question is answered by `schema_valid_json_returned` alone.
        "reasoning_returned": bool(getattr(message, "reasoning_content", None)),
        "latency_ms": round(latency_ms, 1),
        "tokens_in": getattr(response.usage, "prompt_tokens", None),
        "tokens_out": getattr(response.usage, "completion_tokens", None),
    }
    RECEIPT.write_text(json.dumps(receipt, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {RECEIPT.relative_to(Path.cwd())}")
    print(json.dumps({k: v for k, v in receipt.items() if k != "content"}, indent=2, ensure_ascii=False))
    if parsed is None:
        raise SystemExit("the provider did not return schema-valid JSON for a multimodal request")


if __name__ == "__main__":
    main()
