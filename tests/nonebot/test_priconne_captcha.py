from __future__ import annotations

import asyncio


def test_priconne_manual_validate_single_pending(app):
    from src.plugins.priconne import captcha

    captcha._pending.clear()
    req = captcha.ManualCaptchaRequest(
        token="abc123",
        challenge="challenge",
        gt="gt",
        userid="userid",
        event=asyncio.Event(),
    )
    captcha._pending[req.token] = req

    token = captcha.submit_manual_validate("validate-value")

    assert token == "abc123"
    assert req.validate == "validate-value"
    assert req.event.is_set()


def test_priconne_manual_validate_requires_token_when_multiple_pending(app):
    from src.plugins.priconne import captcha

    captcha._pending.clear()
    captcha._pending["one"] = captcha.ManualCaptchaRequest("one", "c", "gt", "u", asyncio.Event())
    captcha._pending["two"] = captcha.ManualCaptchaRequest("two", "c", "gt", "u", asyncio.Event())

    try:
        captcha.submit_manual_validate("validate-value")
    except ValueError as e:
        assert "多个等待中的验证码" in str(e)
    else:
        raise AssertionError("submit_manual_validate should require token with multiple pending requests")


def test_priconne_captcha_mode_toggle(app):
    from src.plugins.priconne import captcha

    captcha.set_captcha_auto(False)
    assert not captcha.is_captcha_auto_enabled()

    captcha.set_captcha_auto(True)
    assert captcha.is_captcha_auto_enabled()
