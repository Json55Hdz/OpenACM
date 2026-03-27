"""
Skill Manager - Dynamic skill management for OpenACM.

Skills are stored as .md files in ./skills/ organized by category.
Metadata is synced with the database.
"""

import structlog
import re
from pathlib import Path
from typing import Any
from datetime import datetime

from openacm.storage.database import Database
from openacm.core.skill_manager_default_skills import DEFAULT_SKILLS

log = structlog.get_logger()

# Base directory for skills
SKILLS_BASE_DIR = Path("skills")


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

    async def get_active_skills_prompt(self, user_message: str = "") -> str:
        """Get combined prompt from relevant active skills based on user message.

        Uses keyword matching to determine which skills are relevant.
        If no specific skills match, returns empty to avoid interfering.
        """
        if not self._active_skills:
            return ""

        # Keywords para cada tipo de skill
        skill_keywords = {
            "security-auditor": [
                "seguridad",
                "vulnerabilidad",
                "audita",
                "revisa",
                "audit",
                "security",
                "vulnerability",
            ],
            "code-reviewer": [
                "revisa",
                "código",
                "review",
                "mejora",
                "optimiza",
                "code",
                "review",
                "refactor",
            ],
            "api-designer": ["api", "rest", "endpoint", "diseña api", "openapi", "swagger"],
            "rag-optimizer": ["rag", "vector", "embedding", "chroma", "búsqueda", "search"],
            "fastapi-expert": ["fastapi", "web", "endpoint", "async", "uvicorn"],
            "database-architect": ["base de datos", "sql", "schema", "tabla", "database", "sqlite"],
        }

        user_lower = user_message.lower()
        relevant_skills = []

        for skill in self._active_skills:
            skill_name = skill["name"]
            keywords = skill_keywords.get(skill_name, [])

            # Check if any keyword matches
            is_relevant = any(keyword in user_lower for keyword in keywords)

            # Special case: if user asks for a specific skill by name
            if skill_name.replace("-", " ") in user_lower or skill_name in user_lower:
                is_relevant = True

            if is_relevant:
                relevant_skills.append(skill)

        if not relevant_skills:
            return ""  # No agregar skills si ninguna es relevante

        # Build prompt with only relevant skills
        prompts = ["\n# Contexto Especializado (solo para esta consulta):"]
        for skill in relevant_skills:
            prompts.append(
                f"\n## {skill['name']}\n{skill['content'][:500]}..."
            )  # Truncar para no saturar

        prompts.append("\n[Usa este contexto solo si es relevante para responder]")

        return "\n".join(prompts)

    async def get_skill_by_name(self, name: str) -> dict[str, Any] | None:
        """Get a specific skill by name."""
        for skill in self._active_skills:
            if skill["name"] == name:
                return skill
        return None

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
