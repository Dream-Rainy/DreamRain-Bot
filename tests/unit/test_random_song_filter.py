from __future__ import annotations


class DummyAdapter:
    game_code = "dummy"
    display_name = "dummy"
    level_names = ["BASIC", "ADVANCED", "EXPERT", "MASTER", "ULTIMA"]
    difficulty_types = ["standard", "dx"]


async def test_parse_difficulty_range(loaded_chiffon_bot):
    from src.plugins.chiffon_bot.shared.handlers.generic_random_song import (
        parse_difficulty_range,
    )

    assert parse_difficulty_range("13") == (13.0, 13.5)
    assert parse_difficulty_range("13+") == (13.6, 13.9)
    assert parse_difficulty_range("13.5") == (13.5, 13.5)
    assert parse_difficulty_range("12-13+") == (12.0, 13.9)
    assert parse_difficulty_range("abc") is None


async def test_filter_songs_by_difficulty_range(loaded_chiffon_bot):
    from src.plugins.chiffon_bot.shared.handlers.generic_random_song import (
        get_songs_by_difficulty_range,
    )
    from src.plugins.chiffon_bot.shared.song_data import SongData

    store = {
        1: SongData(
            id=1,
            title="Song A",
            difficulties={
                "standard": [
                    {"type": "std", "difficulty": "BASIC", "level": "12", "internalLevelValue": 12.4},
                    {"type": "std", "difficulty": "ADVANCED", "level": "13", "internalLevelValue": 13.2},
                ],
                "dx": [{"type": "dx", "difficulty": "EXPERT", "level": "14", "levelValue": 14.0}],
            },
        ),
        2: SongData(
            id=2,
            title="Song B",
            difficulties={
                "standard": [{"type": "std", "difficulty": "MASTER", "level": "13+", "internalLevelValue": 13.8}]
            },
        ),
    }

    matches = get_songs_by_difficulty_range(store, 13.0, 13.5, DummyAdapter())

    assert len(matches) == 1
    assert matches[0]["song_data"].id == 1
    assert matches[0]["song_type"] == "standard"
    assert matches[0]["level_value"] == 13.2
