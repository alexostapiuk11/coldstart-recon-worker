"""Artifact 5: how many LoRA adapters fit on one GPU.

Imports `harness/` and never `coldstart/` or `autoscale/`; tests/test_multilora_boundary.py
enforces it. Design: docs/superpowers/specs/2026-09-26-multi-lora-serving-harness-amendment.md.
"""

SCHEMA_VERSION = 1
