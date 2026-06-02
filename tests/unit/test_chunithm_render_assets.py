from __future__ import annotations

from pathlib import Path
from typing import Any


def test_build_chuni_jacket_image_name_branches(loaded_chiffon_bot) -> None:
    from src.plugins.chiffon_bot.domains.chunithm.services.chunithm_data_fetcher import (
        build_chuni_jacket_image_name,
    )

    assert (
        build_chuni_jacket_image_name(8270, "CHU_UI_Jacket_2450.dds")
        == "jacket/CHU_UI_Jacket_2450.png"
    )
    assert (
        build_chuni_jacket_image_name(8270, "jacket/CHU_UI_Jacket_2450.png")
        == "jacket/CHU_UI_Jacket_2450.png"
    )
    assert (
        build_chuni_jacket_image_name(8270)
        == "https://assets2.lxns.net/chunithm/jacket/8270.png"
    )
    assert (
        build_chuni_jacket_image_name(8270, remote_assets_base_url="https://example.test/chuni")
        == "https://example.test/chuni/jacket/8270.png"
    )
    assert build_chuni_jacket_image_name(None) == ""


def test_chuni_music_xml_parser_reads_jaket_file(tmp_path: Path) -> None:
    from src.plugins.chiffon_bot.domains.chunithm.services.music_xml_parser import (
        parse_music_xml,
    )

    music_xml = tmp_path / "Music.xml"
    music_xml.write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<MusicData>
  <name><id>8270</id><str>Test Song</str></name>
  <jaketFile><path>CHU_UI_Jacket_2450.dds</path></jaketFile>
</MusicData>
""",
        encoding="utf-8",
    )

    parsed = parse_music_xml(music_xml)

    assert parsed is not None
    assert parsed["id"] == 8270
    assert parsed["image_name"] == "jacket/CHU_UI_Jacket_2450.png"


async def test_chuni_song_info_render_uses_chuni_data_asset_root(
    loaded_chiffon_bot,
    monkeypatch,
) -> None:
    from src.plugins.chiffon_bot.domains.chunithm.schemas import ChuniSongData
    from src.plugins.chiffon_bot.domains.chunithm.views import chuni_bg_draw

    captured: dict[str, Any] = {}

    async def fake_template_to_pic(**kwargs: Any) -> bytes:
        captured.update(kwargs)
        return b"fake-chuni-song-info"

    chuni_bg_draw.clear_chuni_song_info_img_cache()
    monkeypatch.setattr(chuni_bg_draw, "template_to_pic", fake_template_to_pic)

    song_data = ChuniSongData(
        id=8270,
        title="セガサターン起動音[H.][Remix]",
        artist="Hiro",
        genre="VARIETY",
        bpm=120,
        version=16,
        image_name="jacket/CHU_UI_Jacket_2450.png",
        difficulties={
            "we": [
                {
                    "type": "we",
                    "difficulty": "舞",
                    "level": "☆4",
                    "noteCounts": {"total": 100},
                }
            ]
        },
    )

    img = await chuni_bg_draw.render_chuni_song_info_img(song_data)

    assert img == b"fake-chuni-song-info"
    assert captured["template_name"] == "chuni_song_info.html"
    assert captured["pages"]["base_url"] == chuni_bg_draw._template_base_uri
    assert Path(captured["templates"]["base_url"]) == chuni_bg_draw._CHUNI_ASSETS_DIR
    assert captured["templates"]["bg_page_url"] == "bg_html/X-VERSE-X/X-VERSE-X.html"
    assert captured["templates"]["song_info"]["image_name"] == "jacket/CHU_UI_Jacket_2450.png"
    assert "jacket_url" not in captured["templates"]["song_info"]
