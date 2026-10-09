"""Bounded startup preparation and idle refresh of recently used covers."""

from __future__ import annotations

import asyncio
import re
import time
from pathlib import Path

from nonebot import logger

from . import html_render as rendering

_task: asyncio.Task[None] | None = None
_SHARED_TEMPLATES = Path(__file__).resolve().parents[1] / 'shared/render_templates'
_ASSETS = Path.cwd() / 'data/chiffon_bot/template'
_COMMON_URLS: list[str] = []
_INTERVAL = 30.0
_ACTIVE_SECONDS = 600.0
_WORK_SECONDS = 0.2
_BATCH_SIZE = 4

_WARM_IMAGES_JS = r"""async ({urls, budget, timeout, paint}) => {
  let timer;
  const decoded = [], failed = [], skipped = [];
  let pixels = 0;
  try { return await Promise.race([(async () => {
    await Promise.all(urls.map(async url => {
      if (!url.startsWith('file:')) { skipped.push(url); return; }
      const image = new Image();
      try {
        await new Promise((resolve, reject) => {
          image.onload = resolve; image.onerror = () => reject(new Error('Image load failed'));
          image.src = url;
        });
        const size = image.naturalWidth * image.naturalHeight * 4;
        if (!size || pixels + size > budget) { skipped.push(url); return; }
        pixels += size;
        await image.decode();
        decoded.push(url);
      } catch (error) { failed.push(url); }
    }));
    if (paint) await new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)));
    return {decoded, failed, skipped, pixels};
  })(), new Promise((resolve, reject) => {
    timer = setTimeout(() => reject(new Error('Warmup batch timed out')), timeout);
  })]); } finally { clearTimeout(timer); }
}"""
_FONT_FACES = (
    ('Inter', '100 900'), ('FOT-NewRodinPro', '500'), ('FOT-NewRodinPro', '600'),
    ('FOT-NewRodinPro', '700'), ('SourceHanSansCN', '250 900'), ('思源黑体', '700'), ('GenSenRounded2', '400'),
    ('GenSenRounded2', '700'), ('NotoSansJP', '100 900'), ('ヒラギノ角ゴ Pro W3', '300'),
)
_BACKGROUNDS = (
    ('maimai', 'bg_html/prism_plus/prism_plus.html', 1100, 800),
    ('chunithm', 'bg_html/X-VERSE-X/X-VERSE-X.html', 1100, 800),
    ('maimai', 'bg_html/prism_plus/prism_plus.html', 1280, 1744),
)


def _common_assets() -> list[str]:
    urls = dict.fromkeys(
        (_ASSETS / game / asset).resolve().as_uri()
        for game, name in (('maimai', 'b50.html'), ('maimai', 'song_info.html'), ('chunithm', 'chuni_song_info.html'))
        for asset in re.findall(r'assets/[A-Za-z0-9_./-]+\.(?:png|svg)',
            (_SHARED_TEMPLATES.parents[1] / 'domains' / game / 'template' / name).read_text(encoding='utf-8'))
        if (_ASSETS / game / asset).is_file()
        and (_ASSETS / game / asset).resolve().is_relative_to((_ASSETS / game).resolve())
    )
    return list(urls)[:16]


async def _warm_batch(urls: list[str], budget: int, *, paint: bool = False):
    pool = rendering._page_pool
    if pool is None or rendering._background_tasks:
        return None
    async with rendering._local_page(1, {}, _idle_only=True, _preserve_page=True) as page:
        if page is None:
            return None
        # Cancellation closes only this borrowed page, never a foreground page.
        async with asyncio.timeout(1):
            versions = await asyncio.to_thread(lambda: {rendering._version_image_uri(url): url for url in urls})
            result = await rendering._run_on_page(page, page.evaluate(_WARM_IMAGES_JS, {
                'urls': list(versions), 'budget': budget, 'timeout': 500, 'paint': paint,
            }))
        for key in ('decoded', 'failed', 'skipped'):
            result[key] = [versions[url] for url in result[key]]
        return result


async def _warm_images(urls: list[str], budget: int, deadline: float) -> int:
    global _COMMON_URLS
    count = 0
    for offset in range(0, len(urls), _BATCH_SIZE):
        if time.monotonic() >= deadline:
            break
        result = await _warm_batch(urls[offset:offset + _BATCH_SIZE], budget)
        if result is None:
            break
        budget -= result['pixels']
        count += len(result['decoded'])
        pool = rendering._page_pool
        if pool is not None:
            for url in result['decoded']:
                if url in pool.covers:
                    pool.covers[url].warmed = time.monotonic()
            for url in result['failed']:
                pool.covers.pop(url, None)
        _COMMON_URLS = [u for u in _COMMON_URLS if u not in result['failed']]
        if budget <= 0:
            break
        await asyncio.sleep(0)
    if count:
        await _warm_batch([], 0, paint=True)
    return count


