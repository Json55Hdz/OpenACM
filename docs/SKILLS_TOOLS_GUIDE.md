# OpenACM Skills & Tools File Structure

## Overview

| Type | Location | Format | Activation |
|------|----------|--------|------------|
| **Skills** | `./skills/{category}/` | `.md` with frontmatter | Automatic on creation (DB + file) |
| **Tools** | `src/openacm/tools/` | `.py` with `@tool` decorator | Restart required |

---

## Skills - `./skills/`

Skills are **behavioral guides** for the LLM model. They are saved as Markdown files with metadata in the frontmatter.

### Directory Structure

```
skills/
├── security/          # Security skills
│   └── security-auditor.md
├── development/       # Development skills
│   ├── code-reviewer.md
│   ├── fastapi-expert.md
│   └── database-architect.md
├── ai/               # AI/ML skills
│   └── rag-optimizer.md
├── custom/           # User custom skills
│   └── my-custom-skill.md
└── generated/        # AI-generated skills
    └── django-expert-20250327.md
```

### SKILL.md File Format

```markdown
---
name: "skill-name"
description: "Brief description of what it does"
category: "development"
created: "2025-03-27T10:30:00"
---

# Skill Name

## Overview
Detailed description and when to use this skill.

## Guidelines
Specific instructions, best practices, patterns to follow:
- Point 1
- Point 2
- Point 3

## Examples
Concrete examples:
- Example 1: Common scenario
- Example 2: Edge case

## Common Pitfalls
What to avoid:
- Anti-pattern 1
- Common mistake 2
```

### Recommended Categories

- `security` - Auditing, vulnerabilities, security best practices
- `development` - Programming, API design, databases
- `ai` - Machine learning, RAG, prompt engineering
- `custom` - User custom skills
- `generated` - Skills automatically created by the system

### How to Create Skills

#### Option 1: From Chat (Automatic)
```
You: Create a skill to be an expert in Django

[The bot automatically:]
1. Generates content with AI
2. Saves to: skills/generated/django-expert.md
3. Saves metadata in SQLite
4. Activates immediately
```

#### Option 2: Manually (File)
1. Create file: `skills/custom/my-skill.md`
2. Fill in with SKILL.md format
3. Restart OpenACM (syncs files to DB)

#### Option 3: Web Dashboard
- Go to "Skills" section
- Click "+ New Skill"
- Complete the form
- Automatically saved to file + DB

---

## Tools - `src/openacm/tools/`

Tools are **executable Python functions** that OpenACM can call. They are saved as `.py` files with the `@tool` decorator.

### Directory Structure

```
src/openacm/tools/
├── __init__.py
├── base.py                 # Base class and @tool decorator
├── registry.py            # ToolRegistry
│
├── system_cmd.py          # System commands
├── file_ops.py           # File operations
├── web_search.py         # Web search
├── browser_agent.py      # Browser automation
├── python_kernel.py      # Python execution
├── google_services.py    # Google integration
├── screenshot.py         # Screenshots
├── rag_tools.py          # RAG tools
├── system_info.py        # System information
│
├── skill_creator.py      # Skill creator
└── tool_creator.py       # Tool creator
```

### TOOL.py File Format

```python
"""
tool-name.py - Short description

Longer description of the tool.
"""

import structlog
from openacm.tools.base import tool

log = structlog.get_logger()


@tool(
    name="tool_name",                 # Unique name in snake_case
    description="""                   # Description for the LLM (when to use it)
    Detailed description.
    Use when: (1) scenario 1, (2) scenario 2
    """,
    parameters={                      # JSON Schema for parameters
        "type": "object",
        "properties": {
            "param1": {
                "type": "string",
                "description": "Description of parameter 1"
            },
            "param2": {
                "type": "integer",
                "description": "Description of parameter 2"
            }
        },
        "required": ["param1"],       # Required parameters
    },
    risk_level="medium",              # low | medium | high
    needs_sandbox=False,              # True if it executes dangerous code
)
async def tool_name(
    param1: str,                      # Parameters with type hints
    param2: int = 0,                  # Default values
    _brain=None,                      # Dependency injection (optional)
    **kwargs
) -> str:
    """Main tool function."""

    # Your code here
    result = f"Processing {param1}..."

    return result


# Export functions
__all__ = ["tool_name"]
```

### How to Create Tools

#### Option 1: From Chat (Saves file, requires restart)
```
You: Create a tool that calculates the factorial of a number

[The bot:]
1. Generates Python code
2. Saves to: src/openacm/tools/factorial_calculator.py
3. Responds with success
4. Indicates restart is needed
```

#### Option 2: Manually (Development)
1. Create file: `src/openacm/tools/my_tool.py`
2. Use the template above
3. Add import in `app.py`:
   ```python
   from openacm.tools import my_tool
   self.tool_registry.register_module(my_tool)
   ```
4. Restart OpenACM

#### Complete Tool Example

