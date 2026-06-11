from __future__ import annotations


async def test_chiffon_bot_loads_with_nonebug(app, loaded_chiffon_bot):
    from nonebot.plugin import get_loaded_plugins

    loaded_names = {plugin.name for plugin in get_loaded_plugins()}

    assert loaded_chiffon_bot.name == "chiffon_bot"
    assert "chiffon_bot" in loaded_names


async def test_chiffon_admin_commands_are_registered_on_admin_tree(app, loaded_chiffon_bot):
    from nonebot.matcher import matchers

    command_rules = {
        repr(matcher.rule)
        for matcher_set in matchers.values()
        for matcher in matcher_set
        if matcher.type == "message"
    }

    assert any("Command(cmds=(('admin', 'update'),))" in rule for rule in command_rules)
    assert any("Command(cmds=(('admin', 'clean'),))" in rule for rule in command_rules)
    assert not any("Command(cmds=(('mai', 'update'),))" in rule for rule in command_rules)
    assert not any("Command(cmds=(('chuni', 'update'),))" in rule for rule in command_rules)
    assert not any("Command(cmds=(('mai', 'clean'),))" in rule for rule in command_rules)
    assert not any("Command(cmds=(('chuni', 'clean'),))" in rule for rule in command_rules)
