---
name: "openacm-master"
description: >
  Master skill orchestrator for OpenACM development.
  This skill coordinates all other skills in .opencode/skills/ directory.
  Use this to understand which specialized skill to invoke for each task.
---

# OpenACM - Master Skill Orchestrator

OpenACM es un agente autónomo Tier-1 con:
- Memoria vectorial (ChromaDB/RAG)
- Control de sistema (ejecución de comandos, archivos)
- Navegador autónomo (Playwright)
- Kernel Python interactivo (Jupyter)
- Dashboard web (FastAPI + WebSockets)
- Canales multiplataforma (Discord, Telegram, WhatsApp)
- Búsqueda web y servicios Google
- Sandbox de seguridad
- **Sistema de Skills dinámico** (archivos en `./skills/`)
- **Creador de Tools** (archivos en `src/openacm/tools/`)

## Skills Disponibles

### 🔒 skill-security-auditor
**Cuándo usar:**
- Antes de instalar cualquier skill o dependencia nueva
- Para auditar código Python en busca de vulnerabilidades
- Para revisar seguridad de scripts y herramientas
- Para detectar prompt injection en archivos markdown
- Para validar dependencias (typosquatting, versiones)

**Cómo invocar:**
```bash
python skills/skill_security_auditor.py /ruta/a/codigo/
```

### 🚀 ci-cd-pipeline-builder
**Cuándo usar:**
- Configurar GitHub Actions para testing automático
- Crear pipelines de deploy
- Configurar hooks de pre-commit
- Automatizar linting y formateo (ruff, black)
- Configurar releases automáticos

**Archivos clave:**
- `.github/workflows/*.yml`
- `pyproject.toml` (configuración de herramientas)

### 🧠 rag-architect
**Cuándo usar:**
- Diseñar estrategias de chunking para ChromaDB
- Optimizar búsqueda vectorial
- Seleccionar modelos de embeddings
- Implementar re-ranking
- Configurar metadata filtering
- Evaluar calidad de retrieval

**Contexto actual:**
- Usa ChromaDB para almacenamiento vectorial
- Sentence-transformers para embeddings
- Almacena en `data/vectordb/`

### 🗄️ database-designer
**Cuándo usar:**
- Diseñar esquemas SQLite para nueva funcionalidad
- Crear migraciones de base de datos
- Optimizar índices
- Diseñar políticas RLS (Row Level Security)
- Normalizar/denormalizar datos

**Contexto actual:**
- Usa aiosqlite (async SQLite)
- Base de datos en `data/openacm.db`
- Schema gestionado en `storage/database.py`

### 🎭 playwright-pro
**Cuándo usar:**
- Crear tests E2E para el dashboard web
- Automatizar navegación del browser agent
- Testing de integración con páginas web
- Screenshots automáticos
- Performance testing

**Contexto actual:**
- Playwright ya está integrado en `tools/browser_agent.py`
- Usa modo headless
- Screenshots se guardan en `data/media/`

### 🔄 self-improving-agent
**Cuándo usar:**
- Optimizar el sistema de memoria a largo plazo
- Extraer patrones de código recurrentes
- Curar automáticamente la memoria vectorial
- Promover buenas prácticas detectadas
- Health check de la memoria

**Contexto actual:**
- Memoria conversacional: SQLite
- Memoria vectorial: ChromaDB
- Eventos: EventBus interno

### 🌐 api-design-reviewer
**Cuándo usar:**
- Revisar endpoints de FastAPI
- Validar diseño REST
- Detectar breaking changes
- Revisar autenticación/autorización
- Documentación OpenAPI/Swagger

**Contexto actual:**
- FastAPI en `web/server.py`
- WebSockets para chat en tiempo real
- Autenticación por token en dashboard

### 🔍 browser-automation
**Cuándo usar:**
- Extender el browser agent actual
- Crear nuevas herramientas de scraping
- Automatizar interacciones web complejas
- Manejar autenticación en sitios externos
- Extraer datos estructurados

**Contexto actual:**
- Browser agent usa Playwright
- Soporte para login automático
- Screenshots y descargas
- Exporta contenido dinámico

## Flujos de Trabajo Típicos

