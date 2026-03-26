"""
RAG Tools — let the LLM actively search and store long-term memories.
"""

from openacm.tools.base import tool


@tool(
    name="remember_note",
    description=(
        "Save a specific piece of information, fact, or user preference to long-term memory. "
        "Use this when the user asks you to remember something, or when you learn an important "
        "fact about the user that might be useful later (e.g. 'My name is Juan', 'I prefer dark mode')."
    ),
    parameters={
        "type": "object",
        "properties": {
            "note": {
                "type": "string",
                "description": "The information to remember. Be specific and descriptive.",
            },
        },
        "required": ["note"],
    },
    risk_level="low",
)
async def remember_note(note: str, **kwargs) -> str:
    """Save a note to long-term memory."""
    _event_bus = kwargs.get("_event_bus")
    
    # Access RAG engine through a global reference
    try:
        from openacm.core.rag import _rag_engine
        if _rag_engine and _rag_engine.is_ready:
            await _rag_engine.remember(note)
            return f"✅ Remembered: '{note[:80]}{'...' if len(note) > 80 else ''}'"
        else:
            return "⚠️ Long-term memory is not available right now."
    except Exception as e:
        return f"Error saving to memory: {str(e)}"


@tool(
    name="search_memory",
    description=(
        "Search your long-term memory for relevant information from past conversations, "
        "saved notes, or ingested documents. Use this when the user asks 'do you remember...', "
        "'what did I tell you about...', or when you need context from past interactions."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The search query — what you're looking for in your memory.",
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum number of memory fragments to retrieve (default: 5).",
                "default": 5,
            },
        },
        "required": ["query"],
    },
    risk_level="low",
)
async def search_memory(query: str, max_results: int = 5, **kwargs) -> str:
    """Search long-term memory."""
    try:
        from openacm.core.rag import _rag_engine
        if _rag_engine and _rag_engine.is_ready:
            results = await _rag_engine.query(query, top_k=max_results)
            if not results:
                return f"No memories found for: '{query}'"
            
            output = [f"🧠 Found {len(results)} memory fragments for: '{query}'\n"]
            for i, fragment in enumerate(results, 1):
                # Truncate very long fragments
                text = fragment[:300] + "..." if len(fragment) > 300 else fragment
                output.append(f"  [{i}] {text}\n")
            
            return "\n".join(output)
        else:
            return "⚠️ Long-term memory is not available right now."
    except Exception as e:
        return f"Error searching memory: {str(e)}"
