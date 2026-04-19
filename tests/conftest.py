"""pytest fixtures shared across the test modules.

Forces the offline ``MockProvider`` for every test so the suite stays
deterministic and never accidentally calls a live LLM, regardless of
what's in ``.env``.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ["LLM_PROVIDER"] = "mock"

SAMPLES_DIR = Path(__file__).resolve().parent.parent / "samples"


@pytest.fixture
def constant_error_log() -> str:
    """Return the raw text of ``samples/constant_error.txt``."""
    return (SAMPLES_DIR / "constant_error.txt").read_text()


@pytest.fixture
def empty_project_log() -> str:
    """Return the raw text of ``samples/empty_project.txt``."""
    return (SAMPLES_DIR / "empty_project.txt").read_text()


@pytest.fixture
def constant_error_xml() -> str:
    """Return the raw text of ``samples/constant_error.xml``."""
    return (SAMPLES_DIR / "constant_error.xml").read_text()


@pytest.fixture
def empty_project_xml() -> str:
    """Return the raw text of ``samples/empty_project.xml``."""
    return (SAMPLES_DIR / "empty_project.xml").read_text()
