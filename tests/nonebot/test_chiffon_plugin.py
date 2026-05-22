from __future__ import annotations


async def test_chiffon_bot_loads_with_nonebug(app, loaded_chiffon_bot):
    from nonebot.plugin import get_loaded_plugins

    loaded_names = {plugin.name for plugin in get_loaded_plugins()}

    assert loaded_chiffon_bot.name == "chiffon_bot"
    assert "chiffon_bot" in loaded_names
