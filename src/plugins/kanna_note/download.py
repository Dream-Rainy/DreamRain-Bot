import asyncio
import os
from io import BytesIO

from pathlib import Path

import brotli
import httpx
from loguru import logger

from .base import FetchUrl, FilePath
from .database import jp_data
from .util import download_stream


async def download_brotli_db(url: str, path: Path, max_retries: int = 3):
    path.parent.mkdir(parents=True, exist_ok=True)
    FilePath.temp_db.value.parent.mkdir(parents=True, exist_ok=True)

    last_error = None
    for attempt in range(max_retries):
        try:
            decompressor = brotli.Decompressor()
            # 每次重试前清空临时文件
            with open(FilePath.temp_db.value, "wb") as f:
                async for chunk in download_stream(url):
                    f.write(decompressor.process(chunk))
            os.replace(FilePath.temp_db.value, path)
            logger.info(f"下载成功: {url} -> {path}")
            return
        except (httpx.ConnectError, httpx.TimeoutException, httpx.RemoteProtocolError) as e:
            last_error = e
            if attempt < max_retries - 1:
                wait = 2 ** attempt
                logger.warning(f"下载失败 (重试 {attempt + 1}/{max_retries}): {url} — {e}，{wait}s 后重试")
                await asyncio.sleep(wait)
            else:
                logger.error(f"下载失败 (已达最大重试次数): {url} — {e}")

    raise last_error  # type: ignore


async def update_pcr_database():
    errors: list[tuple[str, Exception]] = []
    for url, path in zip(
        (FetchUrl.jp_url.value, FetchUrl.tw_url.value, FetchUrl.cn_url.value, FetchUrl.jp_supplement_url.value),
        (FilePath.jp_db.value, FilePath.tw_db.value, FilePath.cn_db.value, FilePath.jp_supplement_db.value),
    ):
        try:
            await download_brotli_db(url, path)
        except (httpx.ConnectError, httpx.TimeoutException, httpx.RemoteProtocolError) as e:
            errors.append((url, e))
            logger.error(f"下载失败: {url} — {e}")

    if errors:
        failed_urls = "\n".join(f"  - {u}: {e}" for u, e in errors)
        logger.error(f"以下数据库下载失败:\n{failed_urls}")

    # 即使部分下载失败，仍尝试合并已成功的补充库
    if FilePath.jp_supplement_db.value.exists():
        await jp_data.merge_supplement(FilePath.jp_supplement_db.value)

    if errors:
        raise RuntimeError(f"部分数据库下载失败 ({len(errors)}/{4}):\n{failed_urls}")


def generate_pcr_fullcard(id_, star):
    return (
        f"{FetchUrl.fullcard_url.value}/{id_}{star}1.webp",
        FilePath.fullcard.value / f"fullcard_unit_{id_}{star}1.png",
    )


async def cache_download(url, save_path):
    save_path.parent.mkdir(parents=True, exist_ok=True)
    temp = BytesIO()
    async for chunk in download_stream(url):
        temp.write(chunk)
    with open(save_path, "wb") as f:  # 写入文件,防止出错
        f.write(temp.getvalue())


async def get_pcr_fullcard(id_):
    url, save_path = generate_pcr_fullcard(id_, 6)
    if save_path.exists():
        return save_path
    try:
        await cache_download(url, save_path)
        return save_path
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            url, save_path = generate_pcr_fullcard(id_, 3)
            if save_path.exists():
                return save_path
            if not save_path.exists():
                try:
                    await cache_download(url, save_path)
                    return save_path
                except httpx.HTTPStatusError as e:
                    if e.response.status_code == 404:
                        raise ValueError(f"暂无id为{id_}的全卡数据") from e


async def get_skill_icon(skill_icon_id):
    url = f"{FetchUrl.skill_icon_url.value}/{skill_icon_id}.webp"
    save_path = FilePath.skill_icon.value / f"{skill_icon_id}.png"
    if save_path.exists():
        return save_path
    try:
        await cache_download(url, save_path)
        return save_path
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            raise ValueError(f"暂无id为{skill_icon_id}的技能图标") from e


async def get_equipment_icon(equipment_icon_id):
    url = f"{FetchUrl.equipment_url.value}/{equipment_icon_id}.webp"
    save_path = FilePath.equipment.value / f"{equipment_icon_id}.png"
    if save_path.exists():
        return save_path
    try:
        await cache_download(url, save_path)
        return save_path
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            raise ValueError(f"暂无id为{equipment_icon_id}的装备图标") from e


async def get_enemy_icon(enemy_id):
    url = f"{FetchUrl.enemy_icon_url.value}/{enemy_id}.webp"
    save_path = FilePath.enemy.value / f"{enemy_id}.png"
    if save_path.exists():
        return save_path
    try:
        await cache_download(url, save_path)
        return save_path
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            return FilePath.icon.value / "kailu.png"  # 默认图标


async def get_teaser_icon(teaser_id, type_):
    utl = f"{FetchUrl.teaser_url.value.format(type_)}/{teaser_id}.webp"
    save_path = FilePath.teaser.value / f"{teaser_id}.png"
    if save_path.exists():
        return save_path
    try:
        await cache_download(utl, save_path)
        return save_path
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            raise ValueError(f"暂无id为{teaser_id}的预告图标") from e
