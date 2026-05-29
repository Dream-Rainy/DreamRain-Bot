from __future__ import annotations


def test_build_uses_saa_image_constructor_shape(app):
    from nonebot_plugin_saa import Image, Reply, Text

    from src.plugins.chiffon_bot.app.commands._response import _build
    from src.plugins.chiffon_bot.shared.bot_response import BotResponse

    image = b"fake-png"

    segments = _build(
        BotResponse(text="hello", image=image, reply_to=123, suffix="done")
    )

    assert [type(segment) for segment in segments] == [Reply, Text, Image, Text]
    assert segments[2].data["image"] == image
