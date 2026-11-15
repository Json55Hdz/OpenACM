"""A skill the user or the AI created has no hand-written keywords; it must still switch on."""
import pytest

from openacm.core.skill_manager import SkillManager


def _manager(skills):
    m = SkillManager.__new__(SkillManager)
    m._active_skills = skills
    m.last_matched_skill_names = []
    return m


SKILL = {"name": "sql-reviewer", "description": "Revisa consultas SQL buscando índices faltantes y joins costosos",
         "content": "Always check indexes."}


async def test_a_custom_skill_activates_on_a_word_of_its_name():
    out = await _manager([SKILL]).get_active_skills_prompt("necesito ayuda con este reviewer de queries")
    assert "sql-reviewer" in out


async def test_a_custom_skill_activates_on_two_description_words():
    out = await _manager([SKILL]).get_active_skills_prompt("mis consultas tienen joins muy lentos")
    assert "sql-reviewer" in out


async def test_one_common_word_is_not_enough():
    assert await _manager([SKILL]).get_active_skills_prompt("hazme una consultas de ejemplo para cocinar") == ""


async def test_unrelated_messages_leave_the_prompt_alone():
    assert await _manager([SKILL]).get_active_skills_prompt("qué hora es en Tokio") == ""
