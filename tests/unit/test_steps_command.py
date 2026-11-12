"""Per-chat tool-step limit: /steps command + BrainLoopMixin._resolve_step_limit."""
from types import SimpleNamespace

from openacm.core.brain_loop import BrainLoopMixin
from openacm.core.commands import CommandProcessor
from openacm.core.messages import STEPS_UNLIMITED


class FakeDB:
    def __init__(self):
        self.data = {}

    async def get_setting(self, key):
        return self.data.get(key)

    async def set_setting(self, key, value):
        self.data[key] = value


class FakeBrain(BrainLoopMixin):
    def __init__(self, db):
        self.config = SimpleNamespace(max_tool_iterations=25)
        self.memory = SimpleNamespace(database=db)
        self._step_limits = {}


async def test_default_limit_when_nothing_set():
    brain = FakeBrain(FakeDB())
    assert await brain._resolve_step_limit("u", "web") == 25


async def test_set_number_applies_only_to_that_chat_and_persists():
    db = FakeDB()
    brain = FakeBrain(db)
    cp = CommandProcessor(brain, db)
    res = await cp.handle("/steps", "200", "u1", "web")
    assert res.handled and "200" in res.text
    assert await brain._resolve_step_limit("u1", "web") == 200
    assert await brain._resolve_step_limit("u2", "web") == 25
    # survives a restart: a fresh brain reads it back from the database
    assert await FakeBrain(db)._resolve_step_limit("u1", "web") == 200


async def test_off_removes_limit_and_default_restores_it():
    db = FakeDB()
    brain = FakeBrain(db)
    cp = CommandProcessor(brain, db)
    await cp.handle("/steps", "off", "u", "web")
    assert await brain._resolve_step_limit("u", "web") == STEPS_UNLIMITED
    assert "no limit" in (await cp.handle("/steps", "", "u", "web")).text
    await cp.handle("/steps", "default", "u", "web")
    assert await brain._resolve_step_limit("u", "web") == 25
    assert await FakeBrain(db)._resolve_step_limit("u", "web") == 25


async def test_invalid_argument_changes_nothing():
    db = FakeDB()
    brain = FakeBrain(db)
    res = await CommandProcessor(brain, db).handle("/steps", "muchos", "u", "web")
    assert res.handled and "Usage" in res.text
    assert await brain._resolve_step_limit("u", "web") == 25
