import pytest
from openacm.storage.database import Database


@pytest.fixture
async def db():
    database = Database(":memory:")
    await database.initialize()
    yield database
    await database.close()


class TestCustomerNames:
    async def test_unknown_conversation_returns_none(self, db):
        assert await db.get_customer_name("u1", "web") is None

    async def test_set_and_read_name(self, db):
        await db.set_customer_name("u1", "web", "Juan")
        assert await db.get_customer_name("u1", "web") == "Juan"

    async def test_set_overwrites_existing_name(self, db):
        await db.set_customer_name("u1", "web", "Juan")
        await db.set_customer_name("u1", "web", "Juan Perez")
        assert await db.get_customer_name("u1", "web") == "Juan Perez"

    async def test_isolated_per_user_and_channel(self, db):
        await db.set_customer_name("u1", "whatsapp", "Ana")
        await db.set_customer_name("u2", "whatsapp", "Beto")
        await db.set_customer_name("u1", "telegram", "Ana en Telegram")
        assert await db.get_customer_name("u1", "whatsapp") == "Ana"
        assert await db.get_customer_name("u2", "whatsapp") == "Beto"
        assert await db.get_customer_name("u1", "telegram") == "Ana en Telegram"
