"""
Skill Creator Tool — Create and activate AI skills dynamically from chat.

Allows users to create custom skills on-the-fly by describing what they need.
The skill is automatically generated using LLM and activated immediately.
"""

import structlog
from openacm.tools.base import tool
from openacm.core.skill_manager import SkillManager

log = structlog.get_logger()


@tool(
    name="create_skill",
    description=(
        "Create a new AI skill dynamically. Use this when the user wants to:\n"
        "1. Create a specialized assistant persona (e.g., 'create a Python expert skill')\n"
        "2. Add domain-specific knowledge (e.g., 'add a skill for reviewing SQL queries')\n"
        "3. Create a coding assistant for a specific technology\n"
        "4. Define custom behavior patterns or workflows\n"
        "The skill will be generated using AI and activated immediately."
    ),
    parameters={
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Short, kebab-case name for the skill (e.g., 'python-expert', 'sql-reviewer')",
            },
            "description": {
                "type": "string",
                "description": "Brief description of what this skill does (1-2 sentences)",
            },
            "use_cases": {
                "type": "string",
                "description": "Specific scenarios when this skill should be used. List 2-3 examples starting with '-'",
            },
            "category": {
                "type": "string",
                "description": "Category for organizing the skill",
                "enum": ["security", "development", "ai", "custom"],
                "default": "custom",
            },
        },
        "required": ["name", "description", "use_cases"],
    },
    risk_level="medium",
    needs_sandbox=False,
    category="meta",
)
async def create_skill(
    name: str,
    description: str,
    use_cases: str,
    category: str = "custom",
    _brain=None,
    **kwargs,
) -> str:
    """Create a new skill dynamically using the LLM and activate it immediately."""

    if not _brain or not _brain.skill_manager:
        return "Error: Skill manager not available. Cannot create skills at this time."

    skill_manager: SkillManager = _brain.skill_manager

    # Validate name
    name = name.lower().replace(" ", "-").replace("_", "-")
    if not name.replace("-", "").isalnum():
        return f"Error: Invalid skill name '{name}'. Use only letters, numbers, and hyphens."

    # Check if skill already exists
    existing = await skill_manager.database.get_skill_by_name(name)
    if existing:
        if existing.get("is_active"):
            return f"⚠️ Skill '{name}' already exists and is active. Use it directly or delete it first to recreate."
        else:
            # Reactivate existing skill
            await skill_manager.toggle_skill(existing["id"])
            return f"✅ Skill '{name}' already existed and has been reactivated!"

    try:
        # Generate the skill using LLM
        log.info("Generating skill", name=name, category=category)

        skill_prompt = f"""Create a comprehensive skill guide for an AI assistant.

Skill Name: {name}
Description: {description}
Category: {category}
Use Cases:
{use_cases}

Write detailed instructions in Markdown format following this structure:

# {name.replace("-", " ").title()}

## Overview
What this skill does and when to use it.

## Guidelines  
Detailed instructions, best practices, and specific patterns:
- What to do in different scenarios
- How to approach problems
- Specific techniques or methodologies
- Code patterns or examples if relevant

## Examples
Concrete examples showing the skill in action:
- Example 1: Common scenario
- Example 2: Edge case
- Example 3: Best practice demonstration

## Common Pitfalls
What to avoid and why:
- Anti-patterns
- Common mistakes
- Performance traps
- Security concerns

Make it immediately actionable. The AI should be able to apply this knowledge right away.
Be specific and practical, not generic.
"""

        # Generate content using LLM
        response = await _brain.llm_router.chat(
            messages=[{"role": "user", "content": skill_prompt}],
            temperature=0.7,
            max_tokens=2000,
        )

        content = response.get("content", "").strip()

        if not content or len(content) < 100:
            return f"Error: Generated skill content is too short or empty. Please try again with a more detailed description."

        # Create the skill
        skill = await skill_manager.create_skill(
            name=name,
            description=description,
            content=content,
            category=category,
        )

        # Skill is created active by default

        # Refresh brain's skill cache
        await skill_manager._refresh_cache()

        log.info("Skill created successfully", name=name, id=skill.get("id"))

        # Return success message with preview
        preview = content[:300] + "..." if len(content) > 300 else content

        return f"""✅ **Skill '{name}' creada y activada exitosamente!**

📝 **Descripción:** {description}
📂 **Categoría:** {category}
🔢 **ID:** {skill.get("id")}

**Vista previa del contenido:**
```
{preview}
```

💡 **Esta skill ahora está activa** y se aplicará automáticamente en nuestras conversaciones. Puedes desactivarla desde el dashboard en la sección Skills si lo necesitas.

🎯 **Casos de uso:**
{use_cases}
"""

    except Exception as e:
        log.error("Failed to create skill", name=name, error=str(e))
        return f"Error creating skill: {str(e)}"


