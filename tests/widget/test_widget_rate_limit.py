"""Tests for the public widget abuse guard."""

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.layer4_platform.widget_rate_limit import WidgetRateLimiter  # noqa: E402


def test_per_ip_limit_blocks_and_isolates_by_ip():
    rl = WidgetRateLimiter(per_ip_per_min=3, per_bot_per_min=100, bot_daily_cap=100)
    t = 1000.0
    assert [rl.check_and_record(ip="1.1.1.1", bot_id="b", now=t + i * 0.1) for i in range(3)] == [None, None, None]
    assert rl.check_and_record(ip="1.1.1.1", bot_id="b", now=t + 0.4) == "per_ip_per_min"
    # a different IP is unaffected
    assert rl.check_and_record(ip="2.2.2.2", bot_id="b", now=t + 0.5) is None


def test_per_bot_minute_limit_across_ips():
    rl = WidgetRateLimiter(per_ip_per_min=100, per_bot_per_min=2, bot_daily_cap=100)
    t = 1000.0
    assert rl.check_and_record(ip="a", bot_id="b", now=t) is None
    assert rl.check_and_record(ip="b", bot_id="b", now=t) is None
    assert rl.check_and_record(ip="c", bot_id="b", now=t) == "per_bot_per_min"


def test_per_bot_daily_cap():
    rl = WidgetRateLimiter(per_ip_per_min=100, per_bot_per_min=100, bot_daily_cap=2)
    t = 1000.0
    assert rl.check_and_record(ip="a", bot_id="b", now=t) is None
    assert rl.check_and_record(ip="c", bot_id="b", now=t + 1) is None
    assert rl.check_and_record(ip="d", bot_id="b", now=t + 2) == "per_bot_daily"


def test_minute_window_slides():
    rl = WidgetRateLimiter(per_ip_per_min=1, per_bot_per_min=100, bot_daily_cap=100)
    t = 1000.0
    assert rl.check_and_record(ip="x", bot_id="b", now=t) is None
    assert rl.check_and_record(ip="x", bot_id="b", now=t + 30) == "per_ip_per_min"
    assert rl.check_and_record(ip="x", bot_id="b", now=t + 61) is None  # >60s frees the slot


def test_rejected_request_consumes_no_quota():
    rl = WidgetRateLimiter(per_ip_per_min=2, per_bot_per_min=100, bot_daily_cap=100)
    t = 1000.0
    rl.check_and_record(ip="x", bot_id="b", now=t)
    rl.check_and_record(ip="x", bot_id="b", now=t)
    # third is rejected and must NOT extend the window further
    assert rl.check_and_record(ip="x", bot_id="b", now=t + 1) == "per_ip_per_min"
    # exactly at 60s after the FIRST allowed hit, one slot frees
    assert rl.check_and_record(ip="x", bot_id="b", now=t + 60.001) is None
