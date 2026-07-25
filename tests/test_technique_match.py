"""Remediation fix-direction: the technique gold read off the ACT export, the classifier seam (faked —
no network), and the chance-corrected scorer.

The load-bearing test is `test_constant_classifier_scores_kappa_zero_at_high_raw_agreement`: technique
gold is rule-level, so a classifier that answers one id for everything is the failure mode this metric
exists to survive. If κ ever stops catching it, the metric is decorative.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from clearway.eval.technique_match import (
    NO_TECHNIQUE,
    RemediationDraft,
    TechniqueClassification,
    classification_rows,
    classification_schema,
    classifier_system_prompt,
    classify,
    classify_all,
    coverage_note,
    covered_classes,
    score_technique_match,
    scoreable,
    technique_gold_by_class,
    technique_vocabulary,
    uncovered_classes,
)
from clearway.llm.client import Completion, FakeLLMClient
from clearway.schemas.models import Citation, Conformance, DraftRow

LABEL_GOLD = "G131"
TITLE_GOLD = ("G88", "H25")


def _classified(axe_rule: str, inferred: str, i: int) -> TechniqueClassification:
    return TechniqueClassification(
        act_testcase_id=f"{axe_rule}-{i}",
        axe_rule=axe_rule,
        remediation=f"fix {i}",
        inferred_technique=inferred,
    )


def _mixed_set(label_answers: list[str], title_answers: list[str]) -> list[TechniqueClassification]:
    return [_classified("label", a, i) for i, a in enumerate(label_answers)] + [
        _classified("document-title", a, i) for i, a in enumerate(title_answers)
    ]


# --- the gold, read off the vendored export -------------------------------------------------------


def test_technique_gold_covers_exactly_label_and_document_title() -> None:
    """Coverage is 2 of the 4 scored classes, and it is DERIVED: label requires G131, document-title
    accepts either G88 or H25, and the other two classes declare no technique requirement at all."""
    gold = technique_gold_by_class()
    assert gold == {"document-title": TITLE_GOLD, "label": (LABEL_GOLD,)}
    assert covered_classes() == ("document-title", "label")
    assert uncovered_classes() == ("empty-heading", "link-name")


def test_coverage_note_states_two_of_four_and_names_the_absent_classes() -> None:
    note = coverage_note()
    assert "2 of 4 scored classes" in note
    assert "empty-heading, link-name" in note and "absent, not passing" in note


def test_vocabulary_is_the_whole_technique_namespace_not_the_scored_codes() -> None:
    """The classifier chooses from every technique id in the export — narrowing it to the three codes
    the scored classes use would hand it the answer."""
    vocabulary = technique_vocabulary()
    assert len(vocabulary) == 42
    assert set(vocabulary) >= {LABEL_GOLD, *TITLE_GOLD}
    assert vocabulary == tuple(sorted(vocabulary))


def test_scoreable_drops_the_classes_with_no_technique_gold() -> None:
    drafts = [
        RemediationDraft(act_testcase_id="a", axe_rule="label", remediation="x"),
        RemediationDraft(act_testcase_id="b", axe_rule="link-name", remediation="y"),
        RemediationDraft(act_testcase_id="c", axe_rule="empty-heading", remediation="z"),
    ]
    assert [d.act_testcase_id for d in scoreable(drafts)] == ["a"]


# --- the acceptance trap --------------------------------------------------------------------------


def test_constant_classifier_scores_kappa_zero_at_high_raw_agreement() -> None:
    """Always answering G131 is right on every label case and wrong on every title case. Raw match
    would call that 0.688 — respectable-looking; κ calls it 0.0, which is the truth."""
    scoring = score_technique_match(_mixed_set([LABEL_GOLD] * 11, [LABEL_GOLD] * 5), classifier_model="fake-classifier")
    assert scoring.metric.kappa == pytest.approx(0.0)
    assert scoring.metric.raw_agreement == pytest.approx(11 / 16)
    assert scoring.metric.constant_classifier is True
    assert scoring.metric.n == 16


def test_a_discriminating_classifier_scores_kappa_one() -> None:
    """Either title technique counts: ACT lists G88 and H25 as alternatives for the same fix, so they
    are one gold category, not two."""
    scoring = score_technique_match(
        _mixed_set([LABEL_GOLD] * 11, ["G88", "H25", "G88", "H25", "G88"]), classifier_model="fake-classifier"
    )
    assert scoring.metric.kappa == pytest.approx(1.0)
    assert scoring.metric.raw_agreement == pytest.approx(1.0)
    # Perfect agreement collapses the interval to a point too, so the constant-classifier flag is read
    # from the answer stream and NOT from the interval width — otherwise it would fire backwards here.
    assert (scoring.metric.ci_low, scoring.metric.ci_high) == (1.0, 1.0)
    assert scoring.metric.constant_classifier is False


def test_an_off_gold_technique_never_matches_but_kappa_still_credits_the_separation() -> None:
    """Strict by design: G130 is a real title technique ACT does not list here, so not one title case
    matches — raw agreement falls to the label cases alone.

    κ is nonetheless POSITIVE (~0.41), and that is κ behaving correctly rather than a leak: a stream
    that answers one id for label fixes and a different one for title fixes has separated the two
    classes, which is what chance-corrected DIRECTION asks. It is also why raw agreement ships beside
    κ — only raw agreement shows that no title case was actually right."""
    scoring = score_technique_match(_mixed_set([LABEL_GOLD] * 11, ["G130"] * 5), classifier_model="fake-classifier")
    assert scoring.metric.raw_agreement == pytest.approx(11 / 16)
    assert scoring.metric.kappa == pytest.approx(0.4074074074, abs=1e-9)


def test_declining_to_infer_is_scored_as_a_disagreement() -> None:
    """`none` is not a free pass: an unclassifiable remediation counts as pointing at no technique."""
    scoring = score_technique_match(
        _mixed_set([LABEL_GOLD] * 11, [NO_TECHNIQUE] * 5), classifier_model="fake-classifier"
    )
    assert scoring.metric.raw_agreement == pytest.approx(11 / 16)
    assert all(not row["agrees"] for row in classification_rows(_mixed_set([], [NO_TECHNIQUE] * 5)))


def test_the_metric_is_reproducible_from_the_same_classifications() -> None:
    """Same classifications in, byte-identical metric out — the bootstrap bounds included, because the
    seed and resample count travel on the metric."""
    rows = _mixed_set([LABEL_GOLD] * 6 + ["G88"] * 5, ["H25"] * 4 + [LABEL_GOLD])
    first = score_technique_match(rows, classifier_model="fake-classifier").metric
    second = score_technique_match(rows, classifier_model="fake-classifier").metric
    assert first.model_dump() == second.model_dump()
    assert (first.seed, first.resamples) == (0, 10_000)
    assert first.ci_low <= first.kappa <= first.ci_high


def test_scoring_an_uncovered_class_raises_rather_than_inventing_gold() -> None:
    with pytest.raises(ValueError, match="carries no technique gold"):
        score_technique_match([_classified("link-name", LABEL_GOLD, 0)], classifier_model="fake-classifier")


def test_scoring_nothing_raises_rather_than_reporting_a_zero() -> None:
    with pytest.raises(ValueError, match="nothing to compare"):
        score_technique_match([], classifier_model="fake-classifier")


def test_notes_report_chance_correction_coverage_and_the_floor_caveat() -> None:
    notes = score_technique_match(_mixed_set([LABEL_GOLD] * 3, ["G88"] * 2), classifier_model="fake").notes
    assert "CHANCE-CORRECTED" in notes and "never the number" in notes
    assert "2 of 4 scored classes" in notes
    assert "floor" in notes and "USEFUL" in notes


def test_classification_rows_carry_the_sentence_and_the_gold_they_were_scored_against() -> None:
    """The audit trail an artifact ships, so κ recomputes from the file without re-calling the model."""
    rows = classification_rows(_mixed_set([LABEL_GOLD], ["G88"]))
    assert [r["agrees"] for r in rows] == [True, True]
    assert rows[1]["gold_techniques"] == list(TITLE_GOLD)
    assert rows[1]["gold_key"] == "G88+H25"
    assert rows[0]["remediation"] == "fix 0"


# --- the classifier seam (faked — never a network call) -------------------------------------------


def test_classify_sends_only_the_remediation_sentence_and_parses_the_answer() -> None:
    """The classifier is told the sentence and nothing else — not the element, the rule, the class or
    the expected outcome — so it cannot read the answer off the case it is scoring."""
    captured: dict[str, str] = {}

    class _Recording(FakeLLMClient):
        def complete_json(self, system: str, user: str, schema: type[BaseModel]) -> Completion:
            captured["system"], captured["user"] = system, user
            return super().complete_json(system, user, schema)

    sentence = "Name what the visitor should type into this field."
    client = _Recording('{"technique":"G131"}')
    draft = RemediationDraft(act_testcase_id="case-1", axe_rule="label", remediation=sentence)
    result = classify(client, draft, vocabulary=technique_vocabulary())

    assert result.inferred_technique == LABEL_GOLD
    assert captured["user"] == f"Remediation: {sentence}"
    everything_sent = (captured["user"] + captured["system"]).lower()
    assert "case-1" not in everything_sent
    assert "label" not in everything_sent and "document-title" not in everything_sent


def test_classify_normalizes_case_and_accepts_the_none_answer() -> None:
    vocabulary = technique_vocabulary()
    draft = RemediationDraft(act_testcase_id="c", axe_rule="label", remediation="Do something vague.")
    assert classify(FakeLLMClient('{"technique":"g131"}'), draft, vocabulary=vocabulary).inferred_technique == "G131"
    assert (
        classify(FakeLLMClient('{"technique":"none"}'), draft, vocabulary=vocabulary).inferred_technique == NO_TECHNIQUE
    )


def test_an_answer_outside_the_vocabulary_raises_rather_than_folding_into_none() -> None:
    """The structured-output enum forbids it, so seeing one means the constraint is not holding — a
    stop, not a silently degraded stream."""
    with pytest.raises(ValueError, match="not a WCAG technique id"):
        classify(
            FakeLLMClient('{"technique":"G9999"}'),
            RemediationDraft(act_testcase_id="c", axe_rule="label", remediation="x"),
            vocabulary=technique_vocabulary(),
        )


def test_the_answer_schema_pins_the_allowed_ids_as_an_enum() -> None:
    vocabulary = technique_vocabulary()
    schema = classification_schema(vocabulary).model_json_schema()
    assert schema["properties"]["technique"]["enum"] == [*vocabulary, NO_TECHNIQUE]
    assert schema["additionalProperties"] is False


def test_the_system_prompt_lists_the_vocabulary_and_the_none_escape() -> None:
    prompt = classifier_system_prompt(technique_vocabulary())
    assert LABEL_GOLD in prompt and "H25" in prompt and NO_TECHNIQUE in prompt
    assert "REMEDIATION" in prompt


def test_classify_all_makes_one_call_per_draft_in_order() -> None:
    client = FakeLLMClient('{"technique":"G131"}', '{"technique":"H25"}')
    drafts = [
        RemediationDraft(act_testcase_id="a", axe_rule="label", remediation="one"),
        RemediationDraft(act_testcase_id="b", axe_rule="document-title", remediation="two"),
    ]
    assert [c.inferred_technique for c in classify_all(client, drafts, vocabulary=technique_vocabulary())] == [
        "G131",
        "H25",
    ]


# --- the run-artifact reader ----------------------------------------------------------------------


def test_a_run_artifact_without_remediation_text_raises() -> None:
    """A run that records conformance, citations and confidence but not the remediation sentence — the
    whole input to this metric — must fail loudly, never score an empty stream."""
    from clearway.eval.technique_match_build import remediation_drafts

    artifact = {
        "cases": [
            {
                "act_testcase_id": "a",
                "axe_rule": "label",
                "drafts": [{"finding_id": "f", "conformance": "supports", "cited_sc_ids": [], "confidence": 0.9}],
            }
        ]
    }
    with pytest.raises(RuntimeError, match="no scoreable remediation text"):
        remediation_drafts(artifact)


def test_the_reader_keeps_only_the_covered_classes() -> None:
    from clearway.eval.technique_match_build import remediation_drafts

    artifact = {
        "cases": [
            {"act_testcase_id": "a", "axe_rule": "label", "drafts": [{"remediation": "one"}]},
            {"act_testcase_id": "b", "axe_rule": "link-name", "drafts": [{"remediation": "two"}]},
        ]
    }
    assert [d.act_testcase_id for d in remediation_drafts(artifact)] == ["a"]


def test_the_pre_fix_frozen_runs_stay_unscoreable_rather_than_being_rewritten() -> None:
    """Half of the invariant, and the half history must not be rewritten to satisfy: every run frozen
    BEFORE the builder began recording the drafted sentence lacks it, so it raises instead of scoring an
    empty stream. The sentence cannot be recovered from those files — only re-drafted, which is a fresh
    model pass — so they are left as they are and simply stay out of the metric.

    Which artifacts those are is decided by reading them, not by a hard-coded list: a run is pre-fix iff
    no draft in it carries `remediation`. That keeps this test honest as new runs are frozen, while still
    failing if anyone back-fills a sentence into an old artifact."""
    from clearway.eval.offline_build import _RUNS_DIR
    from clearway.eval.technique_match_build import remediation_drafts

    runs = sorted(_RUNS_DIR.glob("*.json"))
    assert runs, "no frozen run artifacts to check"
    pre_fix = [
        p
        for p in runs
        if not any(d.get("remediation") for c in json.loads(p.read_text())["cases"] for d in c["drafts"])
    ]
    assert pre_fix, "expected at least one artifact frozen before remediation was recorded"
    for path in pre_fix:
        with pytest.raises(RuntimeError, match="no scoreable remediation text"):
            remediation_drafts(json.loads(path.read_text()))


def test_a_run_frozen_after_the_fix_is_scoreable_from_its_own_file() -> None:
    """The consequence of the fix, asserted on the real artifacts rather than a fixture: at least one
    frozen run now carries drafted remediation, so the fix-direction metric is computable from a
    checked-in file with no re-drafting. Before this, the metric was structurally unmeasurable."""
    from clearway.eval.offline_build import _RUNS_DIR
    from clearway.eval.technique_match_build import remediation_drafts

    scoreable = []
    for path in sorted(_RUNS_DIR.glob("*.json")):
        artifact = json.loads(path.read_text())
        if any(d.get("remediation") for c in artifact["cases"] for d in c["drafts"]):
            scoreable.append((path, remediation_drafts(artifact)))
    assert scoreable, "no frozen run carries drafted remediation — the metric is uncomputable again"
    for path, drafts in scoreable:
        assert drafts, path.name
        assert {d.axe_rule for d in drafts} <= set(technique_gold_by_class()), path.name


def test_a_record_written_now_round_trips_into_scoreable_remediation_text() -> None:
    """The other half: the run builder records the drafted sentence, so an artifact written today IS
    scoreable — the writer and this reader meet on the same key, proven end to end rather than assumed.
    The frozen runs simply lack it, and every reader takes its fields by name, so both shapes load."""
    from clearway.eval.referent_injection_build import _draft_record
    from clearway.eval.technique_match_build import remediation_drafts

    sentence = "Name what the visitor should type into this field."
    draft = DraftRow(
        finding_id="f1",
        conformance=Conformance.DOES_NOT_SUPPORT,
        citations=[Citation(sc_id="2.4.6")],
        remediation=sentence,
        confidence=0.9,
    )
    record = _draft_record(SimpleNamespace(id="f1", target="#email"), draft)
    assert record["remediation"] == sentence

    artifact = {"cases": [{"act_testcase_id": "case-1", "axe_rule": "label", "drafts": [record]}]}
    assert [d.remediation for d in remediation_drafts(artifact)] == [sentence]


# --- the classifier's own configuration -----------------------------------------------------------


def test_the_classifier_role_is_configured_apart_from_the_judge(monkeypatch: pytest.MonkeyPatch) -> None:
    """Three model roles, never conflated: setting the judge's variables must not move the classifier,
    and the classifier's own variables must."""
    from clearway.llm.cloud import technique_classifier_client

    monkeypatch.setenv("CLEARWAY_JUDGE_MODEL", "judge-model")
    monkeypatch.setenv("CLEARWAY_JUDGE_EFFORT", "high")
    monkeypatch.delenv("CLEARWAY_TECHNIQUE_MODEL", raising=False)
    monkeypatch.delenv("CLEARWAY_TECHNIQUE_EFFORT", raising=False)
    default = technique_classifier_client()
    assert (default.model, default.reasoning_effort) == ("gpt-5.6-sol", "medium")

    monkeypatch.setenv("CLEARWAY_TECHNIQUE_MODEL", "classifier-model")
    monkeypatch.setenv("CLEARWAY_TECHNIQUE_EFFORT", "low")
    configured = technique_classifier_client()
    assert (configured.model, configured.reasoning_effort) == ("classifier-model", "low")
