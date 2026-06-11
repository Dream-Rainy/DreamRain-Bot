"""Jacket image recognition for song search."""

from __future__ import annotations

import asyncio
import hashlib
import tempfile
import traceback
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse

import cv2
import numpy as np
from nonebot import logger
from PIL import Image, UnidentifiedImageError

from ...infra.http.client import HttpClient
from ..game.adapter import DomainAdapter
from ..song_data import SongData

try:
    import diskcache
except Exception:  # pragma: no cover
    diskcache = None  # type: ignore[assignment]


_HASH_SIZE = 16
_HASH_BITS = _HASH_SIZE * _HASH_SIZE
_MAX_DETECT_SIDE = 1200
_CONFIDENT_MAX_DISTANCE = 70
_STRONG_MAX_DISTANCE = 45
_CONFIDENT_DISTANCE_GAP = 6
_REMOTE_DOWNLOAD_CONCURRENCY = 8

_CACHE_DIR = Path(tempfile.gettempdir()) / "dreamrain_bot" / "jacket_recognition"
_CACHE_DIR.mkdir(parents=True, exist_ok=True)
_hash_cache = diskcache.Cache(str(_CACHE_DIR / "hashes")) if diskcache is not None else None
_bytes_cache = diskcache.Cache(str(_CACHE_DIR / "bytes")) if diskcache is not None else None

_http_client = HttpClient(
    cache_dir=str(_CACHE_DIR / "http"),
    cache_ttl_seconds=30 * 24 * 3600,
    timeout_seconds=12,
)


@dataclass(frozen=True)
class CropSelection:
    """A selected square-ish image region in source-image coordinates."""

    image: Image.Image
    box: tuple[int, int, int, int]


@dataclass(frozen=True)
class JacketReference:
    """A precomputed song jacket hash."""

    song_id: int
    title: str
    image_name: str
    hash_value: np.ndarray


@dataclass(frozen=True)
class JacketMatch:
    """One recognition candidate."""

    song_id: int
    title: str
    image_name: str
    distance: int


@dataclass(frozen=True)
class JacketRecognitionResult:
    """Recognition output with confidence metadata."""

    matches: list[JacketMatch]
    crop_box: tuple[int, int, int, int] | None = None
    reference_count: int = 0

    @property
    def best(self) -> JacketMatch | None:
        return self.matches[0] if self.matches else None

    @property
    def is_confident(self) -> bool:
        best = self.best
        if best is None:
            return False
        if best.distance > _CONFIDENT_MAX_DISTANCE:
            return False
        if best.distance <= _STRONG_MAX_DISTANCE or len(self.matches) == 1:
            return True
        return self.matches[1].distance - best.distance >= _CONFIDENT_DISTANCE_GAP


_reference_cache_by_game: dict[str, list[JacketReference]] = {}
_build_locks: dict[str, asyncio.Lock] = {}


def _open_image(image_bytes: bytes) -> Image.Image:
    try:
        return Image.open(BytesIO(image_bytes)).convert("RGB")
    except UnidentifiedImageError as exc:
        raise ValueError("无法解析图片，请换一张更清晰的截图再试") from exc


def _dhash(image: Image.Image, hash_size: int = _HASH_SIZE) -> np.ndarray:
    """Compute a horizontal difference hash as a flat uint8 array."""

    resized = image.resize((hash_size + 1, hash_size), Image.Resampling.LANCZOS).convert("L")
    pixels = np.asarray(resized, dtype=np.int16)
    return (pixels[:, :-1] > pixels[:, 1:]).astype(np.uint8).reshape(-1)


def _hash_distance(left: np.ndarray, right: np.ndarray) -> int:
    if left.shape != right.shape:
        raise ValueError("hash shape mismatch")
    return int(np.abs(left.astype(np.int16) - right.astype(np.int16)).sum())


def _trim_inner(image: Image.Image, margin_ratio: float) -> Image.Image:
    width, height = image.size
    margin_x = int(width * margin_ratio)
    margin_y = int(height * margin_ratio)
    if margin_x <= 0 and margin_y <= 0:
        return image
    if margin_x * 2 >= width or margin_y * 2 >= height:
        return image
    return image.crop((margin_x, margin_y, width - margin_x, height - margin_y))


