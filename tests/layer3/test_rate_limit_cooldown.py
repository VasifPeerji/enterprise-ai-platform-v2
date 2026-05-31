"""Tests for the rate-limit cooldown store (M4)."""

from __future__ import annotations

from src.layer0_model_infra.routing.rate_limit_cooldown import RateLimitCooldown


def test_mark_and_is_cooling_down():
    c = RateLimitCooldown()
    assert c.is_cooling_down("m1") is False
    c.mark("m1", 100)
    assert c.is_cooling_down("m1") is True


def test_expired_entry_is_not_cooling():
    c = RateLimitCooldown()
    c.mark("m2", -1)  # expiry in the past
    assert c.is_cooling_down("m2") is False


def test_active_set_reaps_expired():
    c = RateLimitCooldown()
    c.mark("hot", 100)
    c.mark("cold", -1)
    active = c.active()
    assert "hot" in active
    assert "cold" not in active


def test_clear():
    c = RateLimitCooldown()
    c.mark("m", 100)
    c.clear()
    assert c.is_cooling_down("m") is False


def test_default_cooldown_seconds():
    assert RateLimitCooldown(default_cooldown_seconds=-1.0).__class__ is RateLimitCooldown
    expired = RateLimitCooldown(default_cooldown_seconds=-1.0)
    expired.mark("m")  # uses the (negative) default → already expired
    assert expired.is_cooling_down("m") is False

    cooling = RateLimitCooldown(default_cooldown_seconds=100.0)
    cooling.mark("m")
    assert cooling.is_cooling_down("m") is True
