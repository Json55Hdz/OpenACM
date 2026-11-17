"""Messages that were stored encrypted twice are repaired to a single layer, and nothing else is touched."""
import pytest

from openacm.storage.database import Database
from openacm.watchers.encryption import ActivityEncryptor


@pytest.fixture
async def edb(tmp_path):
    enc = ActivityEncryptor(key_path=tmp_path / "k.key")
    database = Database(str(tmp_path / "t.db"), encryptor=enc)
    await database.initialize()
    yield database, enc
    await database.close()


async def _raw(database, content: str, role="user"):
    """Insert a row with the content EXACTLY as given (no encryption), like the old bug left it."""
    await database._db.execute(
        "INSERT INTO messages (user_id, channel_id, role, content, timestamp) VALUES ('u','c',?,?, '2026-11-01T00:00:00')",
        (role, content),
    )
    await database._db.commit()


async def test_double_encrypted_rows_are_repaired_and_others_left_alone(edb):
    database, enc = edb
    await database.log_message("u", "c", "user", "normal one")                       # single layer
    await _raw(database, enc.encrypt(enc.encrypt("hello from the agent")))           # double layer
    await _raw(database, "plain old row from before encryption existed")             # never encrypted

    before = await database.get_conversation("u", "c")
    assert [m["content"] for m in before][1].startswith("gAAAA")                     # the bug: gibberish

    assert await database._repair_double_encrypted_messages() == 1
    assert await database._repair_double_encrypted_messages() == 0                   # idempotent

    after = [m["content"] for m in await database.get_conversation("u", "c")]
    assert after == ["normal one", "hello from the agent", "plain old row from before encryption existed"]


async def test_nothing_happens_without_an_encryptor(tmp_path):
    database = Database(str(tmp_path / "p.db"))
    await database.initialize()
    assert await database._repair_double_encrypted_messages() == 0
    await database.close()
