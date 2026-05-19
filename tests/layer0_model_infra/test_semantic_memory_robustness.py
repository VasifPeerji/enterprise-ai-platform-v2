"""
Regression tests for Layer 2 bugs surfaced by wild-corpus testing.

Each test here locks in a specific fix. The wild corpus revealed real issues
the curated golden set wouldn't have caught:
  - Slang negation ("get rid of") not detected
  - Stack-trace queries with different error types incorrectly matching
  - URLs treated as differentiating entities even when substitutable
  - PII tokens contaminating entity extraction
"""

from __future__ import annotations

import pytest

from src.layer0_model_infra.routing.semantic_memory import SemanticMemory


def make_memory():
    return SemanticMemory(
        similarity_threshold=0.75,
        enable_local_embedding=True,
        enable_persistence=False,
    )


class TestNegationGuard:
    """Negation polarity must reject opposite intents even at high similarity."""

    @pytest.mark.parametrize("record,lookup", [
        ("How do I install Docker?", "How do I uninstall Docker?"),
        ("Enable telemetry for the app", "Disable telemetry for the app"),
        ("How do I run tests with coverage?", "How do I run tests without coverage?"),
        ("How do I enable dark mode in vscode", "How do I get rid of dark mode in vscode"),
        ("Start the service", "Stop the service"),
    ])
    def test_negation_polarity_rejects(self, record, lookup):
        mem = make_memory()
        mem.record(query=record, model_id="m1", quality_score=0.9, escalated=False)
        result = mem.lookup(lookup)
        assert not result.hit, (
            f"Negation polarity should reject: {record!r} vs {lookup!r}; "
            f"got hit with sim={result.similarity}"
        )


class TestTechnicalEntityHardMatch:
    """Technical terms (errors, -able words, module paths) must hard-match —
    any difference rejects, regardless of similarity."""

    def test_stack_trace_subscriptable_vs_iterable(self):
        mem = make_memory()
        mem.record(
            query="Got TypeError: 'NoneType' object is not subscriptable",
            model_id="m1", quality_score=0.9, escalated=False,
        )
        result = mem.lookup("Got TypeError: 'NoneType' object is not iterable")
        assert not result.hit
        # The guard should specifically catch the technical-entity difference
        assert result.guard_rejected is not None
        assert "technical_entity" in result.guard_rejected or result.similarity < 0.75

    def test_different_error_types_reject(self):
        mem = make_memory()
        mem.record(query="Got a TypeError in my function", model_id="m1",
                   quality_score=0.9, escalated=False)
        result = mem.lookup("Got a ValueError in my function")
        assert not result.hit


class TestPIIScrubbing:
    """PII / URLs scrubbed to type tokens — different values, same template, should hit."""

    def test_different_emails_same_template_hits(self):
        mem = make_memory()
        mem.record(query="Send an email to alice@example.com about the meeting",
                   model_id="m1", quality_score=0.9, escalated=False)
        result = mem.lookup("Send an email to bob@other.com about the meeting")
        assert result.hit, (
            f"PII-scrubbed templates should hit; got miss with sim={result.similarity}"
        )

    def test_different_urls_same_template_hits(self):
        mem = make_memory()
        mem.record(
            query="Can you explain what's at https://example.com/api/docs",
            model_id="m1", quality_score=0.9, escalated=False,
        )
        result = mem.lookup("Can you explain what's at https://other-site.com/v2/api")
        assert result.hit, (
            f"URL-scrubbed templates should hit; got miss with sim={result.similarity}"
        )

    def test_different_phones_same_template_hits(self):
        mem = make_memory()
        mem.record(
            query="Send a text to 555-123-4567 about the meeting",
            model_id="m1", quality_score=0.9, escalated=False,
        )
        result = mem.lookup("Send a text to (555) 987-6543 about the meeting")
        assert result.hit


class TestEscalatedNeverReusable:
    """Escalated entries must never be served from cache, regardless of TTL."""

    def test_escalated_exact_match_misses(self):
        mem = make_memory()
        mem.record(
            query="Implement a distributed consensus algorithm in Go",
            model_id="m1", quality_score=0.85, escalated=True,
        )
        result = mem.lookup("Implement a distributed consensus algorithm in Go")
        assert not result.hit
        assert "low-quality / escalated" in result.reasoning


class TestTenantIsolation:
    """Entries tagged with tenant_id must not leak across tenants."""

    def test_tenant_a_entry_invisible_to_tenant_b(self):
        mem = make_memory()
        mem.record(
            query="Show users from the database",
            model_id="m1", quality_score=0.9, escalated=False,
            tenant_id="tenant_A",
        )
        result = mem.lookup("Show users from the database", tenant_id="tenant_B")
        assert not result.hit

    def test_tenant_a_entry_visible_to_tenant_a(self):
        mem = make_memory()
        mem.record(
            query="Show users from the database",
            model_id="m1", quality_score=0.9, escalated=False,
            tenant_id="tenant_A",
        )
        result = mem.lookup("Show users from the database", tenant_id="tenant_A")
        assert result.hit

    def test_global_entry_visible_to_any_tenant(self):
        """When tenant_id is empty, entry is global (current default)."""
        mem = make_memory()
        mem.record(query="What is Python?", model_id="m1", quality_score=0.9, escalated=False)
        result = mem.lookup("What is Python?", tenant_id="any_tenant")
        assert result.hit


class TestContextLengthGuard:
    """Cached short query must not match a much longer lookup query."""

    def test_short_record_long_lookup_rejects(self):
        mem = make_memory()
        mem.record(query="Hi", model_id="m1", quality_score=0.9, escalated=False)
        result = mem.lookup(
            "Hi, can you help me debug this 200-line Python script that uses "
            "recursion to solve the n-queens problem with backtracking?"
        )
        assert not result.hit


class TestCacheStats:
    """Metrics surface should expose hit rate, latency saved, etc."""

    def test_stats_includes_new_observability_fields(self):
        mem = make_memory()
        s = mem.stats()
        assert "lookup_count" in s
        assert "hit_count" in s
        assert "hit_rate_actual" in s
        assert "latency_saved_us" in s
        assert "guard_rejections" in s
        assert "embedder_available" in s
        assert "persistence_enabled" in s

    def test_hit_count_increments(self):
        mem = make_memory()
        mem.record(query="What is Python?", model_id="m1", quality_score=0.9, escalated=False)
        mem.lookup("What is Python?")  # should hit
        mem.lookup("What is Java?")    # should miss
        s = mem.stats()
        assert s["lookup_count"] >= 2
        assert s["hit_count"] >= 1


class TestModelInvalidation:
    """invalidate_model() drops all entries pointing to a deprecated model."""

    def test_invalidate_model_drops_entries(self):
        mem = make_memory()
        mem.record(query="A", model_id="old_model", quality_score=0.9, escalated=False)
        mem.record(query="B", model_id="new_model", quality_score=0.9, escalated=False)
        mem.record(query="C", model_id="old_model", quality_score=0.9, escalated=False)
        assert mem.stats()["total_entries"] == 3
        removed = mem.invalidate_model("old_model")
        assert removed == 2
        assert mem.stats()["total_entries"] == 1
