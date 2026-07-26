"""Send the captured bytes, bare, to the model — and confirm the three discriminations survive capture.

The pool turns on three visual facts and nothing else: that one picture is the W3C logo, that another
is a Copenhagen waterfront and not Paris, and that the third is bread. Those were established on the
*asset files* before any of this was built. This asks the same three questions of the bytes that came
back out of the **capture path** — the response the browser fetched, stored content-addressed, read
back through `ImageStore` and declared with a media type sniffed from the bytes.

Why it is worth three calls: without it, a later condition that comes out flat has two explanations
that cannot be told apart — the plumbing delivered nothing, or the plumbing delivered a picture the
capture had already ruined. This separates them in advance, cheaply, on data that is not held out
(the same three pictures were already spent on the pre-spec probe).

**Bare, deliberately.** No page, no finding, no pipeline system prompt, no candidate criteria — one
image and one open question, identical for all three. An open question rather than "is this the W3C
logo?", because a leading question is answerable by a model that saw nothing at all.

The reads are **pre-registered below, before the run**: what an answer must contain to count as
resolving each discrimination, and — for the photograph, whose whole point is that it is not Paris —
what it must not. A raw answer that resolves the discrimination while missing the tokens is reported
as it came out and judged by a human; it is not fixed by widening the list afterwards.

    uv run python scripts/probe_captured_images.py

Three model calls against the local stack, declared in the receipt and in the milestone's run count.
"""

from __future__ import annotations

import base64
import json
import os
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from clearway.eval.image_capture import ARTIFACT, STORE_DIR
from clearway.eval.image_opaque import ACT_IMAGE_OPAQUE
from clearway.llm.local import LocalLLMClient
from clearway.scanner.capture import ImageStore

RECEIPT = Path(__file__).resolve().parents[1] / "benchmark" / "reports" / "captured_image_discrimination.json"

# One question, asked of every picture, with no hint of what any of them might be.
_USER_TEXT = "Name what this image actually shows. Be specific: if it is a place, name the place."

_SYSTEM_PROMPT = "You describe images accurately. Answer only about the image you are shown."


class _ImageDescription(BaseModel):
    """The smallest schema that still forces structured output — this probe asks one thing."""

    description: str = Field(..., description="what the image shows")


# THE PRE-REGISTRATION. Per image label: what a resolving answer must say, and what it must not.
# `must_contain` is satisfied by ANY one token (they are synonyms for one fact, not a checklist).
DISCRIMINATIONS: dict[str, dict[str, Any]] = {
    "w3c-logo": {
        "discrimination": "the picture is the W3C logo",
        "must_contain": ["w3c", "world wide web consortium"],
        "must_not_contain": [],
    },
    "nyhavn": {
        "discrimination": "the picture is a Copenhagen waterfront, and is not Paris",
        "must_contain": ["nyhavn", "copenhagen", "denmark", "danish", "canal", "harbour", "harbor", "waterfront"],
        "must_not_contain": ["paris"],
    },
    "bread": {
        "discrimination": "the picture is bread",
        "must_contain": ["bread", "loaf", "loaves", "baguette", "boule", "bakery", "sourdough"],
        "must_not_contain": [],
    },
}


def resolves(description: str, expectation: dict[str, Any]) -> bool:
    """Whether one answer resolves one discrimination, read exactly as pre-registered above."""
    said = description.lower()
    return any(token in said for token in expectation["must_contain"]) and not any(
        token in said for token in expectation["must_not_contain"]
    )


def _model_digest(base_url: str, model: str) -> str | None:
    """The served model's digest — provenance continuity with every run before this. Best-effort: a
    metadata request, never worth failing the probe over."""
    try:
        with urllib.request.urlopen(f"{base_url}/api/tags", timeout=30) as response:  # noqa: S310  # local URL
            served = json.loads(response.read())["models"]
        return next(str(entry["digest"])[:12] for entry in served if entry["name"] == model)
    except Exception:  # noqa: BLE001 — provenance is best-effort; the probe's result does not depend on it
        return None


