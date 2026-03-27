"""
Tool Creator — Dynamically create and register new Python tools.

Allows users to create custom tools from chat that are saved to disk
and immediately available for use.
"""

import structlog
import re
from pathlib import Path
from datetime import datetime

from openacm.tools.base import tool

log = structlog.get_logger()

TOOLS_DIR = Path("src/openacm/tools")


def validate_python_code(code: str) -> tuple[bool, str]:
    """Validate that the code is syntactically correct Python."""
    try:
        compile(code, "<string>", "exec")
        return True, ""
    except SyntaxError as e:
        return False, f"Syntax error at line {e.lineno}: {e.msg}"


def sanitize_filename(name: str) -> str:
    """Convert tool name to safe filename."""
    # Convert to lowercase, replace spaces and special chars
    safe = re.sub(r"[^a-zA-Z0-9_-]", "_", name.lower())
    safe = re.sub(r"_+", "_", safe)  # Collapse multiple underscores
    return safe.strip("_")


@tool(
    name="create_tool",
    description=(
        "Create a new Python tool dynamically and save it to disk. "
        "Use this when the user wants to:\n"
        "1. Create a custom automation script\n"
        "2. Add a new capability to OpenACM\n"
        "3. Create a reusable function for common tasks\n"
        "4. Extend OpenACM with domain-specific functionality\n"
        "The tool will be saved as a Python file and registered immediately."
    ),
    parameters={
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Tool name in snake_case (e.g., 'file_analyzer', 'api_validator')",
            },
            "description": {
                "type": "string",
                "description": "What this tool does (1-2 sentences for the LLM to understand when to use it)",
            },
            "parameters": {
                "type": "string",
                "description": 'JSON schema description of parameters. Example: \'{"url": "The URL to fetch", "timeout": "Timeout in seconds"}\'',
            },
            "code": {
                "type": "string",
                "description": "Complete Python code for the tool function. Must be valid Python with proper indentation. Include imports and the async function.",
            },
        },
        "required": ["name", "description", "parameters", "code"],
    },
    risk_level="high",
    needs_sandbox=False,
)
async def create_tool(
    name: str,
    description: str,
    parameters: str,
    code: str,
    **kwargs,
) -> str:
    """Create a new tool file and register it."""

    # Validate name
    safe_name = sanitize_filename(name)
    if not safe_name or safe_name[0].isdigit():
        return f"❌ Invalid tool name '{name}'. Use letters, numbers, hyphens, underscores. Cannot start with a number."

    # Check if file already exists
    tool_file = TOOLS_DIR / f"{safe_name}.py"
    if tool_file.exists():
        return (
            f"⚠️ Tool file '{safe_name}.py' already exists. Delete it first or use a different name."
        )

    # Validate Python code
    is_valid, error_msg = validate_python_code(code)
    if not is_valid:
        return f"❌ Python syntax error:\n{error_msg}\n\nPlease fix the code and try again."

    try:
        # Generate complete tool file content
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        file_content = f'''"""
{safe_name.replace("_", " ").title()} Tool — {description}

Generated automatically on {timestamp}
"""

import structlog
from openacm.tools.base import tool

log = structlog.get_logger()


@tool(
    name="{safe_name}",
    description="""{description}""",
    parameters={{
        "type": "object",
        "properties": {{
{format_parameters(parameters)}
        }},
        "required": [{get_required_params(parameters)}],
    }},
    risk_level="medium",
    needs_sandbox=False,
)
async def {safe_name}(
{get_function_signature(parameters)}
    **kwargs,
) -> str:
    """{description}"""
    
{indent_code(code)}


# Make function available at module level
__all__ = ["{safe_name}"]
'''

        # Write file
        tool_file.write_text(file_content, encoding="utf-8")
        log.info("Tool file created", file=str(tool_file))

        # Success message with instructions
        return f"""✅ **Tool '{safe_name}' creado exitosamente!**

📁 **Ubicación:** `{tool_file}`
📝 **Descripción:** {description}
⚡ **Estado:** Guardado en disco

🔧 **Para activar este tool, necesitas:**

1. **Reiniciar OpenACM** (o recargar el módulo)
2. El tool se registrará automáticamente al inicio

💡 **Uso desde el chat:**
Una vez activo, puedes usarlo diciendo:
- "Ejecuta {safe_name} con..."
- "Usa el tool {safe_name} para..."

⚠️ **Nota importante:** Los tools se guardan en disco pero requieren reinicio para cargar.
Esto es una medida de seguridad para evitar ejecución de código no verificado.

🎯 **Siguiente paso:** Reinicia OpenACM para usar el nuevo tool.

**Vista previa del código:**
```python
{code[:500]}{"..." if len(code) > 500 else ""}
```
"""

    except Exception as e:
        log.error("Failed to create tool", name=name, error=str(e))
        return f"❌ Error creating tool: {str(e)}"