### Agregar nueva funcionalidad:
1. **rag-architect** - Si involucra búsqueda/memoria
2. **database-designer** - Si requiere cambios en DB
3. **api-design-reviewer** - Si expone nuevos endpoints
4. **skill-security-auditor** - Auditar antes de mergear
5. **ci-cd-pipeline-builder** - Automatizar tests

### Optimizar rendimiento:
1. **self-improving-agent** - Analizar patrones de uso
2. **rag-architect** - Optimizar retrieval si aplica
3. **database-designer** - Añadir índices necesarios
4. **playwright-pro** - Tests de carga si aplica

### Seguridad:
1. **skill-security-auditor** - Auditar código regularmente
2. **api-design-reviewer** - Revisar autenticación
3. **browser-automation** - Asegurar sandbox del browser

## Estructura del Proyecto

```
OpenACM/
├── src/openacm/           # Código fuente principal
│   ├── core/             # Brain, LLM router, memory, RAG
│   ├── tools/            # Tools registry + herramientas
│   ├── web/              # FastAPI + dashboard
│   ├── channels/         # Discord, Telegram, WhatsApp
│   ├── security/         # Sandbox, crypto, auth
│   └── storage/          # Database
├── skills/               # Skills auditadas (legacy)
├── .opencode/skills/     # Skills para opencode (este directorio)
├── data/                 # DB y vectordb
└── config/               # Configuración
```

## Tech Stack

- **Python 3.12+** - Lenguaje principal
- **FastAPI** - Web framework
- **LiteLLM** - Router de LLMs
- **ChromaDB** - Vector database
- **Playwright** - Browser automation
- **aiosqlite** - Async SQLite
- **structlog** - Logging estructurado
- **rich** - CLI bonito
- **pydantic** - Validación de datos

---

## 📁 Estructura de Archivos: Skills vs Tools

### 🧠 SKILLS - `./skills/`

Las skills son **guías de comportamiento** para el LLM. Se guardan como archivos Markdown.

**Ubicación:**
```
skills/
├── security/          # 🔒 Skills de seguridad
├── development/       # 💻 Skills de desarrollo  
├── ai/               # 🧠 Skills de IA/ML
├── custom/           # ⚙️ Skills personalizadas
└── generated/        # ✨ Skills generadas por IA
```

**Formato:** Archivo `.md` con frontmatter YAML:
```markdown
---
name: "mi-skill"
description: "Descripción"
category: "development"
---

# Mi Skill
## Overview
...
```

**Activación:** 
- Se guarda en archivo **Y** en base de datos
- Activa **inmediatamente** al crear
- El Brain las carga dinámicamente desde la DB

### 🔧 TOOLS - `src/openacm/tools/`

Los tools son **funciones Python ejecutables**.

**Ubicación:**
```
src/openacm/tools/
├── base.py              # Decorador @tool
├── skill_creator.py     # ✅ Crea skills (archivo + DB)
├── tool_creator.py      # ✅ Crea tools (archivo .py)
└── [otros].py          # Tools del sistema
```

**Formato:** Archivo `.py` con decorador `@tool`:
```python
@tool(
    name="mi_tool",
    description="...",
    parameters={...}
)
async def mi_tool(...) -> str:
    ...
```

**Activación:**
- Se guarda en archivo `.py`
- Requiere **reinicio** para cargar
- Se registra en ToolRegistry al inicio

### 🔄 Diferencias Clave

| Aspecto | Skills | Tools |
|---------|--------|-------|
| **Qué son** | Guías de comportamiento | Funciones ejecutables |
| **Formato** | Markdown (.md) | Python (.py) |
| **Ubicación** | `./skills/{cat}/` | `src/openacm/tools/` |
| **Activación** | Inmediata | Reinicio requerido |
| **Persistencia** | Archivo + SQLite | Solo archivo |

### 📝 Guía Rápida

**Para crear una Skill:**
```bash
# Automáticamente desde chat
"Crea una skill para ser experto en Django"
# Guarda en: skills/generated/django-expert.md
```

**Para crear un Tool:**
```bash
# Automáticamente desde chat  
"Crea un tool que valide emails"
# Guarda en: src/openacm/tools/email_validator.py
# ⚠️ Reinicio requerido para activar
```

**Documentación completa:** Ver `SKILLS_TOOLS_GUIDE.md`
