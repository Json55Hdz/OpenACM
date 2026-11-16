"""History pages backwards: 'load earlier messages' asks for the ones before the oldest it has."""


async def test_conversation_pages_backwards(db):
    for i in range(10):
        await db.log_message("u", "web", "user", f"m{i}")

    newest = await db.get_conversation("u", "web", limit=4)
    assert [m["content"] for m in newest] == ["m6", "m7", "m8", "m9"]       # oldest first within a page
    assert all(isinstance(m["id"], int) for m in newest)

    older = await db.get_conversation("u", "web", limit=4, before_id=min(m["id"] for m in newest))
    assert [m["content"] for m in older] == ["m2", "m3", "m4", "m5"]

    oldest = await db.get_conversation("u", "web", limit=4, before_id=min(m["id"] for m in older))
    assert [m["content"] for m in oldest] == ["m0", "m1"]                   # short page: nothing before it
    assert await db.get_conversation("u", "web", limit=4, before_id=min(m["id"] for m in oldest)) == []
