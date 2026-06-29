from typing import Any


async def enhance_scores(data):
    """将乐曲成绩列表中的每条记录与谱面数据合并。

    按需从数据库取出对应谱面的 sheet 信息，展开合并到成绩 dict 中，
    同时对 rate 字段做大小写规范化。
    """
    song_cache: dict[int, Any] = {}

    async def enhance_item(item):
        song_id = item["id"]
        if song_id not in song_cache:
            from ....integrations.lxns.client import lxns_client

            song_cache[song_id] = await lxns_client.catalog.get_song_by_id("maimai", song_id)
        song_data = song_cache[song_id]
        if song_data is None:
            return dict(item)

        sheet = song_data.difficulties[item["type"]][item["level_index"]]
        if hasattr(sheet, "model_dump"):
            sheet_data = sheet.model_dump(
                mode="json",
                by_alias=True,
                exclude_none=True,
            )
        else:
            sheet_data = dict(sheet)

        enhanced = dict(item)

        def format_string(name: str) -> str:
            name = name.lower()
            if name.endswith("p"):
                return name[:-1].upper() + "p"
            return name.upper()

        if "rate" in enhanced:
            enhanced["rate"] = format_string(enhanced["rate"])

        enhanced.update(sheet_data)
        return enhanced

    return [await enhance_item(item) for item in data]


def lazy_enhance(data):
    """Deprecated: use async ``enhance_scores`` instead."""
    raise RuntimeError("lazy_enhance 已改为异步 DB-backed 实现，请使用 enhance_scores")
