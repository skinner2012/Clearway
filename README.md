# Clearway

## Introduction

An accessibility evidence pipeline: it turns a raw accessibility signal into decision-ready, cited, confidence-scored conformance evidence for a human specialist, and measures the trustworthiness of its own AI-generated outputs. It never decides conformance — the specialist does. It starts with websites (where an automated checker gives near-free ground truth) and is designed to extend to physical audits.

## Motivation

Accessibility evaluation is expensive not because problems are hard to detect, but because **documenting defensible findings** is — mapping each issue to the correct citation, writing remediation an implementer can act on, and assembling a standards-shaped report. The costly unit is **expert-minutes-per-finding**, and that is what Clearway sets out to compress.

The design bet: the scarce, defensible thing is not the forward path (scan → retrieve → draft, which many tools already do) but **measuring how far the AI's own outputs can be trusted**. So Clearway hands a human specialist decision-ready evidence *together with* its own trust metrics, and never decides conformance itself. That is the thesis — **measured trust is the product**.

The full rationale — the regulatory backdrop (FTC v. accessiBe), the two-oracle-regime design, detailed scope, and an honest truth-ledger — lives in [`DESIGN_NOTE.md`](DESIGN_NOTE.md).

## Status

Early — currently building **M0 (walking skeleton)**, the thinnest end-to-end run that proves the measurement loop is real. See [`specs/M0-walking-skeleton.md`](specs/M0-walking-skeleton.md).

## Documentation

- [`DESIGN_NOTE.md`](DESIGN_NOTE.md) — full product scope, thesis, and rationale.
- [`ARCHITECTURE.md`](ARCHITECTURE.md) — decisions of record: stack, module boundaries, milestones.
- [`CONTRACTS.md`](CONTRACTS.md) — the shared data schemas (single source of truth).
- [`CLAUDE.md`](CLAUDE.md) — working conventions and rules of engagement for Claude Code and contributors.
- [`specs/`](specs/) — per-milestone task tickets.

## License & authorship

Licensed under the [Apache License 2.0](LICENSE). You may use and build on this work, but must retain the attribution in [`NOTICE`](NOTICE). Original author, architect, and designer: **FuYuan (Skinner) Cheng**. The public commit history is the authoritative record of authorship and precedence.