def _ask(client: LocalLLMClient, base_url: str, image: bytes, media_type: str) -> dict[str, Any]:
    """One call: the picture as a `data:` URI whose type came from the bytes, and one open question."""
    import litellm

    encoded = base64.b64encode(image).decode()
    started = time.perf_counter()
    response = litellm.completion(
        model=f"ollama_chat/{client.model}",
        api_base=base_url,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": _USER_TEXT},
                    {"type": "image_url", "image_url": {"url": f"data:{media_type};base64,{encoded}"}},
                ],
            },
        ],
        response_format=_ImageDescription,
        temperature=0.0,
        timeout=client.timeout_s,
    )
    latency_ms = (time.perf_counter() - started) * 1000.0
    content: str = response.choices[0].message.content or ""
    try:
        described: str | None = _ImageDescription.model_validate_json(content).description
        error: str | None = None
    except ValidationError as invalid:
        described, error = None, str(invalid)
    return {
        "content": content,
        "description": described,
        "validation_error": error,
        "latency_ms": round(latency_ms, 1),
        "tokens_in": getattr(response.usage, "prompt_tokens", None),
        "tokens_out": getattr(response.usage, "completion_tokens", None),
    }


def main() -> None:
    frozen = json.loads(ARTIFACT.read_text())
    store = ImageStore(ACT_IMAGE_OPAQUE / STORE_DIR)
    ref_of_label = {capture["image"]: capture["image_ref"] for capture in frozen["captures"]}
    client = LocalLLMClient()
    base_url = os.getenv("CLEARWAY_OLLAMA_BASE_URL") or "http://localhost:11434"

    results: list[dict[str, Any]] = []
    for label, expectation in DISCRIMINATIONS.items():
        ref = ref_of_label[label]
        image = store.read(ref)  # read back through the store — the digest is re-verified on the way out
        media_type = store.media_type(ref)
        answer = _ask(client, base_url, image, media_type)
        results.append(
            {
                "image": label,
                "image_ref": ref,
                "media_type": media_type,
                "bytes": len(image),
                "discrimination": expectation["discrimination"],
                "must_contain": expectation["must_contain"],
                "must_not_contain": expectation["must_not_contain"],
                "resolved": answer["description"] is not None and resolves(answer["description"], expectation),
                **answer,
            }
        )
        print(f"  {label:<9} {media_type:<11} {'RESOLVED' if results[-1]['resolved'] else 'NOT RESOLVED'}")
        print(f"    {answer['description']!r}")

    receipt = {
        "probe": "the three pool discriminations, asked of the CAPTURED bytes",
        "ran_at": datetime.now(timezone.utc).isoformat(),
        "model": client.model,
        "model_digest": _model_digest(base_url, client.model),
        "provider_prefix": "ollama_chat/",
        "model_calls_spent": len(results),
        "schema": _ImageDescription.__name__,
        "temperature": 0.0,
        "source": {"artifact": str(ARTIFACT.relative_to(Path.cwd())), "store": STORE_DIR},
        "question": _USER_TEXT,
        "system_prompt": _SYSTEM_PROMPT,
        "note": (
            "Bare: one image, one open question, no page and no pipeline prompt. The reads were "
            "pre-registered before the run (must_contain / must_not_contain, carried on each row) "
            "so the answers could not be scored after the fact. The media type on every data: URI "
            "was sniffed from the bytes, never from the deliberately-uniform `.png` file names — "
            "two of these three pictures are JPEG. This separates 'the capture destroyed it' from "
            "'the plumbing delivered nothing' for every later condition."
        ),
        "all_resolved": all(row["resolved"] for row in results),
        "results": results,
    }
    RECEIPT.write_text(json.dumps(receipt, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {RECEIPT.relative_to(Path.cwd())} — all_resolved={receipt['all_resolved']}")
    if not receipt["all_resolved"]:
        raise SystemExit("a discrimination did not resolve on the captured bytes — read the raw answers before acting")


if __name__ == "__main__":
    main()
