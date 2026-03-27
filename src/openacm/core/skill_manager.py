"""
Skill Manager - Gestión dinámica de skills para OpenACM.

Las skills se guardan como archivos .md en ./skills/ organizados por categoría.
Los metadatos se sincronizan con la base de datos.
"""

import structlog
import re
from pathlib import Path
from typing import Any
from datetime import datetime

from openacm.storage.database import Database

log = structlog.get_logger()

# Directorio base para skills
SKILLS_BASE_DIR = Path("skills")


DEFAULT_SKILLS = [
    {
        "name": "security-auditor",
        "description": "Audita código en busca de vulnerabilidades de seguridad",
        "category": "security",
        "content": """# Security Auditor

Eres un experto en seguridad. Cuando el usuario te pida auditar código:

1. Busca patrones peligrosos: eval, exec, os.system, subprocess con shell=True
2. Identifica fugas de datos: requests.post sin validar, lectura de credenciales
3. Revisa dependencias: versiones sin pin, typosquatting
4. Proporciona recomendaciones específicas con ejemplos de código seguro

Prioriza los hallazgos por severidad: CRÍTICO > ALTO > MEDIO > BAJO.
""",
    },
    {
        "name": "code-reviewer",
        "description": "Revisa código siguiendo mejores prácticas de Python",
        "category": "development",
        "content": """# Code Reviewer

Eres un senior developer experto en Python. Al revisar código:

1. **Calidad**: PEP 8, type hints, docstrings
2. **Rendimiento**: Optimiza algoritmos O(n²) → O(n log n)
3. **Mantenibilidad**: Principios SOLID, DRY, KISS
4. **Async**: Verifica uso correcto de async/await
5. **Errores**: Manejo de excepciones específicas, no genéricas

Sé constructivo pero exigente. Explica el "por qué" de cada sugerencia.
""",
    },
    {
        "name": "api-designer",
        "description": "Diseña y revisa APIs REST siguiendo mejores prácticas",
        "category": "development",
        "content": """# API Designer

Eres un experto en diseño de APIs RESTful. Al diseñar o revisar APIs:

1. **Recursos**: Usa nombres de recursos (plural), no verbos
   ✅ GET /users/{id}  ❌ GET /getUser
   
2. **Versionado**: Incluye versión en URL (/api/v1/users)

3. **Métodos HTTP**: Usa correctamente GET, POST, PUT, PATCH, DELETE

4. **Códigos de estado**: 200 OK, 201 Created, 400 Bad Request, 404 Not Found, 500 Error

5. **Autenticación**: JWT tokens, OAuth2 para APIs públicas

6. **Documentación**: OpenAPI/Swagger con ejemplos

7. **Paginación**: cursor-based para grandes datasets

8. **Rate limiting**: Protege endpoints sensibles

Proporciona ejemplos de requests/responses JSON.
""",
    },
    {
        "name": "rag-optimizer",
        "description": "Optimiza sistemas de RAG y búsqueda vectorial",
        "category": "ai",
        "content": """# RAG Optimizer

Eres un experto en Retrieval-Augmented Generation (RAG). Para optimizar RAG:

## Chunking Strategies

1. **Fixed-size**: 512-1024 tokens, 10-20% overlap
2. **Semantic**: Split en frases/párrafos completos
3. **Recursive**: Divide jerárquicamente (sección → párrafo → oración)

## Embeddings

- Modelos: sentence-transformers/all-MiniLM-L6-v2 (rápido), text-embedding-3-large (calidad)
- Dimensiones: 384 (rápido) vs 1536 (preciso)
- Normalización: L2 para cosine similarity

## Retrieval

- **Top-k**: 5-10 documentos inicialmente
- **Re-ranking**: Cross-encoder para refine
- **Metadata filtering**: Filtra por tags/fechas primero
- **Hybrid**: BM25 + Vector para mejor recall

## Evaluation

Métricas: MRR, NDCG, Precision@K
Test con: ¿Recupera el chunk correcto para cada query?

Proporciona configuraciones específicas para ChromaDB.
""",
    },
    {
        "name": "fastapi-expert",
        "description": "Experto en FastAPI y desarrollo web async",
        "category": "development",
        "content": """# FastAPI Expert

Eres un experto en FastAPI y Python async. Al trabajar con FastAPI:

## Estructura

```
app/
├── main.py          # Entry point
├── routers/         # API routes
├── models/          # Pydantic models
├── services/        # Business logic
├── dependencies/    # Inyección de dependencias
└── core/           # Configuración, logging
```

## Mejores Prácticas

1. **Validación**: Usa Pydantic para request/response models
2. **Dependencias**: Inyecta DB, auth, config
3. **Async**: Todas las operaciones I/O deben ser async
4. **Errores**: HTTPException con status codes correctos
5. **Docs**: Auto-generadas, añade ejemplos
6. **Seguridad**: OAuth2PasswordBearer, JWT tokens
7. **Testing**: TestClient, pytest-asyncio
8. **Background tasks**: Para operaciones largas
9. **WebSockets**: Para tiempo real
10. **Middleware**: Logging, CORS, rate limiting

## Patrones

- **Repository**: Abstrae acceso a datos
- **Service**: Lógica de negocio pura
- **Dependency**: Reutilizable, testeable

Proporciona código de ejemplo funcional.
""",
    },
    {
        "name": "database-architect",
        "description": "Diseña esquemas de bases de datos optimizados",
        "category": "development",
        "content": """# Database Architect

Eres un experto en diseño de bases de datos. Al diseñar esquemas:

## Principios

1. **Normalización**: 3NF para OLTP, denormalización cuidada para reporting
2. **PK**: UUID (seguridad) vs AUTO_INCREMENT (performance)
3. **Índices**: B-tree para igualdad/rango, GIN para arrays/text search
4. **Constraints**: FK para integridad, CHECK para validación
5. **Tipos de datos**: TEXT ilimitado vs VARCHAR(n), INTEGER vs BIGINT

## SQLite Específico

- WAL mode para mejor concurrencia
- PRAGMA foreign_keys = ON
- Índices parciales para datos filtrados
- JSON1 extension para datos flexibles

## Async (aiosqlite)

- Todas las queries deben ser async
- Usa connection pooling si hay alta concurrencia
- Transactions para operaciones múltiples

## Migraciones

- Versionado incremental
- Rollback scripts
- Tests de integridad post-migración

Proporciona SQL DDL con comentarios explicativos.
""",
    },
]


