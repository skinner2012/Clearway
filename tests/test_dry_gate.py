"""The Run A dry-gate check functions — pure, gold-free, run before the model is ever called."""

from __future__ import annotations

from dataclasses import dataclass

from clearway.eval.dry_gate import (
    PromptRecord,
    case_set_failures,
    control_leak_failures,
    env_failures,
    evaluate,
    referent_verbatim_failures,
)


@dataclass
class _Excerpt:
    text: str


@dataclass
class _Referent:
    accessible_name: _Excerpt | None = None
    document_title: _Excerpt | None = None
    surrounding_context: _Excerpt | None = None


def _rec(rule: str, tid: str, prompt: str, referent: _Referent | None) -> PromptRecord:
    return PromptRecord(axe_rule=rule, act_testcase_id=tid, referent=referent, prompt=prompt)


def test_referent_present_verbatim_passes() -> None:
    recs = [
        _rec(
            "label",
            "a",
            'x Resolved accessible name: "First name:" y',
            _Referent(accessible_name=_Excerpt("First name:")),
        ),
        _rec(
            "document-title",
            "b",
            'Resolved page title: "Apple harvesting"',
            _Referent(document_title=_Excerpt("Apple harvesting")),
        ),
        _rec(
            "link-name",
            "c",
            'Resolved accessible name: "Go to main"',
            _Referent(accessible_name=_Excerpt("Go to main")),
        ),
    ]
    assert referent_verbatim_failures(recs) == []


def test_referent_absent_from_prompt_fails() -> None:
    recs = [_rec("label", "a", "no referent here", _Referent(accessible_name=_Excerpt("First name:")))]
    fails = referent_verbatim_failures(recs)
    assert len(fails) == 1 and "not found verbatim" in fails[0]


def test_link_name_falls_back_to_surrounding_context() -> None:
    # no accessible name, but the surrounding context is the referent and is present verbatim
    rec = _rec(
        "link-name",
        "c",
        'Surrounding context (...): "Download Ulysses in EPUB"',
        _Referent(surrounding_context=_Excerpt("Download Ulysses in EPUB")),
    )
    assert referent_verbatim_failures([rec]) == []


def test_class_with_no_referent_string_fails() -> None:
    rec = _rec("label", "a", "prompt body", _Referent())
    fails = referent_verbatim_failures([rec])
    assert len(fails) == 1 and "no referent string present" in fails[0]


def test_non_fixed_class_is_ignored_by_referent_check() -> None:
    rec = _rec("empty-heading", "h", "prompt body, no referent", _Referent())
    assert referent_verbatim_failures([rec]) == []


def test_control_leak_detected() -> None:
    clean = _rec("empty-heading", "h1", "plain empty-heading prompt", None)
    leaked = _rec("empty-heading", "h2", 'body Resolved accessible name: "oops"', None)
    assert control_leak_failures([clean]) == []
    fails = control_leak_failures([leaked])
    assert len(fails) == 1 and "leaked" in fails[0]


def test_case_set_checks() -> None:
    base = {f"c{i}" for i in range(44)}
    assert case_set_failures(base, base) == []
    assert case_set_failures(base - {"c0"}, base)  # missing one
    small = {f"c{i}" for i in range(43)}
    assert any("expected 44" in f for f in case_set_failures(small, small))


def test_env_checks() -> None:
    base = {
        "drafter_model_digest": "d",
        "axe_core_version": "4.12.1",
        "act_export_hash": "h",
        "corpus_version": "c",
        "config_id": "m1-single@1",
    }
    assert env_failures(dict(base), base) == []
    bad = dict(base, axe_core_version="4.13.0")
    fails = env_failures(bad, base)
    assert len(fails) == 1 and "axe_core_version" in fails[0]


def test_evaluate_green_and_distinct_counts() -> None:
    recs = [
        _rec("label", "a", 'p1 Resolved accessible name: "N"', _Referent(accessible_name=_Excerpt("N"))),
        _rec("label", "b", 'p2 Resolved accessible name: "M"', _Referent(accessible_name=_Excerpt("M"))),
        _rec("empty-heading", "h", "plain", None),
    ]
    ids = {"a", "b", "h"}
    base_ids = {f"c{i}" for i in range(41)} | ids
    env = {
        k: "v" for k in ("drafter_model_digest", "axe_core_version", "act_export_hash", "corpus_version", "config_id")
    }
    result = evaluate(recs, scoped_ids=base_ids, baseline_ids=base_ids, live_env=env, baseline_env=env)
    assert result.green is True
    assert result.distinct_prompts_by_class == {"label": 2, "empty-heading": 1}


def test_evaluate_red_when_control_leaks() -> None:
    recs = [_rec("empty-heading", "h", 'Resolved page title: "leak"', None)]
    ids = {"h"}
    env = {
        k: "v" for k in ("drafter_model_digest", "axe_core_version", "act_export_hash", "corpus_version", "config_id")
    }
    result = evaluate(recs, scoped_ids=ids, baseline_ids=ids, live_env=env, baseline_env=env)
    assert result.green is False and result.control_failures
