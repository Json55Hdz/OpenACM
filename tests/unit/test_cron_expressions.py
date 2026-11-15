"""Cron expressions must fire on the days they say, not every day."""
from datetime import datetime

from openacm.watchers.cron_scheduler import _next_cron_datetime as nxt

START = datetime(2026, 11, 15, 12, 0)  # a Sunday


def test_day_of_month_alone_fires_only_that_day():
    assert nxt("0 9 20 * *", START) == datetime(2026, 11, 20, 9, 0)
    assert nxt("0 9 20 * *", datetime(2026, 11, 21, 0, 0)) == datetime(2026, 12, 20, 9, 0)


def test_weekday_alone_fires_only_that_weekday():
    assert nxt("0 9 * * 1", START) == datetime(2026, 11, 16, 9, 0)  # Monday


def test_both_restricted_means_either():
    assert nxt("0 9 20 * 1", START) == datetime(2026, 11, 16, 9, 0)  # Monday comes first


def test_sunday_can_be_written_as_7():
    assert nxt("0 9 * * 7", START) == datetime(2026, 11, 22, 9, 0)


def test_every_day_still_works():
    assert nxt("30 13 * * *", START) == datetime(2026, 11, 15, 13, 30)
