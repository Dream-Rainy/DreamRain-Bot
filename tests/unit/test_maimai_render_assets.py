from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from src.plugins.chiffon_bot.domains.maimai.schemas import MaiSongData
from src.plugins.chiffon_bot.domains.maimai.views import mai_bg_draw
from tests.fixtures.song_seed import MAI_DIFFICULTIES, MAI_SONG_ID, MAI_SONG_TITLE


def _b50_user_data() -> dict[str, Any]:
    return {
        "data": {
            "name": "DreamRain",
            "rating": 15000,
            "frame": {"id": 1},
            "trophy": {"color": "Normal", "name": "Test Trophy"},
            "name_plate": {"id": 1},
            "icon": {"id": 1},
            "class_rank": 1,
            "course_rank": 1,
        }
    }


async def test_b50_render_uses_maimai_data_asset_root(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    async def fake_template_to_pic(**kwargs: Any) -> bytes:
        captured.update(kwargs)
        return b"fake-image"

    mai_bg_draw.clear_b50_img_cache()
    monkeypatch.setattr(mai_bg_draw, "template_to_pic", fake_template_to_pic)

    img = await mai_bg_draw.render_b50_img(_b50_user_data(), width=1280, height=536)

    assert img == b"fake-image"
    assert captured["template_path"] == mai_bg_draw.template_search_paths
    assert captured["template_name"] == "b50.html"
    assert captured["pages"]["base_url"] == mai_bg_draw._template_base_uri
    assert captured["pages"]["base_url"].startswith("file:")
    assert Path(captured["templates"]["base_url"]) == mai_bg_draw._MAIMAI_ASSETS_DIR


async def test_song_info_render_uses_maimai_data_asset_root(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    async def fake_template_to_pic(**kwargs: Any) -> bytes:
        captured.update(kwargs)
        return b"fake-song-info"

    mai_bg_draw.clear_song_info_img_cache()
    monkeypatch.setattr(mai_bg_draw, "template_to_pic", fake_template_to_pic)

    song_data = MaiSongData(
        id=MAI_SONG_ID,
        title=MAI_SONG_TITLE,
        artist="supercell",
        category="POPS&ANIME",
        bpm=165,
        version="PRiSM",
        rights="test rights",
        image_name="UI_Jacket_000181.png",
        difficulties=MAI_DIFFICULTIES,
    )

    img = await mai_bg_draw.render_song_info_img(song_data)

    assert img == b"fake-song-info"
    assert captured["template_path"] == mai_bg_draw.template_search_paths
    assert captured["template_name"] == "song_info.html"
    assert captured["pages"]["base_url"] == mai_bg_draw._template_base_uri
    assert captured["pages"]["base_url"].startswith("file:")
    assert Path(captured["templates"]["base_url"]) == mai_bg_draw._MAIMAI_ASSETS_DIR
    assert captured["templates"]["bg_page_url"] == "bg_html/prism/prism.html"


def test_maimai_asset_root_matches_runtime_data_dir() -> None:
    expected = Path.cwd() / "data" / "chiffon_bot" / "template" / "maimai"

    assert mai_bg_draw._MAIMAI_ASSETS_DIR.resolve() == expected.resolve()
    if Path.cwd().as_posix() == "/app":
        assert mai_bg_draw._MAIMAI_ASSETS_DIR.as_posix() == (
            "/app/data/chiffon_bot/template/maimai"
        )


def test_maimai_required_assets_are_present_when_asset_check_is_enabled() -> None:
    required_assets = (
        "assets/UI_CMN_Num_70p.png",
        "assets/title_bg_prism.png",
        "assets/UI_CMN_DXRating_11.png",
        "assets/UI_PFC_MS_Info02_BSC.png",
        "bg_html/prism_plus/prism_plus.html",
        "bg_html/prism/prism.html",
        "jacket/UI_Jacket_000000.png",
    )
    require_assets = os.getenv("CHIFFON_REQUIRE_MAIMAI_ASSETS") == "1"
    asset_root = mai_bg_draw._MAIMAI_ASSETS_DIR
    missing = [rel for rel in required_assets if not (asset_root / rel).is_file()]

    if missing and not require_assets:
        pytest.skip(
            "maimai asset directory is not populated; set "
            "CHIFFON_REQUIRE_MAIMAI_ASSETS=1 to make this a hard failure"
        )

    assert missing == []
