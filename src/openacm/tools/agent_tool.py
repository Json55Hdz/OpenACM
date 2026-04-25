"""
Agent Tool — create and manage autonomous agents from the chat.
"""

import os
import secrets
from openacm.tools.base import tool


@tool(
    name="create_agent",
    description=(
        "[OpenACM Tool] Create a new autonomous agent with custom rules and personality. "
        "Use this when the user asks to create a bot, assistant, or automated responder. "
        "The agent gets its own webhook URL that can be connected to any service. "
        "EXAMPLES: 'create a support bot for my store', 'make an agent that answers FAQs in Spanish', "
        "'create a sales assistant that knows our pricing'"
    ),
    parameters={
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Short agent name (2-4 words)",
            },
            "description": {
                "type": "string",
                "description": "One-sentence description of what the agent does",
            },
            "system_prompt": {
                "type": "string",
                "description": "Full system prompt with the agent's rules, personality and behavior",
            },
            "allowed_tools": {
                "type": "string",
                "description": "'all' to give the agent access to all tools, 'none' for text-only",
                "default": "none",
            },
        },
        "required": ["name", "description", "system_prompt"],
    },
    risk_level="low",
    category="general",
)
async def create_agent(
    name: str,
    description: str,
    system_prompt: str,
    allowed_tools: str = "none",
    **kwargs,
) -> str:
    """Create an autonomous agent and return its webhook details."""
    brain = kwargs.get("_brain")
    if not brain or not hasattr(brain, "memory") or not brain.memory:
        return "Error: database not available"

    db = brain.memory.database
    if not db:
        return "Error: database not available"

    webhook_secret = secrets.token_urlsafe(32)
    agent_id = await db.create_agent(
        name=name,
        description=description,
        system_prompt=system_prompt,
        allowed_tools=allowed_tools,
        webhook_secret=webhook_secret,
    )

    import os
    port = os.environ.get("OPENACM_PORT", "47821")
    webhook_url = f"http://localhost:{port}/api/agents/{agent_id}/chat"
    ui_url = f"http://localhost:{port}/agents"

    return (
        f"✅ Agent **{name}** creado (ID: {agent_id})\n\n"
        f"**Webhook URL:**\n`{webhook_url}`\n\n"
        f"**Secret (X-Agent-Secret header):**\n`{webhook_secret}`\n\n"
        f"**Tools:** {allowed_tools}\n\n"
        f"Llama al webhook con:\n"
        f"```\nPOST {webhook_url}\n"
        f"X-Agent-Secret: {webhook_secret}\n"
        f'Body: {{"message": "hello", "user_id": "user123"}}\n```\n\n'
        f"[Ver Agentes →]({ui_url})"
    )


def _get_db(brain):
    if brain and hasattr(brain, "memory") and brain.memory:
        return brain.memory.database
    return None


@tool(
    name="list_agents",
    description=(
        "List all autonomous agents configured in OpenACM. "
        "Shows each agent's name, description, allowed tools, and webhook URL."
    ),
    parameters={
        "type": "object",
        "properties": {},
        "required": [],
    },
    risk_level="low",
    category="general",
)
async def list_agents(_brain=None, **kwargs) -> str:
    db = _get_db(_brain)
    if not db:
        return "Error: database not available."
    agents = await db.get_all_agents()
    port = os.environ.get("OPENACM_PORT", "47821")
    if not agents:
        return f"No hay agentes creados aún.\n\n[Ir a Agentes →](http://localhost:{port}/agents)"
    lines = [f"**Agentes ({len(agents)}):**\n"]
    for a in agents:
        lines.append(
            f"- **[{a['id']}] {a['name']}** — {a.get('description', '')}\n"
            f"  Tools: {a.get('allowed_tools', 'none')} | "
            f"[Ver →](http://localhost:{port}/agents)"
        )
    lines.append(f"\n[Gestionar Agentes →](http://localhost:{port}/agents)")
    return "\n".join(lines)


@tool(
    name="delete_agent",
    description="Delete an autonomous agent by its ID. This cannot be undone.",
    parameters={
        "type": "object",
        "properties": {
            "agent_id": {
                "type": "integer",
                "description": "The numeric ID of the agent to delete.",
            },
        },
        "required": ["agent_id"],
    },
    risk_level="high",
    category="general",
)
async def delete_agent(agent_id: int, _brain=None, **kwargs) -> str:
    db = _get_db(_brain)
    if not db:
        return "Error: database not available."
    agent = await db.get_agent(agent_id)
    if not agent:
        return f"Agente {agent_id} no encontrado."
    await db.delete_agent(agent_id)
    port = os.environ.get("OPENACM_PORT", "47821")
    return (
        f"🗑️ Agente **{agent['name']}** (ID: {agent_id}) eliminado.\n\n"
        f"[Ver Agentes →](http://localhost:{port}/agents)"
    )
