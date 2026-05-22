from __future__ import annotations


async def test_priconne_compat_imports_with_nonebot(app):
    from src.plugins.priconne.compat import LegacyBot, LegacyEvent, LegacySession, Service

    assert Service is not None
    assert LegacyBot is not None
    assert LegacyEvent is not None
    assert LegacySession is not None
