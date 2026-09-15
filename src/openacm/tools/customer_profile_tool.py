"""
Customer Profile Tool — lets an agent remember a customer's name for this
conversation, independent of memory_ttl resets (see MemoryManager.get_or_create
and AgentRunner.run's customer-name injection).
"""

from openacm.tools.base import tool


@tool(
    name="save_customer_name",
    description=(
        "Save the customer's name for this conversation. Call this as soon as the "
        "customer tells you their name — it's remembered permanently for this chat, "
        "even after the conversation context resets, so future messages can greet "
        "them by name."
    ),
    parameters={
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "The customer's name, as they gave it.",
            },
        },
        "required": ["name"],
    },
    risk_level="low",
    category="ai",
)
async def save_customer_name(name: str, **kwargs) -> str:
    brain = kwargs.get("_brain")
    user_id = kwargs.get("_user_id", "")
    channel_id = kwargs.get("_channel_id", "")

    if brain is None or not getattr(brain, "memory", None) or not brain.memory.database:
        return "Error: database context not available."

    clean_name = name.strip()
    if not clean_name:
        return "Error: 'name' cannot be empty."

    await brain.memory.database.set_customer_name(user_id, channel_id, clean_name)
    return f"Saved: this customer's name is '{clean_name}'."
