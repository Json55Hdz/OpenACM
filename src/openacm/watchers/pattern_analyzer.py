"""
Pattern Analyzer for OpenACM Routines.

Analyzes app activity sessions to detect recurring patterns and
automatically generates "Mis Rutinas" entries.

Detection strategies:
  1. Co-occurrence: apps that appear together in the same work session
  2. Time clustering: same app combo at similar times daily/weekly
  3. Sequential: app B always opened within minutes of app A
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from openacm.storage.database import Database

log = structlog.get_logger()

# Minimum times a pattern must repeat to become a routine suggestion
PATTERN_THRESHOLD = 5
# Minimum focus time (seconds) to consider an app "significant" in a session
MIN_FOCUS_SECONDS = 30
# Max gap (seconds) between sessions to be in the same "work session"
SESSION_GAP = 30 * 60  # 30 minutes


class PatternAnalyzer:
    """Detects recurring app patterns and creates routine suggestions."""

    def __init__(self, db: "Database", llm_router: Any = None):
        self._db = db
        self._llm = llm_router  # Optional — used for LLM-powered naming + descriptions

    async def analyze(self) -> list[dict[str, Any]]:
        """
        Run full pattern analysis.  Returns list of newly created routine dicts.
        """
        activities = await self._db.get_app_activities(limit=5000)
        if len(activities) < 6:
            log.info("PatternAnalyzer: not enough data yet", count=len(activities))
            return []

        log.info("PatternAnalyzer: analyzing sessions", count=len(activities))

        work_sessions = self._group_into_work_sessions(activities)
        patterns = self._find_patterns(work_sessions)
        saved = []
        for pattern in patterns:
            # Enrich with LLM-generated name + description if available
            if self._llm:
                await self._enrich_with_llm(pattern)
            routine = await self._upsert_routine(pattern)
            if routine:
                saved.append(routine)

        merged = await self._deduplicate_existing()
        log.info("PatternAnalyzer: done", new_routines=len(saved), patterns_found=len(patterns), merged=merged)
        return saved

    async def _enrich_with_llm(self, pattern: dict[str, Any]) -> None:
        """
        Ask the LLM to generate a human-friendly name and short description
        for the pattern.  Mutates `pattern` in place.  Never raises — falls
        back to the algorithmic name on any error.
        """
        apps = pattern.get("apps", [])
        hour = pattern.get("trigger_data", {}).get("hour", 12)
        count = pattern.get("occurrence_count", 0)
        days = pattern.get("trigger_data", {}).get("days_of_week", list(range(5)))
        day_names = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
        days_str = ", ".join(day_names[d] for d in days if d < 7)

        prompt = (
            f"El usuario suele abrir estas aplicaciones juntas {count} veces:\n"
            f"Apps: {', '.join(apps)}\n"
            f"Hora habitual: {hour:02d}:00\n"
            f"Días: {days_str or 'varios'}\n\n"
            "Responde SOLO con un JSON con dos campos:\n"
            '{"name": "<nombre corto y descriptivo en español, máx 40 chars>", '
            '"description": "<descripción de 1 frase de qué hace el usuario en este contexto>"}\n'
            "Sin markdown, sin explicaciones, solo el JSON."
        )

        try:
            result = await self._llm.chat(
                messages=[{"role": "user", "content": prompt}],
                tools=None,
                temperature=0.4,
                max_tokens=120,
            )
            raw = result.get("content", "").strip()
            # Strip possible markdown code fences
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            data = json.loads(raw)
            if data.get("name"):
                pattern["name"] = str(data["name"])[:60]
            if data.get("description"):
                pattern["description"] = str(data["description"])[:200]
        except Exception as exc:
            log.debug("LLM routine naming failed, using algorithmic name", error=str(exc))

    # ─── Session grouping ──────────────────────────────────────

    def _group_into_work_sessions(
        self, activities: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """
        Group individual app focus records into logical work sessions.
        A new session begins when there's a gap > SESSION_GAP seconds.
        """
        if not activities:
            return []

        sorted_acts = sorted(activities, key=lambda x: x.get("session_start", ""))

        sessions: list[dict[str, Any]] = []
        current: list[dict[str, Any]] = [sorted_acts[0]]
        current_end = sorted_acts[0].get("session_end", sorted_acts[0].get("session_start", ""))

        for act in sorted_acts[1:]:
            act_start = act.get("session_start", "")
            gap = self._seconds_between(current_end, act_start)

            if 0 <= gap <= SESSION_GAP:
                current.append(act)
                act_end = act.get("session_end", act_start)
                if act_end > current_end:
                    current_end = act_end
            else:
                sessions.append(self._make_session(current))
                current = [act]
                current_end = act.get("session_end", act_start)

        sessions.append(self._make_session(current))
        return sessions

    def _make_session(self, acts: list[dict[str, Any]]) -> dict[str, Any]:
        start_str = acts[0].get("session_start", "")
        try:
            dt = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
            hour = dt.hour
            dow = dt.weekday()
        except Exception:
            hour = 12
            dow = 0

        # Aggregate focus time per app in this session.
        # When a project is detected, use "AppName [Project]" as composite key so
        # "VS Code [OpenACM]" and "VS Code [MyGame]" are treated as separate contexts.
        app_focus: dict[str, float] = defaultdict(float)
        app_process: dict[str, str] = {}
        app_exe: dict[str, str] = {}
        app_project: dict[str, str] = {}    # composite_key → project_name
        app_real_name: dict[str, str] = {}  # composite_key → original app_name

        for act in acts:
            name = act.get("app_name", "Unknown")
            project = act.get("project_name", "")
            key = f"{name} [{project}]" if project else name
            app_focus[key] += act.get("focus_seconds", 0)
            app_process[key] = act.get("process_name", name.lower())
            app_real_name[key] = name
            if project:
                app_project[key] = project
            if act.get("exe_path"):
                app_exe[key] = act["exe_path"]

        return {
            "start": start_str,
            "hour": hour,
            "day_of_week": dow,
            "app_focus": dict(app_focus),
            "app_process": app_process,
            "app_exe": app_exe,
            "app_project": app_project,
            "app_real_name": app_real_name,
        }

    # ─── Pattern detection ─────────────────────────────────────

    def _find_patterns(
        self, sessions: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """
        Find recurring app co-occurrence patterns across work sessions.
        """
        # For each session, determine the "significant" app set (composite keys)
        session_sets: list[dict[str, Any]] = []
        for sess in sessions:
            sig_apps = {
                app
                for app, secs in sess["app_focus"].items()
                if secs >= MIN_FOCUS_SECONDS
            }
            if len(sig_apps) >= 2:
                session_sets.append(
                    {
                        "apps": sig_apps,
                        "app_process": sess["app_process"],
                        "app_exe": sess.get("app_exe", {}),
                        "app_project": sess.get("app_project", {}),
                        "app_real_name": sess.get("app_real_name", {}),
                        "hour": sess["hour"],
                        "day_of_week": sess["day_of_week"],
                        "start": sess["start"],
                    }
                )

        if not session_sets:
            return []

        # Count co-occurrences for every pair of apps (using composite keys)
        pair_data: dict[tuple[str, str], dict] = defaultdict(
            lambda: {"count": 0, "hours": [], "days": [], "all_apps": Counter(),
                     "app_process": {}, "app_exe": {}, "app_project": {}, "app_real_name": {}}
        )

        for sess in session_sets:
            apps = sorted(sess["apps"])
            for i, a in enumerate(apps):
                for b in apps[i + 1:]:
                    key = (a, b)
                    pair_data[key]["count"] += 1
                    pair_data[key]["hours"].append(sess["hour"])
                    pair_data[key]["days"].append(sess["day_of_week"])
                    pair_data[key]["app_process"].update(sess["app_process"])
                    pair_data[key]["app_exe"].update(sess.get("app_exe", {}))
                    pair_data[key]["app_project"].update(sess.get("app_project", {}))
                    pair_data[key]["app_real_name"].update(sess.get("app_real_name", {}))
                    for app in sess["apps"]:
                        pair_data[key]["all_apps"][app] += 1

        # Also collect full-session sets (up to 5 apps) that repeat
        set_data: dict[frozenset, dict] = defaultdict(
            lambda: {"count": 0, "hours": [], "days": [],
                     "app_process": {}, "app_exe": {}, "app_project": {}, "app_real_name": {}}
        )
        for sess in session_sets:
            key = frozenset(sess["apps"])
            set_data[key]["count"] += 1
            set_data[key]["hours"].append(sess["hour"])
            set_data[key]["days"].append(sess["day_of_week"])
            set_data[key]["app_process"].update(sess["app_process"])
            set_data[key]["app_exe"].update(sess.get("app_exe", {}))
            set_data[key]["app_project"].update(sess.get("app_project", {}))
            set_data[key]["app_real_name"].update(sess.get("app_real_name", {}))

        patterns: list[dict[str, Any]] = []
        seen_keys: set[frozenset] = set()

        # Prefer full-set patterns first (more specific)
        for app_set, data in sorted(set_data.items(), key=lambda x: -x[1]["count"]):
            if data["count"] < PATTERN_THRESHOLD:
                continue
            key = frozenset(app_set)
            if key in seen_keys:
                continue
            seen_keys.add(key)

            patterns.append(
                self._build_pattern(
                    apps=sorted(list(app_set)),
                    app_process=data["app_process"],
                    app_exe=data.get("app_exe", {}),
                    app_project=data.get("app_project", {}),
                    app_real_name=data.get("app_real_name", {}),
                    count=data["count"],
                    hours=data["hours"],
                    days=data["days"],
                )
            )

        # Add pair-level patterns not already covered
        for (a, b), data in sorted(pair_data.items(), key=lambda x: -x[1]["count"]):
            if data["count"] < PATTERN_THRESHOLD:
                continue
            key = frozenset([a, b])
            if key in seen_keys:
                continue
            seen_keys.add(key)

            common_together = [
                app
                for app, cnt in data["all_apps"].most_common(5)
                if cnt >= PATTERN_THRESHOLD
            ]
            apps = sorted(set(common_together) | {a, b})
            seen_keys.add(frozenset(apps))

            patterns.append(
                self._build_pattern(
                    apps=apps,
                    app_process=data["app_process"],
                    app_exe=data["app_exe"],
                    app_project=data.get("app_project", {}),
                    app_real_name=data.get("app_real_name", {}),
                    count=data["count"],
                    hours=data["hours"],
                    days=data["days"],
                )
            )

        return patterns

    def _build_pattern(
        self,
        apps: list[str],
        app_process: dict[str, str],
        count: int,
        hours: list[int],
        days: list[int],
        app_exe: dict[str, str] | None = None,
        app_project: dict[str, str] | None = None,
        app_real_name: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        avg_hour = sum(hours) / len(hours) if hours else 12
        is_time = self._is_time_consistent(hours)
        common_days = self._common_days(days)
        confidence = min(0.97, 0.30 + count * 0.07)
        app_exe = app_exe or {}
        app_project = app_project or {}
        app_real_name = app_real_name or {}

        apps_payload = [
            {
                "app_name": app_real_name.get(app, app),
                "display_name": app,
                "process_name": app_process.get(app, app_real_name.get(app, app).lower().replace(" ", "_")),
                "exe_path": app_exe.get(app, ""),
                "project_name": app_project.get(app, ""),
            }
            for app in apps
        ]

        # Build display names for the routine title (include project when known)
        display_apps = []
        for app in apps:
            real = app_real_name.get(app, app)
            proj = app_project.get(app, "")
            display_apps.append(f"{real} ({proj})" if proj else real)

        return {
            "name": self._suggest_name(display_apps, avg_hour),
            "description": "",  # filled by _enrich_with_llm if available
            "apps": apps,       # composite keys like "VS Code [OpenACM]"
            "apps_payload": apps_payload,
            "trigger_type": "time_based" if is_time else "manual",
            "trigger_data": {
                "hour": int(avg_hour),
                "minute": 0,
                "days_of_week": common_days,
            },
            "confidence": round(confidence, 2),
            "occurrence_count": count,
        }

    # ─── Helpers ──────────────────────────────────────────────

    @staticmethod
    def _seconds_between(a: str, b: str) -> float:
        try:
            dt_a = datetime.fromisoformat(a.replace("Z", "+00:00"))
            dt_b = datetime.fromisoformat(b.replace("Z", "+00:00"))
            return (dt_b - dt_a).total_seconds()
        except Exception:
            return -1

    @staticmethod
    def _is_time_consistent(hours: list[int]) -> bool:
        if len(hours) < 2:
            return False
        avg = sum(hours) / len(hours)
        return all(abs(h - avg) <= 2.5 for h in hours)

    @staticmethod
    def _common_days(days: list[int]) -> list[int]:
        if not days:
            return [0, 1, 2, 3, 4]
        counts = Counter(days)
        threshold = max(1, len(days) * 0.25)
        return sorted(d for d, c in counts.items() if c >= threshold)

    @staticmethod
    def _suggest_name(apps: list[str], avg_hour: float) -> str:
        if avg_hour < 5:
            slot = "Late night"
        elif avg_hour < 9:
            slot = "Morning"
        elif avg_hour < 12:
            slot = "Late morning"
        elif avg_hour < 14:
            slot = "Midday"
        elif avg_hour < 18:
            slot = "Afternoon"
        elif avg_hour < 21:
            slot = "Evening"
        else:
            slot = "Night"

        if len(apps) == 0:
            return slot
        elif len(apps) == 1:
            return f"{slot} — {apps[0]}"
        elif len(apps) == 2:
            return f"{slot} — {apps[0]} + {apps[1]}"
        else:
            return f"{slot} — {apps[0]} + {len(apps) - 1} more"

    # ─── DB persistence ───────────────────────────────────────

    @staticmethod
    def _routine_app_keys(apps_json: str) -> frozenset:
        """Parse stored apps JSON → frozenset of composite keys (AppName [Project] or AppName)."""
        try:
            stored = json.loads(apps_json)
            result = set()
            for a in stored:
                if isinstance(a, dict):
                    name = a.get("app_name", "")
                    proj = a.get("project_name", "")
                    result.add(f"{name} [{proj}]" if proj else name)
                else:
                    result.add(str(a))
            return frozenset(result)
        except Exception:
            return frozenset()

    @staticmethod
    def _jaccard(a: frozenset, b: frozenset) -> float:
        """Jaccard similarity between two sets."""
        if not a and not b:
            return 1.0
        union = len(a | b)
        return len(a & b) / union if union else 0.0

    async def _deduplicate_existing(self) -> int:
        """
        Merge routines in the DB that share >= 70% app overlap (Jaccard).
        Keeps the one with the highest occurrence_count; deletes the rest.
        Returns number of routines deleted.
        """
        all_routines = await self._db.get_all_routines()
        if len(all_routines) < 2:
            return 0

        # Sort best-first (highest occurrence_count) so we keep the "richest" entry
        all_routines.sort(key=lambda r: r.get("occurrence_count", 0), reverse=True)

        kept: list[tuple[dict, frozenset]] = []
        merged_count = 0

        for routine in all_routines:
            app_names = self._routine_app_keys(routine.get("apps", "[]"))

            if not app_names:
                kept.append((routine, frozenset()))
                continue

            similar_entry = next(
                (
                    (k, k_apps) for k, k_apps in kept
                    if self._jaccard(app_names, k_apps) >= 0.60
                    or app_names.issubset(k_apps)
                    or k_apps.issubset(app_names)
                ),
                None,
            )

            if similar_entry:
                winner, _ = similar_entry
                new_count = max(
                    winner.get("occurrence_count", 0),
                    routine.get("occurrence_count", 0),
                )
                await self._db.update_routine(winner["id"], occurrence_count=new_count)
                await self._db.delete_routine(routine["id"])
                merged_count += 1
                log.info(
                    "PatternAnalyzer: merged duplicate routine",
                    kept_id=winner["id"],
                    deleted_id=routine["id"],
                )
            else:
                kept.append((routine, app_names))

        return merged_count

    async def _merge_routine(self, existing: dict[str, Any], pattern: dict[str, Any]) -> None:
        """Update an existing routine: bump counts and fill in missing exe_paths."""
        # Index new payload by composite key for precise matching
        new_by_key = {
            f"{a['app_name']} [{a['project_name']}]" if a.get("project_name") else a["app_name"]: a.get("exe_path", "")
            for a in pattern["apps_payload"]
        }
        try:
            stored_apps = json.loads(existing.get("apps", "[]"))
            merged_apps = []
            for a in stored_apps:
                if isinstance(a, dict):
                    composite = f"{a['app_name']} [{a.get('project_name', '')}]" if a.get("project_name") else a["app_name"]
                    merged_apps.append({**a, "exe_path": a.get("exe_path") or new_by_key.get(composite, "")})
                else:
                    merged_apps.append(a)
        except Exception:
            merged_apps = None

        kwargs: dict[str, Any] = {
            "occurrence_count": max(existing.get("occurrence_count", 0), pattern["occurrence_count"]),
            "confidence": max(existing.get("confidence", 0.0), pattern["confidence"]),
        }
        if merged_apps is not None:
            kwargs["apps"] = json.dumps(merged_apps)
        await self._db.update_routine(existing["id"], **kwargs)

    async def _upsert_routine(self, pattern: dict[str, Any]) -> dict[str, Any] | None:
        """Save pattern as routine; skip if same or similar (>=70% Jaccard) app set already exists."""
        existing = await self._db.get_routine_by_apps(pattern["apps"])
        if existing:
            await self._merge_routine(existing, pattern)
            return None

        # Also block near-duplicates via Jaccard similarity
        new_app_set: frozenset = frozenset(pattern["apps"])
        for r in await self._db.get_all_routines():
            r_apps = self._routine_app_keys(r.get("apps", "[]"))
            if self._jaccard(new_app_set, r_apps) >= 0.70:
                await self._merge_routine(r, pattern)
                return None

        routine_id = await self._db.create_routine(
            name=pattern["name"],
            trigger_type=pattern["trigger_type"],
            trigger_data=json.dumps(pattern["trigger_data"]),
            apps=json.dumps(pattern["apps_payload"]),
            confidence=pattern["confidence"],
            occurrence_count=pattern["occurrence_count"],
            description=pattern.get("description", ""),
        )
        return await self._db.get_routine(routine_id)
