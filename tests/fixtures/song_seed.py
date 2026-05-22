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
            "level": "3",
            "levelValue": 3.0,
            "internalLevelValue": 3.0,
            "notes": {"total": 120},
        },
        {
            "level": "7",
            "levelValue": 7.2,
            "internalLevelValue": 7.2,
            "notes": {"total": 240},
        },
        {
            "level": "10",
            "levelValue": 10.1,
            "internalLevelValue": 10.1,
            "notes": {"total": 420},
        },
        {
            "level": "13",
            "levelValue": 13.2,
            "internalLevelValue": 13.2,
            "notes": {"total": 700},
        },
    ],
    "dx": [
        {
            "level": "13+",
            "levelValue": 13.7,
            "internalLevelValue": 13.7,
            "notes": {"total": 800},
        }
    ],
}

CHUNI_DIFFICULTIES = {
    "standard": [
        {"level": "4", "levelValue": 4.0, "internalLevelValue": 4.0},
        {"level": "8", "levelValue": 8.4, "internalLevelValue": 8.4},
        {"level": "11", "levelValue": 11.2, "internalLevelValue": 11.2},
        {"level": "13", "levelValue": 13.3, "internalLevelValue": 13.3},
    ],
    "ultima": [
        {"level": "14", "levelValue": 14.1, "internalLevelValue": 14.1}
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