@tool(
    name="toggle_skill",
    description=(
        "Activate or deactivate an existing skill. "
        "Use this to enable/disable skills without deleting them."
    ),
    parameters={
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Name of the skill to toggle",
            },
        },
        "required": ["name"],
    },
    risk_level="low",
    needs_sandbox=False,
    category="meta",
)
async def toggle_skill(
    name: str,
    _brain=None,
    **kwargs,
) -> str:
    """Toggle a skill's active status."""

    if not _brain or not _brain.skill_manager:
        return "Error: Skill manager not available."

    skill_manager = _brain.skill_manager

    # Find skill by name
    skill = await skill_manager.database.get_skill_by_name(name.lower())
    if not skill:
        # Try partial match
        all_skills = await skill_manager.get_all_skills()
        matches = [s for s in all_skills if name.lower() in s["name"].lower()]
        if len(matches) == 1:
            skill = matches[0]
        elif len(matches) > 1:
            names = ", ".join([s["name"] for s in matches])
            return f"Multiple skills match '{name}': {names}. Please be more specific."
        else:
            all_names = ", ".join([s["name"] for s in all_skills])
            return f"Skill '{name}' not found. Available skills: {all_names}"

    try:
        new_status = not skill.get("is_active", False)
        await skill_manager.toggle_skill(skill["id"])

        status_text = "activada" if new_status else "desactivada"
        emoji = "✅" if new_status else "⏸️"

        return f"{emoji} Skill '{skill['name']}' {status_text} exitosamente."

    except Exception as e:
        return f"Error toggling skill: {str(e)}"


@tool(
    name="list_skills",
    description=(
        "List all available skills with their status. "
        "Shows which skills are active and their categories."
    ),
    parameters={
        "type": "object",
        "properties": {
            "show_inactive": {
                "type": "boolean",
                "description": "Whether to show inactive skills too",
                "default": True,
            },
        },
    },
    risk_level="low",
    needs_sandbox=False,
    category="meta",
)
async def list_skills(
    show_inactive: bool = True,
    _brain=None,
    **kwargs,
) -> str:
    """List all skills with their status."""

    if not _brain or not _brain.skill_manager:
        return "Error: Skill manager not available."

    skill_manager = _brain.skill_manager

    try:
        skills = await skill_manager.get_all_skills()

        if not skills:
            return "No skills found. Create one with 'create_skill'!"

        active_skills = [s for s in skills if s.get("is_active")]
        inactive_skills = [s for s in skills if not s.get("is_active")]

        lines = ["🧠 **Skills Disponibles**\n"]

        if active_skills:
            lines.append(f"\n✅ **Activas ({len(active_skills)}):**")
            for skill in active_skills:
                cat_emoji = {"security": "🔒", "development": "💻", "ai": "🧠", "custom": "⚙️"}.get(
                    skill.get("category", "custom"), "⚙️"
                )
                builtin = " 📦" if skill.get("is_builtin") else ""
                lines.append(
                    f"  • {cat_emoji} **{skill['name']}** - {skill['description']}{builtin}"
                )

        if show_inactive and inactive_skills:
            lines.append(f"\n⏸️ **Inactivas ({len(inactive_skills)}):**")
            for skill in inactive_skills:
                lines.append(f"  • {skill['name']} - {skill['description']}")

        lines.append(
            f"\n💡 Usa `toggle_skill` para activar/desactivar, o `create_skill` para crear nuevas."
        )

        return "\n".join(lines)

    except Exception as e:
        return f"Error listing skills: {str(e)}"


@tool(
    name="delete_skill",
    description=(
        "Delete a custom skill permanently. "
        "Built-in skills cannot be deleted, only deactivated. "
        "Use with caution - this action cannot be undone."
    ),
    parameters={
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Name of the custom skill to delete",
            },
            "confirm": {
                "type": "boolean",
                "description": "Must be true to confirm deletion",
                "default": False,
            },
        },
        "required": ["name"],
    },
    risk_level="high",
    needs_sandbox=False,
    category="meta",
)
async def delete_skill(
    name: str,
    confirm: bool = False,
    _brain=None,
    **kwargs,
) -> str:
    """Delete a custom skill permanently."""

    if not _brain or not _brain.skill_manager:
        return "Error: Skill manager not available."

    skill_manager = _brain.skill_manager

    # Find skill
    skill = await skill_manager.database.get_skill_by_name(name.lower())
    if not skill:
        return f"Skill '{name}' not found."

    if skill.get("is_builtin"):
        return f"❌ Cannot delete built-in skill '{name}'. You can only deactivate it using `toggle_skill`."

    if not confirm:
        return f"⚠️ Are you sure you want to delete skill '{name}'? This cannot be undone.\n\nTo confirm, call delete_skill again with confirm=true"

    try:
        success = await skill_manager.delete_skill(skill["id"])
        if success:
            return f"🗑️ Skill '{name}' has been permanently deleted."
        else:
            return f"Error: Could not delete skill '{name}'."
    except Exception as e:
        return f"Error deleting skill: {str(e)}"
