"""The judge-comparison pre-flight record — pure arithmetic and disk reads, never a model call.

Two properties carry the weight here. First, the budget's correctness predicate is pinned to the
acceptance scorer's `act_correct` on the real frozen artifacts, so the calls are counted under the same
collapse the run will be scored by rather than under a second implementation of it. Second, an
unreadable model listing raises instead of reporting the snapshot as retired: the pre-flight is a
stop-loss, and a stop-loss that fires on a network error is worse than none.
"""

from __future__ import annotations

import hashlib
import inspect
import json
from pathlib import Path

import pytest

from clearway.eval.judge_preflight import (
    BASE_URL_ENV,
    DEFAULT_PASSES,
    JUDGE_ROW_FIELDS,
    MODELS_ENDPOINT,
    CallBudget,
    SnapshotListingUnavailable,
    account_model_ids,
    build_record,
    call_budget,
    conformance_correct,
    judge_attempts_per_call,
    judge_pins,
    judge_row_retention,
    provider_route,
    record_digest,
    snapshot_availability,
)
from clearway.eval.offline import _judged_drafts
from clearway.schemas.models import Conformance

_RUNS = Path(__file__).resolve().parent.parent / "benchmark" / "runs"
_FROZEN = _RUNS / "citation_grounding_run_1.json"


def _artifact(path: Path) -> dict:
    return json.loads(path.read_text())


# --- the correctness predicate, pinned to the scorer that already implements it -----------------


@pytest.mark.parametrize("name", ["run_1.json", "run_2.json", "run_3.json"])
def test_conformance_correct_matches_the_acceptance_scorer(name: str) -> None:
    """`conformance_correct` must agree with `offline._judged_drafts`' `act_correct` row for row.

    The budget is counted with one predicate and the run scored with another; if they ever disagree the
    conformance-flip denominator describes a rule nothing else uses.
    """
    artifact = _artifact(_RUNS / name)
    mine = [
        conformance_correct(Conformance(d["conformance"]), c["expected"])
        for c in artifact["cases"]
        for d in c["drafts"]
    ]
    assert mine == [j.act_correct for j in _judged_drafts(artifact)]


def test_conformance_correct_collapses_partial_as_a_flag_by_default() -> None:
    assert conformance_correct(Conformance.PARTIALLY_SUPPORTS, "failed") is True
    assert conformance_correct(Conformance.PARTIALLY_SUPPORTS, "passed") is False
    assert conformance_correct(Conformance.PARTIALLY_SUPPORTS, "failed", partial_flags=False) is False


def test_conformance_correct_reads_clean_verdicts_against_a_passed_case() -> None:
    assert conformance_correct(Conformance.SUPPORTS, "passed") is True
    assert conformance_correct(Conformance.NOT_APPLICABLE, "passed") is True
    assert conformance_correct(Conformance.DOES_NOT_SUPPORT, "passed") is False


# --- the budget --------------------------------------------------------------------------------


def test_budget_arithmetic_charges_both_mutations_on_their_own_denominators() -> None:
    budget = CallBudget(natural_drafts=10, conformance_correct_drafts=6, passes=3)
    assert budget.anchored_per_pass == 26  # 10 natural + 10 SC-swap + 6 conformance-flip
    assert budget.blind_per_pass == 10
    assert budget.anchored_total == 78
    assert budget.blind_total == 30
    assert budget.grand_total == 108
    assert budget.conformance_correct_share == 0.6


def test_budget_default_passes_is_the_repeat_count_a_noise_floor_needs() -> None:
    assert DEFAULT_PASSES >= 3
    assert CallBudget(natural_drafts=1, conformance_correct_drafts=0).passes == DEFAULT_PASSES


@pytest.mark.parametrize(
    "kwargs",
    [
        {"natural_drafts": 0, "conformance_correct_drafts": 0},
        {"natural_drafts": 5, "conformance_correct_drafts": 6},
        {"natural_drafts": 5, "conformance_correct_drafts": -1},
        {"natural_drafts": 5, "conformance_correct_drafts": 5, "passes": 0},
    ],
)
def test_budget_refuses_an_impossible_shape(kwargs: dict) -> None:
    with pytest.raises(ValueError):
        CallBudget(**kwargs)


