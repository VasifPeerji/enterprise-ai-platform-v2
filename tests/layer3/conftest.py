"""
Fixtures for Layer 3 tests.

Each test that touches a singleton should request the matching ``reset_*``
fixture so the state doesn't leak between tests (encoder caches survive across
the process, which is fine; cache contents do not).
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
REGISTRY_PATH = REPO_ROOT / "src/layer0_model_infra/data/registry.json"


@pytest.fixture
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture
def registry_path() -> Path:
    return REGISTRY_PATH


@pytest.fixture
def reset_registry():
    """Drop the registry singleton before AND after the test."""
    from src.layer0_model_infra.routing import registry_loader
    registry_loader.reset_layer3_registry()
    yield
    registry_loader.reset_layer3_registry()


@pytest.fixture
def reset_feature_extractor():
    from src.layer0_model_infra.routing import feature_extractor
    feature_extractor.reset_feature_extractor()
    yield
    feature_extractor.reset_feature_extractor()


@pytest.fixture
def reset_verdict_cache():
    from src.layer0_model_infra.routing import verdict_cache
    verdict_cache.reset_verdict_cache()
    yield
    verdict_cache.reset_verdict_cache()


@pytest.fixture
def all_keys_set(monkeypatch):
    """Make every model in the registry active by setting every required env var."""
    for name in [
        "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY",
        "GROQ_API_KEY", "OPENROUTER_API_KEY", "HUGGINGFACE_API_KEY",
        "COHERE_API_KEY",
    ]:
        monkeypatch.setenv(name, "test-value")
    yield


@pytest.fixture
def only_groq_set(monkeypatch):
    """Simulate a user with only the GROQ key set."""
    for name in [
        "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY",
        "OPENROUTER_API_KEY", "HUGGINGFACE_API_KEY", "COHERE_API_KEY",
    ]:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("GROQ_API_KEY", "test-value")
    yield


@pytest.fixture
def no_keys_set(monkeypatch):
    """Simulate a fresh install with no provider keys."""
    for name in [
        "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY",
        "GROQ_API_KEY", "OPENROUTER_API_KEY", "HUGGINGFACE_API_KEY",
        "COHERE_API_KEY",
    ]:
        monkeypatch.delenv(name, raising=False)
    yield