def _center_square(image: Image.Image) -> Image.Image:
    width, height = image.size
    side = min(width, height)
    left = (width - side) // 2
    top = (height - side) // 2
    return image.crop((left, top, left + side, top + side))


def select_largest_square_crop(image: Image.Image) -> CropSelection | None:
    """Find the largest square-ish detailed object in an input screenshot."""

    width, height = image.size
    if width <= 0 or height <= 0:
        return None

    scale = min(1.0, _MAX_DETECT_SIDE / max(width, height))
    detect = image
    if scale < 1.0:
        detect = image.resize((int(width * scale), int(height * scale)), Image.Resampling.LANCZOS)

    arr = np.asarray(detect.convert("RGB"))
    gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blurred, 50, 150)
    kernel = np.ones((5, 5), np.uint8)
    edges = cv2.dilate(edges, kernel, iterations=2)
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    detect_width, detect_height = detect.size
    total_area = detect_width * detect_height
    min_side = max(42, int(min(detect_width, detect_height) * 0.045))
    min_area = max(1600, int(total_area * 0.004))

    boxes: list[tuple[int, int, int, int]] = []
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        if w < min_side or h < min_side:
            continue
        ratio = w / h
        if not 0.72 <= ratio <= 1.28:
            continue
        area = w * h
        if area < min_area:
            continue
        if area > total_area * 0.35:
            continue
        boxes.append((x, y, w, h))

    if not boxes:
        return None

    x, y, w, h = max(boxes, key=lambda box: box[2] * box[3])
    if scale < 1.0:
        inv = 1.0 / scale
        x = int(x * inv)
        y = int(y * inv)
        w = int(w * inv)
        h = int(h * inv)

    side = min(w, h)
    x = max(0, min(width - side, x + (w - side) // 2))
    y = max(0, min(height - side, y + (h - side) // 2))
    box = (x, y, side, side)
    return CropSelection(image=image.crop((x, y, x + side, y + side)), box=box)


def _query_variants(
    image: Image.Image,
    selection: CropSelection | None,
) -> list[tuple[Image.Image, tuple[int, int, int, int] | None]]:
    variants: list[tuple[Image.Image, tuple[int, int, int, int] | None]] = []
    if selection is not None:
        variants.append((_trim_inner(selection.image, 0.06), selection.box))
        variants.append((selection.image, selection.box))

    centered = _center_square(image)
    if centered.size[0] >= 48 and centered.size[1] >= 48:
        variants.append((_trim_inner(centered, 0.04), None))
        variants.append((centered, None))

    variants.append((_trim_inner(image, 0.04), None))
    variants.append((image, None))
    return variants


def rank_jacket_matches(
    image: Image.Image,
    references: Iterable[JacketReference],
    *,
    limit: int = 5,
) -> JacketRecognitionResult:
    """Rank references against the largest jacket-like region in an image."""

    refs = list(references)
    if not refs:
        return JacketRecognitionResult(matches=[], reference_count=0)

    selection = select_largest_square_crop(image)
    best_by_song: dict[int, JacketMatch] = {}

    for variant, _ in _query_variants(image, selection):
        query_hash = _dhash(variant)
        for ref in refs:
            distance = _hash_distance(query_hash, ref.hash_value)
            current = best_by_song.get(ref.song_id)
            if current is None or distance < current.distance:
                best_by_song[ref.song_id] = JacketMatch(
                    song_id=ref.song_id,
                    title=ref.title,
                    image_name=ref.image_name,
                    distance=distance,
                )

    matches = sorted(best_by_song.values(), key=lambda item: item.distance)[:limit]
    return JacketRecognitionResult(
        matches=matches,
        crop_box=selection.box if selection else None,
        reference_count=len(refs),
    )


def _is_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _asset_path_for_image(image_name: str) -> Path | None:
    if not image_name or _is_url(image_name):
        return None
    path = Path(image_name)
    if path.is_absolute():
        return path
    return Path.cwd() / "data" / "chiffon_bot" / "template" / "maimai" / image_name


def _cache_key_for_song(game_code: str, song: SongData) -> str:
    image_name = getattr(song, "image_name", "") or ""
    path = _asset_path_for_image(image_name)
    marker = ""
    if path is not None and path.exists():
        stat = path.stat()
        marker = f"{stat.st_mtime_ns}:{stat.st_size}"
    else:
        marker = image_name
    raw = f"v1|{game_code}|{song.id}|{image_name}|{marker}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _hash_to_cache_payload(hash_value: np.ndarray) -> list[int]:
    return [int(x) for x in hash_value.reshape(-1).tolist()]


def _hash_from_cache_payload(payload: object) -> np.ndarray | None:
    if not isinstance(payload, list) or len(payload) != _HASH_BITS:
        return None
    try:
        return np.asarray([1 if int(x) else 0 for x in payload], dtype=np.uint8)
    except Exception:
        return None


async def _load_image_bytes(image_name: str) -> bytes | None:
    if not image_name:
        return None

    local_path = _asset_path_for_image(image_name)
    if local_path is not None:
        if not local_path.exists():
            return None
        return local_path.read_bytes()

    if not _is_url(image_name):
        return None

    bytes_key = hashlib.sha256(image_name.encode("utf-8")).hexdigest()
    if _bytes_cache is not None:
        cached = _bytes_cache.get(bytes_key, default=None)
        if isinstance(cached, bytes):
            return cached

    try:
        data = await _http_client.get_bytes(image_name)
    except Exception:
        logger.debug(f"曲绘下载失败，跳过: {image_name}")
        return None

    if _bytes_cache is not None:
        _bytes_cache.set(bytes_key, data, expire=30 * 24 * 3600)
    return data


async def _build_one_reference(game_code: str, song: SongData) -> JacketReference | None:
    image_name = getattr(song, "image_name", "") or ""
    if not image_name:
        return None

    cache_key = _cache_key_for_song(game_code, song)
    if _hash_cache is not None:
        cached = _hash_cache.get(cache_key, default=None)
        hash_value = _hash_from_cache_payload(cached)
        if hash_value is not None:
            return JacketReference(song.id, song.title, image_name, hash_value)

    image_bytes = await _load_image_bytes(image_name)
    if not image_bytes:
        return None

    try:
        image = _open_image(image_bytes)
        hash_value = _dhash(_center_square(image))
    except Exception:
        traceback.print_exc()
        logger.debug(f"曲绘 hash 构建失败，跳过: [{song.id}] {song.title}")
        return None

    if _hash_cache is not None:
        _hash_cache.set(cache_key, _hash_to_cache_payload(hash_value), expire=None)
    return JacketReference(song.id, song.title, image_name, hash_value)


async def _build_references(adapter: DomainAdapter) -> list[JacketReference]:
    songs = await adapter.load_all_songs()
    game_code = adapter.game_code
    semaphore = asyncio.Semaphore(_REMOTE_DOWNLOAD_CONCURRENCY)

    async def build(song: SongData) -> JacketReference | None:
        async with semaphore:
            return await _build_one_reference(game_code, song)

    refs = [ref for ref in await asyncio.gather(*(build(song) for song in songs.values())) if ref is not None]
    logger.info(f"[{game_code}] 曲绘识别参考库已加载: {len(refs)}/{len(songs)}")
    return refs


async def _get_references(adapter: DomainAdapter) -> list[JacketReference]:
    game_code = adapter.game_code
    cached = _reference_cache_by_game.get(game_code)
    if cached is not None:
        return cached

    lock = _build_locks.setdefault(game_code, asyncio.Lock())
    async with lock:
        cached = _reference_cache_by_game.get(game_code)
        if cached is not None:
            return cached
        refs = await _build_references(adapter)
        _reference_cache_by_game[game_code] = refs
        return refs


async def recognize_jacket(
    image_bytes: bytes,
    adapter: DomainAdapter,
    *,
    limit: int = 5,
) -> JacketRecognitionResult:
    """Recognize a song jacket from image bytes for a game adapter."""

    image = _open_image(image_bytes)
    refs = await _get_references(adapter)
    return rank_jacket_matches(image, refs, limit=limit)


async def recognize_maimai_jacket(image_bytes: bytes, *, limit: int = 5) -> JacketRecognitionResult:
    """Recognize a maimai song jacket from screenshot or cropped cover bytes."""

    from ...domains.maimai.maimai_adapter import get_maimai_adapter

    return await recognize_jacket(image_bytes, get_maimai_adapter(), limit=limit)


def clear_jacket_reference_cache() -> None:
    """Clear in-memory jacket references. Disk caches are preserved."""

    _reference_cache_by_game.clear()