class SkillManager:
    """Gestiona la carga y activación de skills dinámicas."""

    def __init__(self, database: Database):
        self.database = database
        self._skills_cache: dict[str, dict[str, Any]] = {}
        self._active_skills: list[dict[str, Any]] = []

    async def initialize(self):
        """Initialize skills - sync files to DB and load defaults if needed."""
        # Ensure skills directory exists
        SKILLS_BASE_DIR.mkdir(exist_ok=True)
        for cat in ["security", "development", "ai", "custom", "generated"]:
            (SKILLS_BASE_DIR / cat).mkdir(exist_ok=True)

        # Sync any new files from disk to database
        await self._sync_files_to_database()

        # Load built-in defaults if database is empty
        await self._load_builtin_skills()
        await self._refresh_cache()

        # Count files on disk
        skill_files = list(SKILLS_BASE_DIR.rglob("*.md"))
        log.info(
            "SkillManager initialized",
            db_count=len(self._active_skills),
            file_count=len(skill_files),
        )

    async def _load_builtin_skills(self):
        """Load default skills if database is empty - saves to files too."""
        existing = await self.database.get_all_skills()
        if existing:
            return

        log.info("Loading default skills...")
        for skill in DEFAULT_SKILLS:
            # Save to file
            file_path = self._save_skill_to_file(
                name=skill["name"],
                description=skill["description"],
                content=skill["content"],
                category=skill["category"],
            )
            log.info(f"Built-in skill saved: {file_path}")

            # Save to database
            await self.database.create_skill(
                name=skill["name"],
                description=skill["description"],
                content=skill["content"],
                category=skill["category"],
                is_builtin=True,
            )
        log.info(f"Loaded {len(DEFAULT_SKILLS)} default skills")

    async def _refresh_cache(self):
        """Refresh skills cache from database."""
        self._active_skills = await self.database.get_all_skills(active_only=True)
        self._skills_cache = {s["name"]: s for s in self._active_skills}

    def _get_skill_file_path(self, name: str, category: str) -> Path:
        """Get the file path for a skill."""
        # Sanitize filename
        safe_name = re.sub(r"[^a-zA-Z0-9_-]", "_", name.lower())
        category_dir = SKILLS_BASE_DIR / category
        category_dir.mkdir(parents=True, exist_ok=True)
        return category_dir / f"{safe_name}.md"

    def _save_skill_to_file(self, name: str, description: str, content: str, category: str) -> Path:
        """Save skill content to a markdown file."""
        file_path = self._get_skill_file_path(name, category)

        # Build markdown content with frontmatter
        md_content = f"""---
name: "{name}"
description: "{description}"
category: "{category}"
created: "{datetime.now().isoformat()}"
---

{content}
"""
        file_path.write_text(md_content, encoding="utf-8")
        return file_path

    def _load_skill_from_file(self, file_path: Path) -> dict[str, Any] | None:
        """Load skill from markdown file."""
        if not file_path.exists():
            return None

        content = file_path.read_text(encoding="utf-8")

        # Parse frontmatter
        skill = {
            "name": file_path.stem,
            "description": "",
            "category": file_path.parent.name,
            "content": content,
            "file_path": str(file_path),
        }

        # Extract frontmatter if present
        if content.startswith("---"):
            parts = content.split("---", 2)
            if len(parts) >= 3:
                frontmatter = parts[1].strip()
                skill["content"] = parts[2].strip()

                # Parse simple key: value pairs
                for line in frontmatter.split("\n"):
                    if ":" in line:
                        key, value = line.split(":", 1)
                        key = key.strip()
                        value = value.strip().strip('"')
                        if key in ["name", "description", "category"]:
                            skill[key] = value

        return skill

    async def _sync_files_to_database(self):
        """Sync skills from files to database."""
        if not SKILLS_BASE_DIR.exists():
            return

        # Scan all .md files in skills directory
        for category_dir in SKILLS_BASE_DIR.iterdir():
            if category_dir.is_dir():
                for skill_file in category_dir.glob("*.md"):
                    skill_data = self._load_skill_from_file(skill_file)
                    if skill_data:
                        # Check if exists in DB
                        existing = await self.database.get_skill_by_name(skill_data["name"])
                        if not existing:
                            # Add to database
                            await self.database.create_skill(
                                name=skill_data["name"],
                                description=skill_data["description"],
                                content=skill_data["content"],
                                category=skill_data["category"],
                                is_builtin=False,
                            )
                            log.info("Skill synced from file", name=skill_data["name"])

    async def get_active_skills_prompt(self) -> str:
        """Get combined prompt from all active skills."""
        if not self._active_skills:
            return ""

        prompts = []
        for skill in self._active_skills:
            prompts.append(f"\n## Skill: {skill['name']}\n{skill['content']}")

        return "\n".join(prompts)

    async def get_all_skills(self) -> list[dict[str, Any]]:
        """Get all skills with their status."""
        return await self.database.get_all_skills()

    async def create_skill(
        self,
        name: str,
        description: str,
        content: str,
        category: str = "general",
    ) -> dict[str, Any]:
        """Create a new custom skill - saves to file and database."""
        # Save to file first
        file_path = self._save_skill_to_file(name, description, content, category)
        log.info("Skill saved to file", file=str(file_path))

        # Save to database
        skill_id = await self.database.create_skill(
            name=name,
            description=description,
            content=content,
            category=category,
            is_builtin=False,
        )
        await self._refresh_cache()

        skill = await self.database.get_skill(skill_id)
        if skill:
            skill["file_path"] = str(file_path)
        return skill

    async def update_skill(
        self,
        skill_id: int,
        **kwargs,
    ) -> bool:
        """Update a skill."""
        result = await self.database.update_skill(skill_id, **kwargs)
        if result:
            await self._refresh_cache()
        return result

    async def toggle_skill(self, skill_id: int) -> bool:
        """Toggle skill active status."""
        result = await self.database.toggle_skill(skill_id)
        if result:
            await self._refresh_cache()
        return result

    async def delete_skill(self, skill_id: int) -> bool:
        """Delete a custom skill."""
        result = await self.database.delete_skill(skill_id)
        if result:
            await self._refresh_cache()
        return result

    async def generate_skill(
        self,
        name: str,
        description: str,
        use_cases: str,
        llm_router=None,
    ) -> dict[str, Any]:
        """Generate a new skill using LLM."""
        if not llm_router:
            raise ValueError("LLM router required for skill generation")

        prompt = f"""Create a comprehensive skill guide for an AI assistant.

Skill Name: {name}
Description: {description}
Use Cases: {use_cases}

Write the skill content in Markdown format following this structure:

# {name}

## Overview
Brief description of what this skill does.

## Guidelines
Detailed instructions, best practices, and specific patterns to follow.

## Examples
Concrete examples of how to apply this skill.

## Common Pitfalls
What to avoid and why.

Make it practical and actionable. The AI should be able to immediately apply this knowledge.
"""

        response = await llm_router.generate(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
        )

        content = response.get("content", "")

        return await self.create_skill(
            name=name,
            description=description,
            content=content,
            category="generated",
        )
