"""Regime A oracle (`AxeCoreOracle`) and the canonical WCAG 2.2 SC reference set."""

from clearway.oracle.axe import AxeCoreOracle, tag_to_sc_ids
from clearway.oracle.wcag import SC_LEVELS, VALID_SC_IDS

__all__ = ["SC_LEVELS", "VALID_SC_IDS", "AxeCoreOracle", "tag_to_sc_ids"]
