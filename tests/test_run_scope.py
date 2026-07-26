"""The harness's scope as a value: which cases, which classes, how they mint, what identity they stamp.

Every module under `eval/` grew around one case set, and never wrote it down — it lived in a module-level
manifest path, a default argument and a pair of module constants. So the case set a builder drafted and
the identity it froze into the artifact were both inherited silently, and a builder pointed at a
different gold set drafted the acceptance 44 and stamped the acceptance run's identity on the result.

These tests pin the scope as something a call site names: the acceptance scope still selects exactly what
it always selected, the image scope selects the image pool and nothing else, and each carries its own
provenance. The refusals that fall out of an explicit scope live in `test_scope_refusals`.
"""

from __future__ import annotations

import json

import pytest

from clearway.eval import run_scope
from clearway.eval.act_gold import RULE_TO_AXE
from clearway.eval.image_reachability import HTML, IMAGE_AXE_RULE
from clearway.eval.run_scope import ACCEPTANCE, IMAGE_LEAKY, OutOfScope


def test_the_acceptance_scope_reproduces_the_frozen_acceptance_provenance() -> None:
    # The literals every already-frozen artifact carries. If these move, the dry gate's environment
    # check goes red on runs that cannot be re-run.
    assert ACCEPTANCE.config_id == "m1-single@1"
    assert ACCEPTANCE.eval_set_id == "act-acceptance@1"
    assert set(ACCEPTANCE.axe_rules) == set(RULE_TO_AXE.values())


def test_the_image_scope_carries_its_own_provenance_never_the_acceptance_one() -> None:
    # Stamping the acceptance ids on an image run would freeze false provenance into every artifact.
    assert IMAGE_LEAKY.config_id == "single-multimodal@1"
    assert IMAGE_LEAKY.eval_set_id == "act-image-leaky@1"
    assert IMAGE_LEAKY.axe_rules == (IMAGE_AXE_RULE,)
    assert (IMAGE_LEAKY.config_id, IMAGE_LEAKY.eval_set_id) != (ACCEPTANCE.config_id, ACCEPTANCE.eval_set_id)


def test_the_derived_opaque_sets_id_is_reserved_and_distinct_from_the_vendored_one() -> None:
    assert run_scope.OPAQUE_EVAL_SET_ID == "act-image-opaque@1"
    assert run_scope.OPAQUE_EVAL_SET_ID != IMAGE_LEAKY.eval_set_id


def test_the_acceptance_scope_selects_the_forty_four_cases_the_gate_asserts() -> None:
    assert len(run_scope.cases_for(ACCEPTANCE)) + len(run_scope.honest_misses_for(ACCEPTANCE)) == 44


def test_the_image_scope_selects_the_seven_pool_cases_and_none_of_the_acceptance_ones() -> None:
    # A builder that inherits its case set from a module global drafts the acceptance 44. With the scope
    # named at the call site, the image scope can only ever yield the image pool.
    image = run_scope.cases_for(IMAGE_LEAKY)
    assert len(image) == 7
    acceptance_ids = {c["act_testcase_id"] for c in run_scope.cases_for(ACCEPTANCE)}
    assert not {c["act_testcase_id"] for c in image} & acceptance_ids


def test_the_image_scope_carries_no_honest_misses() -> None:
    # The image manifest has no honest-miss list at all; a `.get(..., [])` would render that identically
    # to a set that has them and happens to be empty, so the scope declares which it is.
    assert run_scope.honest_misses_for(IMAGE_LEAKY) == []
    assert IMAGE_LEAKY.carries_honest_misses is False
    assert ACCEPTANCE.carries_honest_misses is True


def test_the_pass_provenance_is_stamped_from_the_named_scope() -> None:
    # The ids used to come from the acceptance builder's module globals, so an image pass would have
    # frozen `m1-single@1` / `act-acceptance@1` into its own artifact.
    provenance = IMAGE_LEAKY.provenance(
        run_ids=["image-leaky-pass1"],
        corpus_version="corpus@1",
        drafter_model="gemma4:31b",
        drafter_model_digest="deadbeef",
        created_at="2026-07-26T00:00:00+00:00",
    )
    assert provenance["config_id"] == "single-multimodal@1"
    assert provenance["eval_set_id"] == "act-image-leaky@1"
    assert provenance["run_ids"] == ["image-leaky-pass1"]


def test_the_image_scope_mints_through_the_asset_threading_helper() -> None:
    from clearway.eval.act_gold import _minting_findings as unsafe

    assert IMAGE_LEAKY.minting_findings is not unsafe
    with pytest.raises(OutOfScope, match="document-title"):
        IMAGE_LEAKY.minting_findings(HTML / "x.html", "document-title")


def test_every_image_pool_case_resolves_under_its_scope() -> None:
    manifest = json.loads(IMAGE_LEAKY.manifest.read_text())
    for case in manifest["cases"]:
        assert (IMAGE_LEAKY.root / case["path"]).exists()
