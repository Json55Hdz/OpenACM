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


async def test_stopping_a_swarm_puts_running_work_back_so_it_can_resume():
    mgr = SwarmManager.__new__(SwarmManager)
    mgr._running = {}
    mgr._emit = mgr._emit_swarm_event = AsyncMock()
    mgr.db = MagicMock()
    mgr.db.get_swarm_tasks = AsyncMock(return_value=[
        {"id": 1, "status": "running"}, {"id": 2, "status": "completed"}])
    mgr.db.get_swarm_workers = AsyncMock(return_value=[
        {"id": 7, "status": "busy"}, {"id": 8, "status": "idle"}])
    mgr.db.update_swarm_task = AsyncMock()
    mgr.db.update_swarm_worker = AsyncMock()
    mgr.db.update_swarm = AsyncMock()
    await mgr.stop_swarm(5)
    mgr.db.update_swarm_task.assert_awaited_once()
    assert mgr.db.update_swarm_task.await_args.args[0] == 1
    mgr.db.update_swarm_worker.assert_awaited_once_with(7, status="idle")
    mgr.db.update_swarm.assert_awaited_with(5, status="paused")


async def test_a_cron_swarm_template_creates_plans_and_starts_a_real_swarm():
    from openacm.watchers.cron_scheduler import CronScheduler

    manager = MagicMock()
    manager.create_swarm = AsyncMock(return_value={"id": 9})
    manager.plan_swarm = AsyncMock()
    manager.start_swarm = AsyncMock()
    db = MagicMock()
    db.get_swarm_template = AsyncMock(return_value={
        "name": "Informe", "goal_template": "Resumen del {date}", "global_model": ""})
    cron = CronScheduler(db, swarm_manager=manager)
    out = await cron._run_swarm_template({"template_id": 1})
    assert "swarm_id=9" in out
    assert "{date}" not in manager.create_swarm.await_args.kwargs["goal"]
    manager.plan_swarm.assert_awaited_once_with(9)
    manager.start_swarm.assert_awaited_once_with(9)
