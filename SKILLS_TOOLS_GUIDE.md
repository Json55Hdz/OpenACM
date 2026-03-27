# 📁 Estructura de Archivos - OpenACM Skills & Tools

## Resumen General

| Tipo | Ubicación | Formato | Activación |
|------|-----------|---------|------------|
| **Skills** | `./skills/{categoria}/` | `.md` con frontmatter | Automática al crear (DB + archivo) |
| **Tools** | `src/openacm/tools/` | `.py` con decorador `@tool` | Reinicio requerido |

---

## 🧠 SKILLS - `./skills/`

Las skills son **guías de comportamiento** para el modelo LLM. Se guardan como archivos Markdown con metadatos en el frontmatter.

### Estructura de Directorios

```
skills/
├── security/          # 🔒 Skills de seguridad
│   └── security-auditor.md
├── development/       # 💻 Skills de desarrollo
│   ├── code-reviewer.md
│   ├── fastapi-expert.md
│   └── database-architect.md
├── ai/               # 🧠 Skills de IA/ML
│   └── rag-optimizer.md
├── custom/           # ⚙️ Skills personalizadas del usuario
│   └── mi-skill-personal.md
└── generated/        # ✨ Skills generadas por IA
    └── django-expert-20250327.md
```

### Formato de Archivo SKILL.md

```markdown
---
name: "nombre-de-la-skill"
description: "Breve descripción de qué hace"
category: "development"
created: "2025-03-27T10:30:00"
---

# Nombre de la Skill

## Overview
Descripción detallada y cuándo usar esta skill.

## Guidelines
Instrucciones específicas, mejores prácticas, patrones a seguir:
- Punto 1
- Punto 2
- Punto 3

## Examples
Ejemplos concretos:
- Ejemplo 1: Escenario común
- Ejemplo 2: Caso edge

## Common Pitfalls
Qué evitar:
- Anti-patrón 1
- Error común 2
```

### Categorías Recomendadas

- `security` - Auditoría, vulnerabilidades, mejores prácticas de seguridad
- `development` - Programación, diseño de APIs, bases de datos
- `ai` - Machine learning, RAG, prompts engineering
- `custom` - Skills personalizadas del usuario
- `generated` - Skills creadas automáticamente por el sistema

### Cómo Crear Skills

#### Opción 1: Desde el Chat (Automático)
```
Tú: Crea una skill para ser experto en Django

[El bot automáticamente:]
1. Genera contenido con IA
2. Guarda en: skills/generated/django-expert.md
3. Guarda metadatos en SQLite
4. Activa inmediatamente
```

#### Opción 2: Manualmente (Archivo)
1. Crear archivo: `skills/custom/mi-skill.md`
2. Llenar con formato SKILL.md
3. Reiniciar OpenACM (sincroniza archivos → BD)

#### Opción 3: Dashboard Web
- Ir a sección "Skills"
- Click "+ Nueva Skill"
- Completar formulario
- Se guarda automáticamente en archivo + BD

---

## 🔧 TOOLS - `src/openacm/tools/`

Los tools son **funciones Python ejecutables** que OpenACM puede llamar. Se guardan como archivos `.py` con el decorador `@tool`.

### Estructura de Directorios

```
src/openacm/tools/
├── __init__.py
├── base.py                 # Base class y decorador @tool
├── registry.py            # ToolRegistry
│
├── system_cmd.py          # Comandos del sistema
├── file_ops.py           # Operaciones de archivos
├── web_search.py         # Búsqueda web
├── browser_agent.py      # Automatización de navegador
├── python_kernel.py      # Ejecución Python
├── google_services.py    # Integración Google
├── screenshot.py         # Capturas de pantalla
├── rag_tools.py          # Herramientas RAG
├── system_info.py        # Información del sistema
│
├── skill_creator.py      # ✅ Creador de skills
└── tool_creator.py       # ✅ Creador de tools
```

### Formato de Archivo TOOL.py

