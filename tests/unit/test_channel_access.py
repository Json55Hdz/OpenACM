"""External channels: who may talk, and with which tools (owner / guest / blocked)."""
import pytest

from openacm.core.channel_access import AccessError, ChannelAccess, GRANTABLE


def make(data=None):
    a = ChannelAccess()
    if data:
        a.data = {"channels": data.get("channels", {}), "chats": data.get("chats", {})}
    return a


def test_the_dashboard_and_other_internal_channels_are_never_limited():
    a = make({"channels": {"telegram": {"mode": "whitelist", "owners": []}}})
    for ch in ("web", "console", "cron", "swarm_1"):
        g = a.resolve(ch, "anyone", "x")
        assert g.owner and g.allows("run_command")


def test_an_unconfigured_external_channel_lets_strangers_chat_but_gives_them_no_tools():
    g = make().resolve("telegram", "999", "999")
    assert g.talk and not g.owner and not g.allows("web_search") and not g.allows("run_command")


def test_owners_get_everything_everywhere():
    a = make({"channels": {"telegram": {"mode": "whitelist", "owners": ["42"]}}})
    assert a.resolve("telegram", "42", "group").allows("run_python")


def test_whitelist_ignores_everyone_else():
    a = make({"channels": {"whatsapp": {"mode": "whitelist", "owners": ["1"]}}})
    g = a.resolve("whatsapp", "2", "2")
    assert not g.talk and not g.allows("web_search")


def test_basic_guests_only_search_the_web():
    a = make({"channels": {"discord": {"mode": "public", "owners": [], "guest": {"level": "basic"}}}})
    g = a.resolve("discord", "7", "7")
    assert g.allows("web_search") and not g.allows("read_file") and not g.allows("run_command")


def test_a_single_chat_can_have_its_own_profile():
    a = make({
        "channels": {"telegram": {"mode": "whitelist", "owners": ["1"]}},
        "chats": {"telegram:-100": {"level": "basic"}, "telegram:-200": {"level": "owner"}, "telegram:-300": {"level": "blocked"}},
    })
    assert a.resolve("telegram", "9", "-100").allows("web_search")          # let in despite the whitelist
    assert a.resolve("telegram", "9", "-200").owner                          # everyone there is trusted
    assert not a.resolve("telegram", "9", "-300").talk
    assert not a.resolve("telegram", "9", "-999").talk                       # other chats still closed


def test_custom_profile_never_exceeds_what_can_be_granted():
    a = make({"channels": {"telegram": {"mode": "public", "guest": {"level": "custom", "tools": ["web_search", "run_command"]}}}})
    g = a.resolve("telegram", "5", "5")
    assert g.tools == frozenset({"web_search"})


async def test_saving_refuses_dangerous_tools_for_guests():
    a = make()
    with pytest.raises(AccessError, match="no se puede dar"):
        await a.update({"channels": {"telegram": {"mode": "public", "guest": {"level": "custom", "tools": ["run_command"]}}}})
    with pytest.raises(AccessError):
        await a.update({"channels": {"myspace": {}}})
    with pytest.raises(AccessError):
        await a.update({"chats": {"telegram:1": {"level": "god"}}})


async def test_saved_settings_survive_a_restart(db):
    a = make()
    await a.load(db)
    await a.update({"channels": {"telegram": {"mode": "whitelist", "owners": [" 42 ", "42", "7"]}},
                    "chats": {"telegram:-1": {"level": "basic"}}})
    b = ChannelAccess()
    await b.load(db)
    assert b.channel("telegram")["owners"] == ["42", "7"] and "telegram:-1" in b.data["chats"]


async def test_the_old_allow_list_becomes_the_owner_whitelist(db):
    a = ChannelAccess()
    await a.load(db, legacy_owners={"telegram": ["11", "12"]})
    assert a.channel("telegram")["mode"] == "whitelist" and a.resolve("telegram", "11", "11").owner
    assert not a.resolve("telegram", "99", "99").talk


def test_filtering_the_tool_list_for_a_guest():
    a = make({"channels": {"telegram": {"mode": "public", "guest": {"level": "basic"}}}})
    schema = [{"function": {"name": n}} for n in ("web_search", "run_command", "read_file")]
    out = a.filter_tools(schema, a.resolve("telegram", "5", "5"))
    assert [t["function"]["name"] for t in out] == ["web_search"]
    assert a.filter_tools(schema, a.resolve("web", "x", "x")) == schema


def test_strangers_are_remembered_so_the_owner_can_promote_them():
    a = make()
    a.note_unknown("telegram", "5", "5", True)
    a.note_unknown("telegram", "5", "5", True)
    assert a.unknown[0]["count"] == 2


async def test_the_registry_refuses_a_tool_the_profile_does_not_allow(brain, tool_registry):
    from openacm.tools import file_ops

    tool_registry.register_module(file_ops)
    brain.channel_access.data = {"channels": {"telegram": {"mode": "public", "guest": {"level": "none"}}}, "chats": {}}
    args = {"path": "no-such-file.txt"}
    out = await tool_registry.execute("read_file", args, "5", "5", "telegram", _brain=brain)
    assert "permission" in out
    owner_out = await tool_registry.execute("read_file", args, "5", "5", "web", _brain=brain)
    assert "permission" not in owner_out


async def test_a_blocked_sender_gets_no_answer_at_all(brain):
    brain.channel_access.data = {"channels": {"whatsapp": {"mode": "whitelist", "owners": ["1"]}}, "chats": {}}
    assert await brain.process_message("hola", "2", "2", channel_type="whatsapp") == ""


def test_grantable_tools_are_read_only_things():
    assert not ({"run_command", "run_python", "write_file", "read_file", "gmail_send"} & GRANTABLE)