async def _heartbeat() -> None:
    pool = rendering._page_pool
    now = time.monotonic()
    if (pool is None or not pool.last_used or now - pool.last_used > _ACTIVE_SECONDS
            or pool.waiters or pool.available.qsize() != len(pool.slots) or rendering._background_tasks):
        return
    # Prioritize entries not refreshed recently; warming does not change LRU order.
    eligible = sorted(((url, cover) for url, cover in pool.covers.items()
                       if now - cover.used <= _ACTIVE_SECONDS and now - cover.warmed >= _INTERVAL),
                      key=lambda item: (item[1].warmed, -item[1].used))
    urls, budget = [], 32 * 1024**2
    for url, cover in eligible:
        if cover.pixels <= budget:
            urls.append(url)
            budget -= cover.pixels
        if len(urls) == 50:
            break
    started = time.monotonic()
    deadline = started + _WORK_SECONDS
    count = await _warm_images(urls, 32 * 1024**2, deadline)
    common = await _warm_images(_COMMON_URLS, 8 * 1024**2, deadline)
    logger.debug(f'render_warmup: heartbeat covers={count} common={common} '
                 f'elapsed={(time.monotonic() - started) * 1000:.0f}ms lru={len(pool.covers)}')


async def _warm_fonts() -> None:
    async with rendering._local_page(1, {}, _idle_only=True, viewport={'width': 1100, 'height': 800}) as page:
        if page is None:
            logger.debug('render_warmup: 主页面忙，跳过字体预热')
            return
        # Use the live shared declarations, without another font filename map.
        template = rendering._template_environment((str(_SHARED_TEMPLATES),)).get_template('bg_template.html')
        html = await template.render_async(
            fonts_dir=(_SHARED_TEMPLATES / 'fonts').as_uri(),
            bg_image_url='data:image/svg+xml,%3Csvg%20xmlns=%22http://www.w3.org/2000/svg%22%20width=%221%22%20height=%221%22/%3E',
        )
        async def load():
            if not page.url.startswith('file:'):
                await page.goto(_ASSETS.as_uri())
            await page.set_content(html, wait_until='domcontentloaded')
            return await page.evaluate("""async specs => {
                const wanted = new Set(specs.map(s => s.join(':')));
                const failures = [];
                await Promise.all([...document.fonts].filter(f =>
                    wanted.has(f.family.replaceAll('"', '') + ':' + f.weight)).map(async f => {
                    try { await f.load(); }
                    catch (error) { failures.push(f.family + ':' + f.weight + ' (' + String(error) + ')'); }
                }));
                await document.fonts.ready;
                return failures;
            }""", _FONT_FACES)
        async with asyncio.timeout(30):
            failures = await rendering._run_on_page(page, load())
        if failures:
            logger.warning(f'render_warmup: 部分字体未预热，沿用字体回退: {failures}')


async def _warm_up() -> None:
    global _COMMON_URLS
    started = time.perf_counter()
    try:
        await _warm_fonts()
    except Exception as exc:
        logger.warning(f'render_warmup: 字体预热失败，继续按需加载: {exc}')
    try:
        _COMMON_URLS = await asyncio.to_thread(_common_assets)
        await _warm_images(_COMMON_URLS, 8 * 1024**2, time.monotonic() + _WORK_SECONDS)
    except Exception as exc:
        logger.debug(f'render_warmup: 跳过公共素材预热: {exc}')
    for game, source, width, height in _BACKGROUNDS:
        pool = rendering._page_pool
        if rendering._background_tasks or (pool is not None and pool.available.qsize() != len(pool.slots)):
            logger.debug('render_warmup: 渲染忙，跳过剩余背景预热')
            break
        try:
            await rendering._background_image_uri(_ASSETS / game, source, width, height)
        except Exception as exc:
            logger.warning(f'render_warmup: 背景预热失败，继续按需加载: {game} {source} ({exc})')
        await asyncio.sleep(0)
    logger.info(f'render_warmup: 有限后台预热完成，耗时 {time.perf_counter() - started:.3f}s')


async def _maintain() -> None:
    await _warm_up()
    while True:
        await asyncio.sleep(_INTERVAL)
        try:
            await _heartbeat()
        except Exception as exc:
            logger.debug(f'render_warmup: 跳过本次补热: {exc}')


def start_render_warmup() -> None:
    global _task
    if _task is not None and not _task.done():
        return
    _task = asyncio.create_task(_maintain(), name='chiffon-render-warmup')


async def stop_render_warmup() -> None:
    global _task
    task, _task = _task, None
    if task is not None:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