```python
"""
nombre-del-tool.py — Descripción corta

Descripción más larga del tool.
"""

import structlog
from openacm.tools.base import tool

log = structlog.get_logger()


@tool(
    name="nombre_del_tool",           # Nombre único en snake_case
    description="""                  # Descripción para el LLM (cuándo usarlo)
    Descripción detallada.
    Use when: (1) escenario 1, (2) escenario 2
    """,
    parameters={                      # JSON Schema de parámetros
        "type": "object",
        "properties": {
            "param1": {
                "type": "string",
                "description": "Descripción del parámetro 1"
            },
            "param2": {
                "type": "integer",
                "description": "Descripción del parámetro 2"
            }
        },
        "required": ["param1"],       # Parámetros obligatorios
    },
    risk_level="medium",              # low | medium | high
    needs_sandbox=False,              # True si ejecuta código peligroso
)
async def nombre_del_tool(
    param1: str,                      # Parámetros con type hints
    param2: int = 0,                  # Valores por defecto
    _brain=None,                      # Inyección de dependencias (opcional)
    **kwargs
) -> str:
    """Función principal del tool."""
    
    # Tu código aquí
    result = f"Procesando {param1}..."
    
    return result


# Exportar funciones
__all__ = ["nombre_del_tool"]
```

### Cómo Crear Tools

#### Opción 1: Desde el Chat (Guarda archivo, requiere reinicio)
```
Tú: Crea un tool que calcule el factorial de un número

[El bot:]
1. Genera código Python
2. Guarda en: src/openacm/tools/factorial_calculator.py
3. Responde con éxito
4. ⚠️ Indica que necesita reinicio
```

#### Opción 2: Manualmente (Desarrollo)
1. Crear archivo: `src/openacm/tools/mi_tool.py`
2. Usar template de arriba
3. Agregar import en `app.py`:
   ```python
   from openacm.tools import mi_tool
   self.tool_registry.register_module(mi_tool)
   ```
4. Reiniciar OpenACM

#### Ejemplo Completo de Tool

```python
# src/openacm/tools/hello_world.py

"""
Hello World Tool — Ejemplo básico

Demuestra cómo crear un tool simple.
"""

import structlog
from openacm.tools.base import tool

log = structlog.get_logger()


@tool(
    name="hello_world",
    description="""
    Saluda al usuario por su nombre.
    Use when: (1) el usuario pide un saludo, (2) quieres demostrar funcionalidad
    """,
    parameters={
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Nombre de la persona a saludar"
            },
            "language": {
                "type": "string",
                "description": "Idioma del saludo (es/en/fr)",
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
    language: str = "es",
    **kwargs
) -> str:
    """Saluda al usuario."""
    
    greetings = {
        "es": f"¡Hola, {name}! 👋",
        "en": f"Hello, {name}! 👋",
        "fr": f"Bonjour, {name}! 👋"
    }
    
    return greetings.get(language, greetings["es"])


__all__ = ["hello_world"]
```

---

## 🔄 Diferencias Clave: Skills vs Tools

| Aspecto | Skills | Tools |
|---------|--------|-------|
| **Qué son** | Guías de comportamiento | Funciones ejecutables |
| **Formato** | Markdown (.md) | Python (.py) |
| **Ubicación** | `./skills/{cat}/` | `src/openacm/tools/` |
| **Persistencia** | Archivo + SQLite | Solo archivo |
| **Activación** | Inmediata | Reinicio requerido |
| **Creados por** | LLM (skill_creator) | LLM (tool_creator) o manual |
| **Seguridad** | Muy seguro (texto) | Sandbox si needed |
| **Ejemplos** | Experto en Django | Ejecutar comando, buscar web |

---

## 📝 Plantillas Rápidas

### Template SKILL.md

