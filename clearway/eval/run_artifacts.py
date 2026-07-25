"""Where one labelled acceptance run's artifacts live — the single place that naming scheme is defined.

An acceptance run freezes several files: one artifact per determinism pass under `benchmark/runs/`, a
per-case checkpoint beside them, and the dry gate, verdict vector and result under `benchmark/reports/`.
A **run label** namespaces all of them, so two runs of the same pipeline never share a filename.

**The namespacing is load-bearing, not cosmetic.** An earlier run is the frozen comparison the next run
is measured against, and two failure modes follow from a shared namespace, both silent:

1. A second run writing `..._run_1.json` **overwrites the first run's canonical pass** — the artifact the
   paired test reads.
2. A scorer globbing the shared prefix sweeps **both** runs' passes into one determinism check, compares
   two runs that are *supposed* to differ, and reports the intended prompt change as a determinism drift.

Neither announces itself, which is why the scheme lives here rather than being spelled out at each call
site, and why `refuse_to_overwrite` guards the write even when a label is passed wrong.

**Labels name what distinguishes a run, never which ticket produced it:** `referent_injection` carries
the per-class referent blocks, `citation_grounding` carries the criterion's normative text and the
citation budget. `referent_injection`'s paths reproduce the already-frozen filenames byte-for-byte, so
adopting labels renamed nothing and orphaned no committed artifact — asserted by test.

The path helpers are pure given a directory (`passes_in`); the rest resolve the real benchmark tree,
which is imported lazily because `offline_build` pulls the drafter, the judge, the retriever and the
scanner behind it, and locating a file should not cost that.
"""

from __future__ import annotations

from pathlib import Path

# The referent-injection run: per-class referent material injected into the drafter prompt.
REFERENT_INJECTION = "referent_injection"
# The citation-grounding run: the criterion's normative text carried to the prompt, plus the citation budget.
CITATION_GROUNDING = "citation_grounding"

RUN_LABELS = (REFERENT_INJECTION, CITATION_GROUNDING)

# Which run each run must be attributed against — the one immediately before it. A run carrying a further
# prompt change has to answer "did this give back what the previous run bought?", and that question is
# only answerable against the previous run's frozen vector. Recorded here so the scorer can REQUIRE the
# comparison rather than accept its silent absence: a missing attribution and a clean one look identical
# in a report, and only one of them is true.
_PRIOR_RUN = {CITATION_GROUNDING: REFERENT_INJECTION}

_PASS_INFIX = "_run_"


class UnknownRunLabel(ValueError):
    """A run label outside `RUN_LABELS` — refused rather than silently opening a third namespace."""


class FrozenRunExists(RuntimeError):
    """A build that would overwrite an already-frozen pass artifact in place."""


def require_label(label: str) -> str:
    """The label, or a refusal. An unrecognised label would quietly create a set of files no scorer
    looks for, so a typo must fail here rather than produce a run that reads as missing."""
    if label not in RUN_LABELS:
        raise UnknownRunLabel(
            f"unknown run label {label!r} — expected one of {', '.join(RUN_LABELS)}. The label is the "
            "namespace a run's frozen artifacts share; an unrecognised one would write a third set of "
            "files rather than the run you meant, and every scorer would report that run as missing."
        )
    return label


def prior_label(label: str) -> str | None:
    """The run this one must be attributed against, or None for the first run in the sequence."""
    return _PRIOR_RUN.get(require_label(label))


def _runs_dir() -> Path:
    from clearway.eval.offline_build import _RUNS_DIR

    return _RUNS_DIR


def _reports_dir() -> Path:
    from clearway.eval.offline_build import _REPORTS_DIR

    return _REPORTS_DIR


def run_path(label: str, pass_n: int) -> Path:
    """The frozen artifact of one determinism pass."""
    return _runs_dir() / f"{require_label(label)}{_PASS_INFIX}{pass_n}.json"


def partial_path(label: str, pass_n: int) -> Path:
    """The per-case checkpoint of one pass — gitignored working state, deliberately kept OUT of the runs
    directory so globbing for passes cannot pick a half-written run up as a frozen one."""
    return _runs_dir().parent / f"{require_label(label)}{_PASS_INFIX}{pass_n}.partial.json"


def passes_in(runs_dir: Path, label: str) -> list[Path]:
    """This label's frozen pass artifacts in `runs_dir`, ordered by pass number — and only this label's.

    Pure, so the separation property is unit-testable without a benchmark tree. Ordering is numeric
    because pass 1 is canonical and a lexical sort would put pass 10 before pass 2. A file whose suffix
    is not a bare integer (a checkpoint, a hand-named experiment) is not a pass and is skipped rather
    than fed into the determinism sweep.
    """
    prefix = f"{require_label(label)}{_PASS_INFIX}"
    numbered: list[tuple[int, Path]] = []
    for path in runs_dir.glob(f"{prefix}*.json"):
        suffix = path.stem[len(prefix) :]
        if suffix.isdigit():
            numbered.append((int(suffix), path))
    return [path for _, path in sorted(numbered)]


def frozen_pass_paths(label: str) -> list[Path]:
    """`passes_in` against the real benchmark tree."""
    return passes_in(_runs_dir(), label)


def dry_gate_path(label: str) -> Path:
    return _reports_dir() / f"{require_label(label)}_dry_gate.json"


def result_path(label: str) -> Path:
    return _reports_dir() / f"{require_label(label)}_result.json"


def verdict_vector_path(label: str) -> Path:
    return _reports_dir() / f"{require_label(label)}_verdict_vector.json"


def refuse_to_overwrite(path: Path) -> None:
    """Refuse to write over an already-frozen pass.

    A frozen pass is a measurement, and the run that produced it cannot be recovered by re-running —
    the model would have to be called again, under whatever prompt is current, which is a different
    measurement wearing the same filename. So the artifact is superseded by **deleting it deliberately**,
    the same rule the calibration rebuild follows, rather than by a `--force` flag that turns the guard
    into a keystroke.
    """
    if path.exists():
        raise FrozenRunExists(
            f"{path.name} already exists and holds a frozen pass. Writing here would replace a "
            "measurement with a different one under the same name, and the original cannot be "
            "recovered without calling the model again under the current prompt — which is not the "
            "same measurement. Check the run label first; if you really mean to supersede this "
            "artifact, delete it deliberately and rebuild."
        )
