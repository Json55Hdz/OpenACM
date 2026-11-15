"""The workflow tracker offers to turn repeated work into a tool; a 'no' must stick."""
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from openacm.core.workflow_tracker import (
    SuggestionResult, WorkflowTracker, _clean_tool_sequence, SUGGESTION_ANSWER_WINDOW_S)


def test_screenshots_are_noise_under_their_real_tool_name():
    assert _clean_tool_sequence([{"tool": "take_screenshot", "arguments": {}}]) == []


def test_an_old_offer_goes_stale():
    s = SuggestionResult(1, "x", 3, "h")
    assert not s.is_stale()
    s.created_at = time.monotonic() - SUGGESTION_ANSWER_WINDOW_S - 1
    assert s.is_stale()


async def test_a_dismissed_pattern_is_not_offered_again_for_a_week(db):
    tracker = WorkflowTracker(db, MagicMock(), MagicMock())
    now = datetime.now(timezone.utc).isoformat()
    ids = []
    for _ in range(3):
        ids.append(await db.insert_workflow_execution(
            user_id="u", channel_id="c", user_message="resume el correo", tool_sequence_raw='["a"]',
            tool_sequence_clean='["a"]', tool_args_hash="h1", turn_timestamp=now))
    sid = await db.insert_workflow_suggestion(
        user_id="u", channel_id="c", trigger_count=3,
        representative_ids_json=__import__("json").dumps(ids), suggested_at=now)
    assert await tracker._was_recently_dismissed("u", "h1") is False   # still pending
    await tracker.resolve_suggestion(sid, accepted=False)
    assert await tracker._was_recently_dismissed("u", "h1") is True
    assert await tracker._was_recently_dismissed("u", "other") is False


async def test_routine_detection_sees_the_newest_sessions_not_the_oldest(db):
    for day in range(1, 8):
        stamp = f"2026-11-{day:02d}T10:00:00"
        await db.log_app_activity(f"App{day}", "t", "p", 60, stamp, stamp, 0, 10)
    seen = [a["app_name"] for a in await db.get_app_activities(limit=3)]
    assert seen == ["App5", "App6", "App7"]  # the latest three, oldest first