```markdown
---
name: "mi-experto"
description: "Experto en X tecnología"
category: "development"
---

# Mi Experto

## Overview
Eres un experto en [tecnología]. Ayudas con [casos de uso].

## Guidelines
1. **Principio 1**: Explicación
2. **Principio 2**: Explicación
3. **Principio 3**: Explicación

## Examples
- **Escenario A**: Cómo abordarlo
- **Escenario B**: Cómo abordarlo

## Common Pitfalls
- ❌ No hagas esto
- ❌ Evita esto otro
```

### Template TOOL.py

```python
"""mi_tool.py — Descripción"""

import structlog
from openacm.tools.base import tool

log = structlog.get_logger()


@tool(
    name="mi_tool",
    description="""Descripción para el LLM""",
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
async def mi_tool(input: str, **kwargs) -> str:
    """Función principal."""
    return f"Resultado: {input}"


__all__ = ["mi_tool"]
```

---

## 🎯 Mejores Prácticas

### Para Skills:
1. **Nombres descriptivos**: `django-expert` mejor que `skill1`
2. **Categorías claras**: Usa las 5 categorías definidas
3. **Contenido accionable**: El LLM debe poder aplicarlo inmediatamente
4. **Ejemplos concretos**: No descripciones vagas
5. **Versionado**: Las skills generadas incluyen fecha

### Para Tools:
1. **Nombres en snake_case**: `file_analyzer`, no `FileAnalyzer`
2. **Parámetros tipados**: Usa type hints siempre
3. **Manejo de errores**: Try/except con mensajes claros
4. **Logs**: Usa structlog para debugging
5. **Documentación**: Descripción clara de cuándo usarlo
6. **Nivel de riesgo**: Sé honesto (high si usa subprocess)

---

## 🚀 Workflows Comunes

### Workflow 1: Crear Skill desde Chat
```
1. Usuario: "Crea skill para ser experto en GraphQL"
2. LLM genera contenido completo
3. Guarda en: skills/generated/graphql-expert.md
4. Guarda metadatos en DB
5. ✅ Activa inmediatamente
```

### Workflow 2: Crear Tool desde Chat
```
1. Usuario: "Crea tool que valide emails"
2. LLM genera código Python
3. Guarda en: src/openacm/tools/email_validator.py
4. ⚠️ Muestra mensaje: "Reinicia para activar"
5. Usuario reinicia OpenACM
6. ✅ Tool disponible
```

### Workflow 3: Desarrollo Manual
```
1. Desarrollador crea archivo local
2. Guarda en ubicación correcta
3. Reinicia OpenACM
4. Sistema carga automáticamente
```

---

## 📍 Resumen de Ubicaciones

```
OpenACM/
├── skills/                          # 🧠 SKILLS (Markdown)
│   ├── security/                    #    🔒 Seguridad
│   ├── development/                 #    💻 Desarrollo
│   ├── ai/                          #    🧠 IA/ML
│   ├── custom/                      #    ⚙️ Personalizadas
│   └── generated/                   #    ✨ Auto-generadas
│
├── src/openacm/tools/               # 🔧 TOOLS (Python)
│   ├── base.py                      #    Decorador @tool
│   ├── registry.py                  #    ToolRegistry
│   ├── skill_creator.py             #    ✅ Crea skills
│   ├── tool_creator.py              #    ✅ Crea tools
│   └── [otros tools].py             #    Tools del sistema
│
├── src/openacm/core/                # 🧠 Core
│   ├── skill_manager.py             #    Gestor de skills
│   ├── brain.py                     #    Usa skills activas
│   └── llm_router.py                #    Router LLM
│
├── data/                            # 💾 Datos
│   ├── openacm.db                   #    SQLite (metadatos skills)
│   └── vectordb/                    #    ChromaDB
│
└── .opencode/                       # 🎯 Skills para OpenCode
    └── skills/                      #    (Ya instaladas)
        ├── skill-security-auditor/
        └── [otras skills]/
```

---

**¿Preguntas sobre dónde guardar algo específico?** 🤔