def test_frozen_budget_is_the_number_recorded_before_anything_is_spent() -> None:
    """The pre-flight figure, pinned: 54 drafts, 39 of them conformance-correct, 603 judge calls."""
    budget = call_budget(_artifact(_FROZEN))
    assert (budget.natural_drafts, budget.conformance_correct_drafts) == (54, 39)
    assert budget.anchored_per_pass == 147
    assert (budget.anchored_total, budget.blind_total, budget.grand_total) == (441, 162, 603)


# --- the floor, and why 603 is not the number that will be spent --------------------------------


def test_the_headline_total_is_a_floor_and_the_ceiling_is_stated_beside_it() -> None:
    """A retried call is invisible on disk, so a single total would read as the amount spent."""
    budget = call_budget(_artifact(_FROZEN))
    assert budget.max_attempts_per_call == judge_attempts_per_call() == 2
    assert budget.grand_total_ceiling == 1206
    payload = budget.to_dict()
    assert payload["grand_total_is_a_floor"] == 603
    assert "grand_total" not in payload, "a bare `grand_total` key would be read as the amount spent"
    assert "invisible" in payload["retry_visibility"] or "no trace" in payload["retry_visibility"]


def test_the_attempt_count_follows_the_judge_rather_than_a_second_copy_of_it() -> None:
    from clearway.judge import Judge

    retries = inspect.signature(Judge.__init__).parameters["retries"].default
    assert judge_attempts_per_call() == retries + 1


def test_no_judge_harness_overrides_the_retry_count_that_makes_the_floor_a_floor() -> None:
    """The floor assumes the constructor default applies. A harness passing `retries=` would break
    that silently, so it is grepped rather than trusted — the same guard the artifact filenames get."""
    root = Path(__file__).resolve().parent.parent / "clearway"
    offenders = [
        f"{path.relative_to(root)}:{n}"
        for path in sorted(root.rglob("*.py"))
        for n, line in enumerate(path.read_text().splitlines(), start=1)
        if "Judge(" in line and "retries" in line
    ]
    assert offenders == [], (
        f"these call sites set the judge's retry count themselves, so the recorded call floor no longer "
        f"follows the constructor default it was derived from: {offenders}"
    )


def test_budget_dict_states_its_own_arithmetic_and_collapse_rule() -> None:
    payload = call_budget(_artifact(_FROZEN)).to_dict()
    assert payload["arithmetic"] == (
        "anchored = 3 × (54 natural + 54 SC-swap + 39 conformance-flip) = 441; blind = 3 × 54 = 162; "
        "floor = 603; ceiling = 603 × 2 attempts = 1206"
    )
    assert payload["conformance_collapse_rule"] == (
        "FLAGS={does_not_support, partially_supports}; CLEAN={not_applicable, supports}"
    )


# --- what the earlier passes retained ----------------------------------------------------------


@pytest.mark.parametrize("name", ["run_1.json", "run_2.json", "run_3.json"])
def test_the_earlier_judged_passes_kept_every_per_finding_field(name: str) -> None:
    retention = judge_row_retention(_artifact(_RUNS / name))
    assert retention["drafts"] == 63
    assert retention["rows_with_all_judge_fields"] == 63
    assert retention["partial_rows"] == 0
    assert retention["replayable"] is True
    assert retention["fields"] == list(JUDGE_ROW_FIELDS)


def test_the_frozen_drafter_pass_carries_no_judge_output_at_all() -> None:
    """The pass the comparison replays was drafter-only, so there is nothing on it to replay."""
    retention = judge_row_retention(_artifact(_FROZEN))
    assert retention["drafts"] == 54
    assert retention["rows_with_all_judge_fields"] == 0
    assert retention["replayable"] is False


def test_a_half_judged_pass_is_neither_replayable_nor_counted_as_present() -> None:
    artifact = {"cases": [{"drafts": [dict.fromkeys(JUDGE_ROW_FIELDS, True), {"judge_verdict": "correct"}, {}]}]}
    retention = judge_row_retention(artifact)
    assert (retention["drafts"], retention["rows_with_all_judge_fields"], retention["partial_rows"]) == (3, 1, 1)
    assert retention["replayable"] is False


# --- snapshot availability ---------------------------------------------------------------------


