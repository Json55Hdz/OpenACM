"""LLM monitoring queries: errors, failovers and the cost/usage breakdown (mixed into Database)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

ERROR_RETENTION_DAYS = 30


def _since(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=max(1, min(int(days), 90)))).isoformat()


class LlmMonitorMixin:
    async def log_llm_error(
        self, provider: str, model: str, role: str, error_class: str, message: str, failover_to: str = ""
    ) -> None:
        if not self._db:
            return
        now = datetime.now(timezone.utc)
        await self._db.execute(
            "INSERT INTO llm_errors (timestamp, provider, model, role, error_class, message, failover_to) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (now.isoformat(), provider, model, role, error_class, message, failover_to),
        )
        await self._db.execute(
            "DELETE FROM llm_errors WHERE timestamp < ?",
            ((now - timedelta(days=ERROR_RETENTION_DAYS)).isoformat(),),
        )
        await self._db.commit()

    async def get_llm_errors(self, days: int = 7, limit: int = 50) -> list[dict[str, Any]]:
        if not self._db:
            return []
        cursor = await self._db.execute(
            "SELECT timestamp, provider, model, role, error_class, message, failover_to "
            "FROM llm_errors WHERE timestamp >= ? ORDER BY id DESC LIMIT ?",
            (_since(days), max(1, min(int(limit), 200))),
        )
        return [dict(r) for r in await cursor.fetchall()]

    async def get_llm_monitor(self, days: int = 7) -> dict[str, Any]:
        """Cost, tokens, speed and error counts per model, plus totals."""
        if not self._db:
            return {"models": [], "totals": {}, "errors_by_provider": []}
        since = _since(days)
        cursor = await self._db.execute(
            "SELECT provider, model, COUNT(*) AS requests, SUM(total_tokens) AS tokens, "
            "SUM(cost) AS cost, AVG(elapsed_ms) AS avg_ms "
            "FROM llm_usage WHERE timestamp >= ? GROUP BY provider, model ORDER BY cost DESC, requests DESC",
            (since,),
        )
        models = [
            {
                "provider": r["provider"] or "", "model": r["model"], "requests": r["requests"],
                "tokens": int(r["tokens"] or 0), "cost": round(float(r["cost"] or 0), 4),
                "avg_ms": int(r["avg_ms"] or 0),
            }
            for r in await cursor.fetchall()
        ]
        cursor = await self._db.execute(
            "SELECT provider, COUNT(*) AS errors, SUM(CASE WHEN failover_to != '' THEN 1 ELSE 0 END) AS failovers "
            "FROM llm_errors WHERE timestamp >= ? GROUP BY provider ORDER BY errors DESC",
            (since,),
        )
        errors = [
            {"provider": r["provider"], "errors": r["errors"], "failovers": int(r["failovers"] or 0)}
            for r in await cursor.fetchall()
        ]
        totals = {
            "requests": sum(m["requests"] for m in models),
            "tokens": sum(m["tokens"] for m in models),
            "cost": round(sum(m["cost"] for m in models), 4),
            "errors": sum(e["errors"] for e in errors),
            "failovers": sum(e["failovers"] for e in errors),
        }
        return {"models": models, "totals": totals, "errors_by_provider": errors, "days": days}
