from __future__ import annotations


def test_extract_oauth_code_from_plain_text(loaded_chiffon_bot):
    from src.plugins.chiffon_bot.app.commands.account import _extract_oauth_code_from_text

    assert _extract_oauth_code_from_text("AUTH_code-123456") == "AUTH_code-123456"
    assert _extract_oauth_code_from_text("code: AUTH_code-123456") == "AUTH_code-123456"
    assert _extract_oauth_code_from_text("code AUTH_code-123456") == "AUTH_code-123456"


def test_extract_oauth_code_from_query_string(loaded_chiffon_bot):
    from src.plugins.chiffon_bot.app.commands.account import _extract_oauth_code_from_text

    assert _extract_oauth_code_from_text("code=AUTH_code-123456&state=st_ok", expected_state="st_ok") == "AUTH_code-123456"
    assert _extract_oauth_code_from_text("?state=st_ok&code=AUTH_code-123456", expected_state="st_ok") == "AUTH_code-123456"


def test_extract_oauth_code_from_callback_url(loaded_chiffon_bot):
    from src.plugins.chiffon_bot.app.commands.account import _extract_oauth_code_from_text

    url = "https://relay.example.com/callback?code=AUTH_code-123456&state=st_ok"
    assert _extract_oauth_code_from_text(url, expected_state="st_ok") == "AUTH_code-123456"


def test_extract_oauth_code_from_copied_multiline_payload(loaded_chiffon_bot):
    from src.plugins.chiffon_bot.app.commands.account import _extract_oauth_code_from_text

    assert _extract_oauth_code_from_text(
        "code=AUTH_code-123456\nstate=st_ok",
        expected_state="st_ok",
    ) == "AUTH_code-123456"
    assert _extract_oauth_code_from_text(
        "state=st_ok\ncode=AUTH_code-123456",
        expected_state="st_ok",
    ) == "AUTH_code-123456"


def test_extract_oauth_code_rejects_wrong_state(loaded_chiffon_bot):
    from src.plugins.chiffon_bot.app.commands.account import _extract_oauth_code_from_text

    url = "https://relay.example.com/callback?code=AUTH_code-123456&state=st_other"
    assert _extract_oauth_code_from_text(url, expected_state="st_ok") is None
    assert _extract_oauth_code_from_text("code=AUTH_code-123456\nstate=st_other", expected_state="st_ok") is None
    assert _extract_oauth_code_from_text("state=st_other\ncode=AUTH_code-123456", expected_state="st_ok") is None
    assert _extract_oauth_code_from_text("not an oauth code") is None
