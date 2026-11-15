"""How a worker's reply becomes completed / failed decides retries and cascades."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from openacm.core.swarm_manager import SwarmManager

parse = SwarmManager._parse_task_status


class TestParseTaskStatus:
    def test_explicit_completed_marker(self):
        assert parse("Hecho.\nTASK_STATUS: COMPLETED")[0] == "completed"

    def test_explicit_failed_marker_carries_its_reason(self):
        assert parse("No pude.\nTASK_STATUS: FAILED: falta la API key") == ("failed", "falta la API key")

    def test_a_finished_report_that_mentions_timed_out_is_still_completed(self):
        text = "El cliente HTTP a veces timed out, lo corregí con reintentos.\nTASK_STATUS: COMPLETED"
        assert parse(text)[0] == "completed"

    def test_an_interruption_without_a_marker_is_a_failure(self):
        assert parse("❌ Request timed out")[0] == "failed"

    def test_empty_reply_is_a_failure(self):
        assert parse("")[0] == "failed"

    def test_waiting_for_user_is_not_a_failure(self):
        assert parse("TASK_STATUS: FAILED: waiting_for_user")[0] == "waiting"


async def test_a_crashing_task_reports_failed_so_it_can_be_retried():
    mgr = SwarmManager.__new__(SwarmManager)
    mgr.db = MagicMock()
    for name in ("update_swarm_worker", "update_swarm_task", "add_swarm_message", "get_swarm"):
        setattr(mgr.db, name, AsyncMock(return_value=None))
    mgr._emit = mgr._emit_task_event = mgr._emit_worker_event = AsyncMock()
    mgr._build_worker_tool_registry = MagicMock(side_effect=RuntimeError("boom"))
    swarm = {"id": 1, "name": "s", "workspace_path": "."}
    worker = {"id": 2, "name": "w", "workspace_path": "."}
    task = {"id": 3, "title": "t", "description": "d", "depends_on": "[]"}
    assert await mgr._execute_task(swarm, worker, task, [worker]) == "failed"
