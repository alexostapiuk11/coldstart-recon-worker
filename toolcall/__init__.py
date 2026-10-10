"""Artifact 3: how tool presentation changes tool-calling failure modes.

Imports `harness/` and nothing from another artifact's package;
tests/test_toolcall_boundary.py enforces it, transitively. Design:
docs/superpowers/specs/2026-10-08-tool-calling-reliability-amendment.md, which
governs docs/superpowers/specs/2026-08-17-tool-calling-reliability-harness-design.md.

Two version numbers travel with every graded record. Changing what either one
covers is a breaking change (August §4): numbers graded under different
versions are not comparable.
"""

SCHEMA_VERSION = 1  # the scenario and tool-library file formats
NORMALIZER_VERSION = 1  # toolcall/normalize.py's rules
