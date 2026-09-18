"""Bare seed: create + push only, no .gitlab-ci.yml."""

from __future__ import annotations

from pathlib import Path


def render_ci(_project_dir: Path) -> str | None:
    return None