def test_snapshot_availability_reports_the_listing_size_beside_the_answer() -> None:
    present = snapshot_availability("m", ("a", "m", "z"))
    assert (present["available"], present["listed_model_count"]) == (True, 3)
    absent = snapshot_availability("m", ("a", "z"))
    assert (absent["available"], absent["listed_model_count"]) == (False, 2)
    assert "no inference" in absent["source"]


def test_an_empty_listing_is_not_evidence_of_retirement() -> None:
    """Absent from nothing must be distinguishable from absent from a real list."""
    assert snapshot_availability("m", ())["listed_model_count"] == 0


def test_a_missing_key_leaves_availability_unknown_rather_than_false(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(SnapshotListingUnavailable, match="UNKNOWN"):
        account_model_ids()


def test_an_unreachable_listing_raises_instead_of_reporting_unavailable() -> None:
    with pytest.raises(SnapshotListingUnavailable, match="UNKNOWN, not False"):
        account_model_ids(endpoint="http://127.0.0.1:1/models", api_key="k", timeout_s=0.05)


# --- the pins and the assembled record ---------------------------------------------------------


def test_judge_pins_read_the_effective_effort_and_name_where_it_came_from(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLEARWAY_JUDGE_EFFORT", "high")
    pins = judge_pins()
    assert pins["reasoning_effort"] == "high"
    assert pins["reasoning_effort_source"] == "CLEARWAY_JUDGE_EFFORT"
    assert "effort=high" in pins["judge_version"]


def test_judge_pins_fall_back_to_the_code_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CLEARWAY_JUDGE_EFFORT", raising=False)
    monkeypatch.delenv("CLEARWAY_JUDGE_MODEL", raising=False)
    pins = judge_pins()
    assert (pins["judge_model"], pins["reasoning_effort"]) == ("gpt-5.6-luna", "medium")
    assert pins["reasoning_effort_source"] == "code default"


def test_the_rubric_hash_the_budget_was_counted_under_is_a_deliberate_tripwire(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """INTENTIONAL PIN, expected to fail the first time the rubric text is edited.

    The pre-flight numbers were counted against this rubric, and the comparison they feed treats the
    rubric as the one thing that changes between configurations. So an edit must not slide in silently:
    when this fails, re-read the pre-flight record rather than retyping the hash — a rubric that moved
    means the baseline's instrument moved with it.
    """
    monkeypatch.delenv("CLEARWAY_JUDGE_EFFORT", raising=False)
    monkeypatch.delenv("CLEARWAY_JUDGE_MODEL", raising=False)
    assert judge_pins()["judge_version"] == "rubric=e396f37f; effort=medium", (
        "the rubric text changed since the pre-flight was recorded — the recorded budget and the "
        "anchored baseline were both counted under the previous rubric, so re-record rather than "
        "updating this expectation in place"
    )


def test_record_states_zero_calls_and_hashes_the_artifact_the_budget_came_from() -> None:
    record = build_record(
        frozen_artifact=_FROZEN,
        prior_passes={"run_1.json": _RUNS / "run_1.json"},
        listed_ids=("gpt-5.6-luna",),
        pins={"judge_model": "gpt-5.6-luna", "reasoning_effort": "medium"},
        created_at="2026-07-29T00:00:00+00:00",
    )
    assert record["model_calls_spent"] == 0
    assert record["judge_snapshot"]["available"] is True
    assert record["call_budget"]["grand_total_is_a_floor"] == 603
    assert record["budget_source"]["sha256"] == hashlib.sha256(_FROZEN.read_bytes()).hexdigest()
    assert record["budget_source"]["eval_set_id"] == "act-acceptance@1"
    assert record["prior_judge_rows"]["run_1.json"]["replayable"] is True


# --- the route the availability answer came from ------------------------------------------------


def test_the_listing_endpoint_follows_the_override_the_judges_provider_would_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stop-loss that queries a different host than the judge calls is not a stop-loss."""
    for name in BASE_URL_ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv(BASE_URL_ENV[0], "http://localhost:4000/v1/")
    route = provider_route()
    assert route["endpoint"] == "http://localhost:4000/v1/models"
    assert route["base_url_override_source"] == BASE_URL_ENV[0]


def test_no_override_leaves_the_default_host_and_says_so(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in BASE_URL_ENV:
        monkeypatch.delenv(name, raising=False)
    route = provider_route()
    assert route == {"base_url_override": None, "base_url_override_source": None, "endpoint": MODELS_ENDPOINT}
    assert snapshot_availability("m", ("m",), route=route)["base_url_override"] is None


def test_availability_records_the_host_that_answered_not_a_constant() -> None:
    route = {
        "base_url_override": "http://proxy:4000/v1",
        "base_url_override_source": "OPENAI_BASE_URL",
        "endpoint": "http://proxy:4000/v1/models",
    }
    answer = snapshot_availability("m", ("m",), route=route)
    assert "http://proxy:4000/v1/models" in answer["source"]
    assert answer["base_url_override_source"] == "OPENAI_BASE_URL"


# --- reproducibility of the frozen record -------------------------------------------------------


def _record(created_at: str, listed_ids: tuple[str, ...] = ("gpt-5.6-luna",)) -> dict:
    return build_record(
        frozen_artifact=_FROZEN,
        prior_passes={"run_1.json": _RUNS / "run_1.json"},
        listed_ids=listed_ids,
        pins={"judge_model": "gpt-5.6-luna", "reasoning_effort": "medium"},
        created_at=created_at,
        route={"base_url_override": None, "base_url_override_source": None, "endpoint": MODELS_ENDPOINT},
    )


def test_a_rebuild_reproduces_everything_except_the_timestamp() -> None:
    """The record's own freeze check. Byte digests cannot serve here — `created_at` moves on every
    rebuild — so a genuine change and a re-run would otherwise be indistinguishable."""
    first, second = _record("2026-07-29T00:00:00+00:00"), _record("2027-01-01T12:00:00+00:00")
    assert first != second
    assert first["reproducible_digest"] == second["reproducible_digest"]
    assert record_digest(first) == first["reproducible_digest"]


def test_the_providers_catalogue_growing_is_not_an_edit_to_this_record() -> None:
    """The freeze check must answer "did THIS record change?", and a live catalogue size cannot.

    `listed_model_count` is read off the provider, so it moves whenever any unrelated model is added or
    retired — and it had already drifted once while inside the digest, which made a re-run and a genuine
    edit the same bytes. It stays in the record as evidence and out of the check.
    """
    small = _record("2026-07-29T00:00:00+00:00", ("gpt-5.6-luna",))
    grown = _record("2026-07-29T00:00:00+00:00", ("gpt-5.6-luna", "some-new-model", "another-one"))
    assert grown["judge_snapshot"]["listed_model_count"] != small["judge_snapshot"]["listed_model_count"]
    assert grown["reproducible_digest"] == small["reproducible_digest"]


def test_the_snapshot_actually_disappearing_still_moves_the_digest() -> None:
    """The exclusion is keyed to the catalogue's SIZE, never to the availability answer it supports."""
    present = _record("2026-07-29T00:00:00+00:00", ("gpt-5.6-luna", "x"))
    retired = _record("2026-07-29T00:00:00+00:00", ("x", "y"))
    assert present["judge_snapshot"]["listed_model_count"] == retired["judge_snapshot"]["listed_model_count"]
    assert retired["judge_snapshot"]["available"] is False
    assert retired["reproducible_digest"] != present["reproducible_digest"]


def test_the_digest_covers_a_change_that_matters() -> None:
    baseline = _record("2026-07-29T00:00:00+00:00")
    moved = {**baseline, "call_budget": {**baseline["call_budget"], "grand_total": 604}}
    assert record_digest(moved) != baseline["reproducible_digest"]


def test_the_record_on_disk_is_the_one_these_numbers_were_counted_from() -> None:
    """Pins the frozen file to the digest of a fresh build, so an edited or stale record fails here
    rather than being read as the pre-flight's answer."""
    from clearway.eval.judge_preflight import _report_path

    on_disk = json.loads(_report_path().read_text())
    assert on_disk["reproducible_digest"] == record_digest(on_disk)
    assert on_disk["call_budget"]["grand_total_is_a_floor"] == 603
    assert on_disk["call_budget"]["grand_total_ceiling"] == 1206
    assert on_disk["model_calls_spent"] == 0
