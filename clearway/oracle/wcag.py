"""Canonical WCAG 2.2 success-criterion reference — the L0 valid-SC set used by validator/ (T7).

Source: W3C *Web Content Accessibility Guidelines (WCAG) 2.2* Recommendation,
https://www.w3.org/TR/WCAG22/ (fetched 2026-07-06). WCAG 2.2 removed 4.1.1 Parsing
(obsolete), leaving 86 success criteria. Ids are canonical dotted form (CONTRACTS §2).
"""

from __future__ import annotations

from clearway.schemas.models import ConformanceLevel

A = ConformanceLevel.A
AA = ConformanceLevel.AA
AAA = ConformanceLevel.AAA

# Success criterion id -> conformance level, verbatim from the WCAG 2.2 Recommendation.
SC_LEVELS: dict[str, ConformanceLevel] = {
    # Principle 1 — Perceivable
    "1.1.1": A,
    "1.2.1": A,
    "1.2.2": A,
    "1.2.3": A,
    "1.2.4": AA,
    "1.2.5": AA,
    "1.2.6": AAA,
    "1.2.7": AAA,
    "1.2.8": AAA,
    "1.2.9": AAA,
    "1.3.1": A,
    "1.3.2": A,
    "1.3.3": A,
    "1.3.4": AA,
    "1.3.5": AA,
    "1.3.6": AAA,
    "1.4.1": A,
    "1.4.2": A,
    "1.4.3": AA,
    "1.4.4": AA,
    "1.4.5": AA,
    "1.4.6": AAA,
    "1.4.7": AAA,
    "1.4.8": AAA,
    "1.4.9": AAA,
    "1.4.10": AA,
    "1.4.11": AA,
    "1.4.12": AA,
    "1.4.13": AA,
    # Principle 2 — Operable
    "2.1.1": A,
    "2.1.2": A,
    "2.1.3": AAA,
    "2.1.4": A,
    "2.2.1": A,
    "2.2.2": A,
    "2.2.3": AAA,
    "2.2.4": AAA,
    "2.2.5": AAA,
    "2.2.6": AAA,
    "2.3.1": A,
    "2.3.2": AAA,
    "2.3.3": AAA,
    "2.4.1": A,
    "2.4.2": A,
    "2.4.3": A,
    "2.4.4": A,
    "2.4.5": AA,
    "2.4.6": AA,
    "2.4.7": AA,
    "2.4.8": AAA,
    "2.4.9": AAA,
    "2.4.10": AAA,
    "2.4.11": AA,
    "2.4.12": AAA,
    "2.4.13": AAA,
    "2.5.1": A,
    "2.5.2": A,
    "2.5.3": A,
    "2.5.4": A,
    "2.5.5": AAA,
    "2.5.6": AAA,
    "2.5.7": AA,
    "2.5.8": AA,
    # Principle 3 — Understandable
    "3.1.1": A,
    "3.1.2": AA,
    "3.1.3": AAA,
    "3.1.4": AAA,
    "3.1.5": AAA,
    "3.1.6": AAA,
    "3.2.1": A,
    "3.2.2": A,
    "3.2.3": AA,
    "3.2.4": AA,
    "3.2.5": AAA,
    "3.2.6": A,
    "3.3.1": A,
    "3.3.2": A,
    "3.3.3": AA,
    "3.3.4": AA,
    "3.3.5": AAA,
    "3.3.6": AAA,
    "3.3.7": A,
    "3.3.8": AA,
    "3.3.9": AAA,
    # Principle 4 — Robust  (4.1.1 Parsing removed in WCAG 2.2)
    "4.1.2": A,
    "4.1.3": AA,
}

# The L0 set: every id here is, by definition, a real WCAG 2.2 success criterion.
VALID_SC_IDS: frozenset[str] = frozenset(SC_LEVELS)
