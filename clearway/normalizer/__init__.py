"""Normalizer: raw `ScanResult` → canonical, deduplicated `Finding[]` (ARCHITECTURE §6)."""

from clearway.normalizer.normalize import normalize

__all__ = ["normalize"]
