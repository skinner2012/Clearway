"""The benchmark runner's crash-recovery checkpoint I/O: flush the accumulated run state after each
case, resume from it, skip completed cases. The live run loop isn't unit-testable (needs Ollama +
cloud + pgvector), but the checkpoint helpers it rests on are pure file I/O and asserted here.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from clearway.drafter import Drafter
from clearway.eval.benchmark_build import _done_case_ids, _draft_checked, _read_partial, _write_partial
from clearway.llm import FakeLLMClient
from clearway.schemas.models import Finding


def _state() -> dict:
    return {
        "created_at": "2026-07-15T00:00:00+00:00",
        "cases": [
            {"act_testcase_id": "t1", "expected": "failed", "drafts": [{"conformance": "does_not_support"}]},
            {"act_testcase_id": "t2", "expected": "passed", "drafts": [{"conformance": "supports"}]},
        ],
        "conf_flip": [{"rule_name": "Heading is descriptive", "caught": True}],
        "sc_swaps": [{"rule_name": "Heading is descriptive", "caught": True}],
    }


def test_write_then_read_round_trips(tmp_path: Path) -> None:
    path = tmp_path / "run.partial.json"
    _write_partial(_state(), path)
    assert _read_partial(path) == _state()


def test_read_missing_checkpoint_is_none(tmp_path: Path) -> None:
    assert _read_partial(tmp_path / "absent.json") is None


def test_write_creates_the_output_dir(tmp_path: Path) -> None:
    """A first flush must materialise the benchmark dir, so an early crash still leaves a checkpoint."""
    path = tmp_path / "fresh" / "run.partial.json"
    _write_partial(_state(), path)
    assert path.exists()


def test_done_ids_are_the_completed_cases() -> None:
    assert _done_case_ids(_state()) == {"t1", "t2"}


def test_done_ids_empty_without_a_checkpoint() -> None:
    """No checkpoint → nothing done → a fresh run drafts every case."""
    assert _done_case_ids(None) == set()


def test_draft_checked_aborts_on_a_drafter_fallback() -> None:
    """A silently-degraded drafter (never parses) must fail the acceptance run, not freeze a
    does_not_support@0.0 row that would score as a phantom flag and skew FP/recall."""
    finding = Finding(id="h:x", source_url="file://x", rule_id="image-alt", target="img", help="h")
    with pytest.raises(RuntimeError, match="fell back"):
        _draft_checked(Drafter(FakeLLMClient("not json", "still not json")), finding, [])
    good = '{"conformance":"supports","cited_sc_ids":[],"remediation":"ok","confidence":0.9}'
    assert _draft_checked(Drafter(FakeLLMClient(good)), finding, []).confidence == 0.9
