"""
Swarm tools — let the Brain create, list, and start swarms from the chat.

_swarm_manager is injected by app.py after SwarmManager is initialized
(same pattern as cron_tool._cron_scheduler).
"""

import structlog
from openacm.tools.base import tool

log = structlog.get_logger()

# Injected by app.py after initialization
_swarm_manager = None


@tool(
    name="create_swarm",
    description=(
        "Create a multi-agent swarm to accomplish a complex project goal. "
        "The AI will automatically design a team of specialized worker agents, "
        "assign roles, and plan the tasks. Use this when the user wants to launch "
        "a team of agents to build software, analyze documents, research topics, "
        "generate content, or any other multi-step project. "
        "Pass any file contents the user uploaded directly in the 'context' field."
    ),
    parameters={
        "type": "object",
        "properties": {
            "goal": {
                "type": "string",
                "description": "Detailed description of what the swarm should accomplish.",
            },
            "name": {
                "type": "string",
                "description": "Short display name for the swarm (optional).",
            },
            "global_model": {
                "type": "string",
                "description": (
                    "LiteLLM model string for all workers, e.g. 'anthropic/claude-opus-4-6'. "
                    "Leave empty to use the system default."
                ),
            },
            "context": {
                "type": "string",
                "description": (
                    "Extra context shared with all workers — paste file contents, "
                    "specs, or any data the team needs to understand the project."
                ),
            },
            "auto_start": {
                "type": "boolean",
                "description": "If true, start execution immediately after planning. Default false.",
            },
        },
        "required": ["goal"],
    },
    risk_level="medium",
    category="swarm",
)
async def create_swarm(
    goal: str,
    name: str = "",
    global_model: str = "",
    context: str = "",
    auto_start: bool = False,
    _brain=None,
    **kwargs,
) -> str:
    if _swarm_manager is None:
        return "Swarm manager is not available. Restart OpenACM and try again."

    if not goal.strip():
        return "A goal is required to create a swarm."

    effective_name = name.strip() or f"Swarm: {goal[:50]}"
    global_model_val = global_model.strip() or None

    file_contents = []
    if context.strip():
        file_contents.append({"filename": "context.md", "content": context.strip()})

    try:
        swarm = await _swarm_manager.create_swarm(
            name=effective_name,
            goal=goal,
            file_contents=file_contents or None,
            global_model=global_model_val,
        )
        swarm_id = swarm["id"]

        planned = await _swarm_manager.plan_swarm(swarm_id)
        workers = await _swarm_manager.db.get_swarm_workers(swarm_id)
        tasks = await _swarm_manager.db.get_swarm_tasks(swarm_id)

        summary = (
            f"✅ Swarm **{effective_name}** created (ID: {swarm_id})\n\n"
            f"**Team ({len(workers)} workers):**\n"
            + "\n".join(
                f"- **{w['name']}** ({w['role']}): {w.get('description', '')}"
                for w in workers
            )
            + f"\n\n**Tasks ({len(tasks)}):**\n"
            + "\n".join(f"- {t['title']}" for t in tasks)
            + "\n\nVe a la pestaña **Swarms** para verlo y gestionarlo."
        )

        if auto_start:
            await _swarm_manager.start_swarm(swarm_id)
            summary += "\n\n🚀 Ejecución iniciada — workers corriendo en paralelo."
        else:
            summary += "\n\nEl swarm está listo. Pulsa **Start** en la pestaña Swarms o dime que lo inicie."

        return summary

    except Exception as e:
        log.error("create_swarm tool failed", error=str(e))
        return f"Error al crear el swarm: {e}"


@tool(
    name="start_swarm",
    description="Start execution of a planned or paused swarm by its ID.",
    parameters={
        "type": "object",
        "properties": {
            "swarm_id": {
                "type": "integer",
                "description": "The numeric ID of the swarm to start.",
            },
        },
        "required": ["swarm_id"],
    },
    risk_level="medium",
    category="swarm",
)
async def start_swarm(swarm_id: int, _brain=None, **kwargs) -> str:
    if _swarm_manager is None:
        return "Swarm manager is not available."
    try:
        swarm = await _swarm_manager.db.get_swarm(swarm_id)
        if not swarm:
            return f"Swarm {swarm_id} not found."
        if swarm["status"] not in ("planned", "paused"):
            return f"El swarm {swarm_id} está en estado '{swarm['status']}' — solo se puede iniciar si está en 'planned' o 'paused'."
        await _swarm_manager.start_swarm(swarm_id)
        return f"🚀 Swarm '{swarm['name']}' (ID: {swarm_id}) iniciado."
    except Exception as e:
        return f"Error al iniciar el swarm: {e}"


@tool(
    name="list_swarms",
    description="List all swarms and their current status.",
    parameters={
        "type": "object",
        "properties": {},
        "required": [],
    },
    risk_level="low",
    category="swarm",
)
async def list_swarms(_brain=None, **kwargs) -> str:
    if _swarm_manager is None:
        return "Swarm manager is not available."
    try:
        swarms = await _swarm_manager.db.list_swarms()
        if not swarms:
            return "No hay swarms creados aún."
        lines = []
        for s in swarms:
            lines.append(
                f"- **[{s['id']}] {s['name']}** — {s['status']} "
                f"({s.get('worker_count', 0)} workers, {s.get('task_count', 0)} tasks)"
            )
        return "**Swarms:**\n" + "\n".join(lines)
    except Exception as e:
        return f"Error al listar swarms: {e}"