@tool(
    name="edit_tool",
    description="Edit an existing custom tool file. Use to fix bugs or improve functionality.",
    parameters={
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Name of the tool to edit",
            },
            "code": {
                "type": "string",
                "description": "New complete Python code to replace the existing function",
            },
        },
        "required": ["name", "code"],
    },
    risk_level="high",
    needs_sandbox=False,
)
async def edit_tool(
    name: str,
    code: str,
    **kwargs,
) -> str:
    """Edit an existing tool file."""

    safe_name = sanitize_filename(name)
    tool_file = TOOLS_DIR / f"{safe_name}.py"

    if not tool_file.exists():
        return f"❌ Tool '{name}' not found. Use `create_tool` to create a new one."

    # Check if it's a built-in tool (prevent editing system tools)
    current_content = tool_file.read_text()
    if "Generated automatically" not in current_content and "Built-in" in current_content:
        return f"⚠️ Cannot edit built-in tool '{name}'. Create a copy with a different name."

    # Validate new code
    is_valid, error_msg = validate_python_code(code)
    if not is_valid:
        return f"❌ Python syntax error:\n{error_msg}"

    try:
        # Create backup
        backup_file = tool_file.with_suffix(".py.bak")
        backup_file.write_text(current_content)

        # Replace function body in file
        # This is a simple replacement - in production, use AST parsing
        new_content = re.sub(
            r"async def .*?\([^)]*\) -> str:.*?\n{6}",
            f'async def {safe_name}(\n    **kwargs,\n) -> str:\n    """Tool function"""\n    \n{indent_code(code)}\n\n\n',
            current_content,
            flags=re.DOTALL,
        )

        tool_file.write_text(new_content)

        return f"""✅ **Tool '{safe_name}' actualizado!**

💾 **Backup creado:** `{backup_file}`
📝 **Cambios guardados en:** `{tool_file}`

⚠️ **Reinicio requerido** para aplicar los cambios.
"""

    except Exception as e:
        return f"❌ Error updating tool: {str(e)}"


@tool(
    name="delete_tool",
    description="Delete a custom tool file permanently. Built-in tools cannot be deleted.",
    parameters={
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Name of the tool to delete",
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
)
async def delete_tool(
    name: str,
    confirm: bool = False,
    **kwargs,
) -> str:
    """Delete a tool file."""

    safe_name = sanitize_filename(name)
    tool_file = TOOLS_DIR / f"{safe_name}.py"

    if not tool_file.exists():
        return f"❌ Tool '{name}' not found."

    # Check if built-in
    content = tool_file.read_text()
    if "Generated automatically" not in content:
        return f"⚠️ Cannot delete built-in tool '{name}'. Only custom tools can be deleted."

    if not confirm:
        return f"⚠️ Are you sure you want to delete tool '{name}'?\n\nThis will permanently remove the file:\n`{tool_file}`\n\nTo confirm, call delete_tool with confirm=true"

    try:
        tool_file.unlink()
        return f"🗑️ **Tool '{name}' eliminado permanentemente.**\n\n📁 Archivo eliminado: `{tool_file}`\n\n⚠️ Reinicia OpenACM para completar la eliminación."
    except Exception as e:
        return f"❌ Error deleting tool: {str(e)}"


@tool(
    name="list_tools",
    description="List all available tools, showing which are built-in vs custom.",
    parameters={
        "type": "object",
        "properties": {},
    },
    risk_level="low",
    needs_sandbox=False,
)
async def list_tools(**kwargs) -> str:
    """List all tools in the tools directory."""

    try:
        tools = []
        for file in TOOLS_DIR.glob("*.py"):
            if file.name.startswith("_"):
                continue

            content = file.read_text()
            is_custom = "Generated automatically" in content

            # Extract description from @tool decorator
            desc_match = re.search(r'description="""(.*?)"""', content, re.DOTALL)
            description = (
                desc_match.group(1)[:80] + "..."
                if desc_match and len(desc_match.group(1)) > 80
                else desc_match.group(1)
                if desc_match
                else "No description"
            )

            tools.append(
                {
                    "name": file.stem,
                    "custom": is_custom,
                    "description": description.strip(),
                }
            )

        tools.sort(key=lambda x: (not x["custom"], x["name"]))

        lines = ["🔧 **Tools Disponibles**\n"]

        built_ins = [t for t in tools if not t["custom"]]
        customs = [t for t in tools if t["custom"]]

        if built_ins:
            lines.append(f"📦 **Built-in ({len(built_ins)}):**")
            for t in built_ins:
                lines.append(f"  • {t['name']} - {t['description']}")

        if customs:
            lines.append(f"\n✨ **Custom ({len(customs)}):**")
            for t in customs:
                lines.append(f"  • {t['name']} - {t['description']}")

        lines.append(f"\n💡 Usa `create_tool` para agregar nuevos tools personalizados.")
        lines.append(f"📁 Ubicación: `{TOOLS_DIR}`")

        return "\n".join(lines)

    except Exception as e:
        return f"❌ Error listing tools: {str(e)}"


# Helper functions


def format_parameters(params_str: str) -> str:
    """Format parameters for JSON schema."""
    lines = []
    # Simple parsing - assumes format: "name": "description"
    for line in params_str.strip().split("\n"):
        line = line.strip().strip(",").strip('"')
        if ":" in line:
            key, desc = line.split(":", 1)
            key = key.strip().strip('"')
            desc = desc.strip().strip('"')
            lines.append(f'            "{key}": {{"type": "string", "description": "{desc}"}},')
    return "\n".join(lines)


def get_required_params(params_str: str) -> str:
    """Extract required parameter names."""
    required = []
    for line in params_str.strip().split("\n"):
        line = line.strip().strip(",").strip('"')
        if ":" in line and "(optional)" not in line.lower():
            key = line.split(":")[0].strip().strip('"')
            required.append(f'"{key}"')
    return ", ".join(required)


def get_function_signature(params_str: str) -> str:
    """Generate function signature from parameters."""
    params = []
    for line in params_str.strip().split("\n"):
        line = line.strip().strip(",").strip('"')
        if ":" in line:
            key = line.split(":")[0].strip().strip('"')
            params.append(f"    {key}: str,")
    return "\n".join(params) if params else "    # No parameters"


def indent_code(code: str) -> str:
    """Indent code with proper spacing."""
    lines = code.strip().split("\n")
    return "\n".join("    " + line for line in lines)


__all__ = ["create_tool", "edit_tool", "delete_tool", "list_tools"]
