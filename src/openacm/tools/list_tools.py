"""
List Tools / List Skills — lets the AI report what's actually registered.

Prevents the AI from confusing skills with tools by giving it a programmatic
source of truth instead of inferring from the system prompt.
"""

from openacm.tools.base import tool


@tool(
    name="list_tools",
    description=(
        "List all tools and/or skills currently registered in OpenACM. "
        "Use this when the user asks what you can do, what tools are available, "
        "or what skills are active. "
        "Set what='tools' for executable tools, 'skills' for behavior instructions, "
        "or 'all' to see both. This reads the live registry: ONE call lists everything, so "
        "never browse source files to find out which tools exist. "
        "Use agent_id to see exactly which tools one agent has, and query to search by word."
    ),
    parameters={
        "type": "object",
        "properties": {
            "what": {
                "type": "string",
                "enum": ["tools", "skills", "all"],
                "description": "What to list: 'tools' (executable), 'skills' (context/behavior), or 'all'.",
                "default": "tools",
            },
            "category": {
                "type": "string",
                "description": "Optional: filter by category (e.g. 'system', 'file', 'web', 'ai').",
            },
            "query": {
                "type": "string",
                "description": "Optional: only tools whose name or description contains this word.",
            },
            "agent_id": {
                "type": "integer",
                "description": "Optional: list only the tools that this agent (see list_agents) is allowed to use.",
            },
        },
        "required": [],
    },
    risk_level="low",
    category="meta",
)
async def _agent_allowed_names(brain, agent_id: int, all_names: set[str]) -> tuple[set[str] | None, str]:
    """(names the agent may use, note). None = unknown agent."""
    import json

    db = getattr(brain, "database", None)
    agent = await db.get_agent(int(agent_id)) if db is not None else None
    if not agent:
        return None, f"No agent with id {agent_id}."
    policy = str(agent.get("allowed_tools") or "all").strip()
    if policy == "all":
        return set(all_names), f"Agent '{agent.get('name')}' can use every tool."
    if policy == "none":
        return set(), f"Agent '{agent.get('name')}' has no tools (text only)."
    try:
        listed = {str(n) for n in json.loads(policy)}
    except (ValueError, TypeError):
        return set(), f"Agent '{agent.get('name')}' has an unreadable tool policy, so it exposes no tools."
    return listed & all_names, f"Agent '{agent.get('name')}' has an explicit list of {len(listed)} tools."


async def list_tools(what: str = "tools", category: str = "", query: str = "", agent_id: int | None = None, **kwargs) -> str:
    brain = kwargs.get("_brain")
    if brain is None:
        return "Error: brain context not available."

    sections: list[str] = []

    # ── Tools ──────────────────────────────────────────────────────────────────
    if what in ("tools", "all"):
        registry = getattr(brain, "tool_registry", None)
        if registry is None:
            sections.append("## Tools\n(registry not available)")
        else:
            tools_list = list(registry.tools.values())
            agent_note = ""
            if agent_id is not None:
                allowed, agent_note = await _agent_allowed_names(brain, agent_id, {t.name for t in tools_list})
                if allowed is None:
                    return agent_note
                tools_list = [t for t in tools_list if t.name in allowed]
            if category:
                tools_list = [t for t in tools_list if t.category == category]
            if query:
                q = query.lower()
                tools_list = [t for t in tools_list if q in t.name.lower() or q in (t.description or "").lower()]

            if not tools_list:
                sections.append(f"## Tools\n(none registered{f' in category {category!r}' if category else ''})")
            else:
                # Group by category for readability
                by_cat: dict[str, list] = {}
                for t in sorted(tools_list, key=lambda x: (x.category, x.name)):
                    by_cat.setdefault(t.category, []).append(t)

                lines = [f"## Tools ({len(tools_list)} registered)\n"]
                if agent_note:
                    lines.append(agent_note + chr(10))
                for cat, cat_tools in sorted(by_cat.items()):
                    lines.append(f"**{cat.upper()}**")
                    for t in cat_tools:
                        # First sentence of description only
                        desc = (t.description or "").split(".")[0].strip()
                        risk = f" ⚠️[{t.risk_level}]" if t.risk_level in ("medium", "high") else ""
                        lines.append(f"  • `{t.name}`{risk} — {desc}")
                    lines.append("")
                sections.append("\n".join(lines))

    # ── Skills ─────────────────────────────────────────────────────────────────
    if what in ("skills", "all"):
        skill_manager = getattr(brain, "skill_manager", None)
        if skill_manager is None:
            sections.append("## Skills\n(skill manager not available)")
        else:
            try:
                all_skills = await skill_manager.get_all_skills()
                if category:
                    all_skills = [s for s in all_skills if s.get("category") == category]

                if not all_skills:
                    sections.append(f"## Skills\n(none{f' in category {category!r}' if category else ''})")
                else:
                    active = [s for s in all_skills if s.get("is_active")]
                    inactive = [s for s in all_skills if not s.get("is_active")]

                    lines = [f"## Skills ({len(all_skills)} total, {len(active)} active)\n"]
                    lines.append("**IMPORTANT: Skills are behavior/context instructions — they are NOT callable tools.**\n")

                    if active:
                        lines.append("**ACTIVE** (injected into every relevant prompt):")
                        for s in sorted(active, key=lambda x: x.get("name", "")):
                            desc = (s.get("description") or "").split(".")[0].strip()
                            cat = s.get("category", "general")
                            lines.append(f"  ✓ `{s['name']}` [{cat}] — {desc}")
                        lines.append("")

                    if inactive:
                        lines.append("**INACTIVE:**")
                        for s in sorted(inactive, key=lambda x: x.get("name", "")):
                            desc = (s.get("description") or "").split(".")[0].strip()
                            lines.append(f"  ○ `{s['name']}` — {desc}")

                    sections.append("\n".join(lines))
            except Exception as e:
                sections.append(f"## Skills\n(error fetching: {e})")

    if not sections:
        return "Nothing to list. Use what='tools', 'skills', or 'all'."

    header = (
        "─── TOOLS vs SKILLS ───────────────────────────────────────\n"
        "Tools   = executable Python functions the AI can CALL.\n"
        "Skills  = markdown instructions that shape how the AI THINKS.\n"
        "───────────────────────────────────────────────────────────\n\n"
    )
    return header + "\n\n".join(sections)
