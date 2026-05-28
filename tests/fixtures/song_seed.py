from __future__ import annotations

MAI_SONG_ID = 181
MAI_SONG_TITLE = "君の知らない物語"
MAI_ALIAS = "kimishira"

CHUNI_SONG_ID = 1
CHUNI_SONG_TITLE = "Help me, ERINNNNNN!!"
CHUNI_ALIAS = "えーりん"


MAI_DIFFICULTIES = {
    "standard": [
        {
            "type": "std",
            "difficulty": "basic",
            "level": "3",
            "levelValue": 3.0,
            "internalLevelValue": 3.0,
            "noteCounts": {"total": 120},
        },
        {
            "type": "std",
            "difficulty": "advanced",
            "level": "7",
            "levelValue": 7.2,
            "internalLevelValue": 7.2,
            "noteCounts": {"total": 240},
        },
        {
            "type": "std",
            "difficulty": "expert",
            "level": "10",
            "levelValue": 10.1,
            "internalLevelValue": 10.1,
            "noteCounts": {"total": 420},
        },
        {
            "type": "std",
            "difficulty": "master",
            "level": "13",
            "levelValue": 13.2,
            "internalLevelValue": 13.2,
            "noteCounts": {"total": 700},
        },
    ],
    "dx": [
        {
            "type": "dx",
            "difficulty": "master",
            "level": "13+",
            "levelValue": 13.7,
            "internalLevelValue": 13.7,
            "noteCounts": {"total": 800},
        }
    ],
}

CHUNI_DIFFICULTIES = {
    "standard": [
        {"type": "std", "difficulty": "BASIC", "level": "4", "levelValue": 4.0, "internalLevelValue": 4.0},
        {"type": "std", "difficulty": "ADVANCED", "level": "8", "levelValue": 8.4, "internalLevelValue": 8.4},
        {"type": "std", "difficulty": "EXPERT", "level": "11", "levelValue": 11.2, "internalLevelValue": 11.2},
        {"type": "std", "difficulty": "MASTER", "level": "13", "levelValue": 13.3, "internalLevelValue": 13.3},
    ],
    "ultima": [
        {"type": "std", "difficulty": "ULTIMA", "level": "14", "levelValue": 14.1, "internalLevelValue": 14.1}
    ],
}


async def seed_song_data() -> None:
    from src.plugins.chiffon_bot.infra.db.models import (
        ChuniSong,
        ChuniSongAlias,
        MaiSong,
        MaiSongAlias,
    )

    mai_song = await MaiSong.create(
        id=MAI_SONG_ID,
        title=MAI_SONG_TITLE,
        artist="supercell",
        category="POPS&ANIME",
        bpm=165,
        version="PRiSM",
        rights="test rights",
        difficulties=MAI_DIFFICULTIES,
        collections=[],
    )
    await MaiSongAlias.create(song=mai_song, alias=MAI_ALIAS, priority=0)
    await MaiSongAlias.create(song=mai_song, alias=MAI_SONG_TITLE, priority=1)

    chuni_song = await ChuniSong.create(
        id=CHUNI_SONG_ID,
        title=CHUNI_SONG_TITLE,
        artist="ビートまりお",
        genre="東方Project",
        bpm=180,
        version=1,
        rights="test rights",
        difficulties=CHUNI_DIFFICULTIES,
    )
    await ChuniSongAlias.create(song=chuni_song, alias=CHUNI_ALIAS, priority=0)
    await ChuniSongAlias.create(song=chuni_song, alias=CHUNI_SONG_TITLE, priority=1)
