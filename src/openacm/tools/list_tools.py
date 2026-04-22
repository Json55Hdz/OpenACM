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
        "or 'all' to see both."
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
        },
        "required": [],
    },
    risk_level="low",
    category="meta",
)
async def list_tools(what: str = "tools", category: str = "", **kwargs) -> str:
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
            if category:
                tools_list = [t for t in tools_list if t.category == category]

            if not tools_list:
                sections.append(f"## Tools\n(none registered{f' in category {category!r}' if category else ''})")
            else:
                # Group by category for readability
                by_cat: dict[str, list] = {}
                for t in sorted(tools_list, key=lambda x: (x.category, x.name)):
                    by_cat.setdefault(t.category, []).append(t)

                lines = [f"## Tools ({len(tools_list)} registered)\n"]
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
