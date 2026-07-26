"""Guard for the frozen captured-image discrimination receipt.

The receipt answers a question no offline code can: do the three visual facts this pool turns on
survive the capture path? They were established on the asset files before any capture existed; the
receipt records them being re-established on the bytes that came back out of the store.

What is checked here is that the answer still belongs to the model the client actually uses, that
the reads were the ones pre-registered, and that the pictures asked about are the ones the capture
froze — a probe whose subject drifted from the artifact would otherwise keep reporting a "yes" it
never established for what will actually be sent.

No model call. Re-establish the receipt with `uv run python scripts/probe_captured_images.py`.
"""

from __future__ import annotations

import json
from pathlib import Path

from clearway.eval.image_capture import ARTIFACT, STORE_DIR
from clearway.eval.image_opaque import POOL_IMAGES
from clearway.llm.local import _DEFAULT_MODEL
from scripts.probe_captured_images import DISCRIMINATIONS, resolves

RECEIPT = json.loads(
    (
        Path(__file__).resolve().parent.parent / "benchmark" / "reports" / "captured_image_discrimination.json"
    ).read_text()
)


def test_all_three_discriminations_resolved_on_the_captured_bytes() -> None:
    assert RECEIPT["all_resolved"] is True
    assert len(RECEIPT["results"]) == 3
    assert all(row["resolved"] and row["validation_error"] is None for row in RECEIPT["results"])


def test_the_probe_asked_about_the_pictures_the_capture_actually_froze() -> None:
    """The subject is pinned to the frozen artifact, not merely to three plausible images."""
    frozen = json.loads(ARTIFACT.read_text())
    captured = {capture["image"]: capture["image_ref"] for capture in frozen["captures"]}

    assert {row["image"]: row["image_ref"] for row in RECEIPT["results"]} == captured
    assert {row["image_ref"] for row in RECEIPT["results"]} == set(POOL_IMAGES.values())
    assert RECEIPT["source"] == {"artifact": str(ARTIFACT.relative_to(Path.cwd())), "store": STORE_DIR}


def test_the_media_type_sent_came_from_the_bytes_and_not_the_png_names() -> None:
    """Two of the three assets are JPEG behind a `.png` name; a `data:` URI that said otherwise
    would be the one lie in this pipeline that nothing downstream can detect."""
    sent = {row["image"]: row["media_type"] for row in RECEIPT["results"]}

    assert sent == {"w3c-logo": "image/png", "nyhavn": "image/jpeg", "bread": "image/jpeg"}


def test_the_reads_were_the_ones_pre_registered() -> None:
    """The receipt carries the accept/reject tokens each row was scored against, and re-scoring the
    raw answers with today's `resolves` reproduces every verdict — so a list widened after the fact
    would show up as a receipt that no longer matches the code that wrote it."""
    for row in RECEIPT["results"]:
        expectation = DISCRIMINATIONS[row["image"]]
        assert row["must_contain"] == expectation["must_contain"]
        assert row["must_not_contain"] == expectation["must_not_contain"]
        assert resolves(row["description"], expectation) is row["resolved"]

    # the photograph's whole point: it is a Copenhagen waterfront, and specifically not Paris
    nyhavn = next(row for row in RECEIPT["results"] if row["image"] == "nyhavn")
    assert "paris" not in nyhavn["description"].lower()


def test_the_probe_ran_on_the_model_the_client_uses_and_declared_its_spend() -> None:
    assert RECEIPT["model"] == _DEFAULT_MODEL
    assert RECEIPT["provider_prefix"] == "ollama_chat/"  # `ollama/` silently drops structured output
    assert RECEIPT["temperature"] == 0.0
    assert RECEIPT["model_digest"], "the served digest is the provenance link to the runs before this"
    assert RECEIPT["model_calls_spent"] == 3