```python
# src/openacm/tools/hello_world.py

"""
Hello World Tool - Basic example

Demonstrates how to create a simple tool.
"""

import structlog
from openacm.tools.base import tool

log = structlog.get_logger()


@tool(
    name="hello_world",
    description="""
    Greets the user by name.
    Use when: (1) the user asks for a greeting, (2) you want to demonstrate functionality
    """,
    parameters={
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Name of the person to greet"
            },
            "language": {
                "type": "string",
                "description": "Greeting language (es/en/fr)",
                "enum": ["es", "en", "fr"]
            }
        },
        "required": ["name"],
    },
    risk_level="low",
    needs_sandbox=False,
)
async def hello_world(
    name: str,
    language: str = "en",
    **kwargs
) -> str:
    """Greet the user."""

    greetings = {
        "es": f"Hola, {name}!",
        "en": f"Hello, {name}!",
        "fr": f"Bonjour, {name}!"
    }

    return greetings.get(language, greetings["en"])


__all__ = ["hello_world"]
```

---

## Key Differences: Skills vs Tools

| Aspect | Skills | Tools |
|--------|--------|-------|
| **What they are** | Behavioral guides | Executable functions |
| **Format** | Markdown (.md) | Python (.py) |
| **Location** | `./skills/{cat}/` | `src/openacm/tools/` |
| **Persistence** | File + SQLite | File only |
| **Activation** | Immediate | Restart required |
| **Created by** | LLM (skill_creator) | LLM (tool_creator) or manual |
| **Security** | Very safe (text) | Sandbox if needed |
| **Examples** | Django expert | Run command, web search |

---

## Quick Templates

### SKILL.md Template

```markdown
---
name: "my-expert"
description: "Expert in X technology"
category: "development"
---

# My Expert

## Overview
You are an expert in [technology]. You help with [use cases].

## Guidelines
1. **Principle 1**: Explanation
2. **Principle 2**: Explanation
3. **Principle 3**: Explanation

## Examples
- **Scenario A**: How to approach it
- **Scenario B**: How to approach it

## Common Pitfalls
- Don't do this
- Avoid this
```

### TOOL.py Template

```python
"""my_tool.py - Description"""

import structlog
from openacm.tools.base import tool

log = structlog.get_logger()


@tool(
    name="my_tool",
    description="""Description for the LLM""",
    parameters={
        "type": "object",
        "properties": {
            "input": {"type": "string", "description": "Input"}
        },
        "required": ["input"],
    },
    risk_level="low",
    needs_sandbox=False,
)
async def my_tool(input: str, **kwargs) -> str:
    """Main function."""
    return f"Result: {input}"


__all__ = ["my_tool"]
```

---

## Best Practices

### For Skills:
1. **Descriptive names**: `django-expert` is better than `skill1`
2. **Clear categories**: Use the 5 defined categories
3. **Actionable content**: The LLM should be able to apply it immediately
4. **Concrete examples**: Not vague descriptions
5. **Versioning**: Generated skills include a date

### For Tools:
1. **snake_case names**: `file_analyzer`, not `FileAnalyzer`
2. **Typed parameters**: Always use type hints
3. **Error handling**: Try/except with clear messages
4. **Logging**: Use structlog for debugging
5. **Documentation**: Clear description of when to use it
6. **Risk level**: Be honest (high if it uses subprocess)

---

## Common Workflows

### Workflow 1: Create Skill from Chat
```
1. User: "Create a skill to be a GraphQL expert"
2. LLM generates complete content
3. Saves to: skills/generated/graphql-expert.md
4. Saves metadata in DB
5. Activates immediately
```

### Workflow 2: Create Tool from Chat
```
1. User: "Create a tool that validates emails"
2. LLM generates Python code
3. Saves to: src/openacm/tools/email_validator.py
4. Shows message: "Restart to activate"
5. User restarts OpenACM
6. Tool available
```

### Workflow 3: Manual Development
```
1. Developer creates local file
2. Saves to the correct location
3. Restarts OpenACM
4. System loads it automatically
```

---

## Location Summary

```
OpenACM/
├── skills/                          # SKILLS (Markdown)
│   ├── security/                    #    Security
│   ├── development/                 #    Development
│   ├── ai/                          #    AI/ML
│   ├── custom/                      #    Custom
│   └── generated/                   #    Auto-generated
│
├── src/openacm/tools/               # TOOLS (Python)
│   ├── base.py                      #    @tool decorator
│   ├── registry.py                  #    ToolRegistry
│   ├── skill_creator.py             #    Creates skills
│   ├── tool_creator.py              #    Creates tools
│   └── [other tools].py             #    System tools
│
├── src/openacm/core/                # Core
│   ├── skill_manager.py             #    Skill manager
│   ├── brain.py                     #    Uses active skills
│   └── llm_router.py                #    LLM Router
│
├── data/                            # Data
│   ├── openacm.db                   #    SQLite (skill metadata)
│   └── vectordb/                    #    ChromaDB
│
└── .opencode/                       # Skills for OpenCode
    └── skills/                      #    (Already installed)
        ├── skill-security-auditor/
        └── [other skills]/
```
