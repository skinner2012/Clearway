"""Scanner: Playwright + axe-core page scan → `ScanResult` (ARCHITECTURE §4.2)."""

from clearway.scanner.scan import AXE_VERSION, scan

__all__ = ["scan", "AXE_VERSION"]
