"""Cron parser and schedule computation tests."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.services.cron import CronError, CronExpression, compute_next_run, describe_schedule

NOW = datetime(2026, 11, 12, 10, 30, tzinfo=timezone.utc)  # Thursday


def test_every_15_minutes():
    nxt = CronExpression("*/15 * * * *").next_after(NOW)
    assert nxt == datetime(2026, 11, 12, 10, 45, tzinfo=timezone.utc)


def test_daily_at_3am():
    nxt = CronExpression("0 3 * * *").next_after(NOW)
    assert nxt == datetime(2026, 11, 13, 3, 0, tzinfo=timezone.utc)


def test_weekdays_only():
    nxt = CronExpression("0 9 * * mon-fri").next_after(NOW)
    assert nxt.weekday() < 5
    assert nxt == datetime(2026, 11, 13, 9, 0, tzinfo=timezone.utc)


def test_sunday_uses_cron_convention():
    # cron day-of-week 0 == Sunday
    nxt = CronExpression("0 0 * * 0").next_after(NOW)
    assert nxt.weekday() == 6  # Python Sunday


def test_impossible_date_returns_none():
    assert CronExpression("0 0 31 2 *").next_after(NOW) is None


def test_invalid_expression_raises():
    with pytest.raises(CronError):
        CronExpression("0 3 * *")
    with pytest.raises(CronError):
        CronExpression("99 * * * *")


def test_daily_schedule():
    nxt = compute_next_run("daily", hour=3, minute=30, now=NOW)
    assert nxt == datetime(2026, 11, 13, 3, 30, tzinfo=timezone.utc)


def test_weekly_schedule():
    nxt = compute_next_run("weekly", day_of_week=1, hour=4, minute=0, now=NOW)
    assert nxt == datetime(2026, 11, 16, 4, 0, tzinfo=timezone.utc)  # Monday


def test_monthly_schedule():
    nxt = compute_next_run("monthly", day_of_month=1, hour=5, minute=0, now=NOW)
    assert nxt == datetime(2026, 12, 1, 5, 0, tzinfo=timezone.utc)


def test_monthly_clamps_short_months():
    nxt = compute_next_run("monthly", day_of_month=31, hour=0, minute=0,
                           now=datetime(2027, 1, 31, 1, 0, tzinfo=timezone.utc))
    assert nxt is not None
    assert nxt.month == 2 and nxt.day == 28


def test_interval_schedules():
    assert compute_next_run("minutes", interval_value=30, now=NOW) == datetime(
        2026, 11, 12, 11, 0, tzinfo=timezone.utc
    )
    assert compute_next_run("hourly", interval_value=2, minute=15, now=NOW) == datetime(
        2026, 11, 12, 12, 15, tzinfo=timezone.utc
    )


def test_manual_and_paused_return_none():
    assert compute_next_run("manual", now=NOW) is None
    assert compute_next_run("daily", paused=True, now=NOW) is None


def test_end_date_stops_schedule():
    end = datetime(2026, 11, 12, 12, 0, tzinfo=timezone.utc)
    assert compute_next_run("daily", hour=20, end_date=end, now=NOW) is None


def test_timezone_conversion():
    nxt = compute_next_run("daily", hour=3, minute=0, timezone_name="Asia/Tehran", now=NOW)
    assert nxt is not None
    # 03:00 Tehran (UTC+3:30) == 23:30 UTC previous day
    assert nxt.hour == 23 and nxt.minute == 30


def test_describe_schedule():
    assert describe_schedule("daily", hour=3, minute=0) == "Daily at 03:00"
    assert "Weekly" in describe_schedule("weekly", day_of_week=1, hour=4)
    assert describe_schedule("manual") == "Manual only"
