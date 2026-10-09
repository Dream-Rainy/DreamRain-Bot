from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
from collections import OrderedDict
from collections.abc import Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from functools import lru_cache
from html import escape, unescape
from os import getcwd
from pathlib import Path
from threading import RLock
from typing import Any, Literal
from urllib.parse import urljoin, urlsplit
from urllib.request import url2pathname
from uuid import uuid4

import httpx
import jinja2
from nonebot import get_driver, get_plugin_config, logger, require

from ..config import Config


def _ensure_htmlrender_loaded() -> None:
    # 延迟加载，避免在“仅导入模块”时触发 NoneBot 初始化链
    require("nonebot_plugin_htmlrender")


def _get_new_page():
    _ensure_htmlrender_loaded()
    from nonebot_plugin_htmlrender.browser import get_new_page as _real_get_new_page

    return _real_get_new_page


async def _get_browser():
    _ensure_htmlrender_loaded()
    from nonebot_plugin_htmlrender.browser import get_browser

    return await get_browser()


_binary_client: httpx.AsyncClient | None = None
_binary_endpoint = ''
_binary_loop: Any = None
_binary_retry_at = 0.0
_BINARY_MARKER = re.compile(rb'chiffon-binary-v1:([a-f0-9]{32}):([0-9]{1,8})')


async def _screenshot(page: Any, **options) -> bytes:
    global _binary_client, _binary_endpoint, _binary_loop, _binary_retry_at
    endpoint = get_plugin_config(Config).htmlrender_binary_endpoint.rstrip('/')
    guid = getattr(getattr(page, '_impl_obj', None), '_guid', '')
    if not endpoint or not re.fullmatch(r'page@[a-f0-9]{32}', guid):
        return await page.screenshot(**options)
    loop = asyncio.get_running_loop()
    if _binary_client is None or _binary_endpoint != endpoint or _binary_loop is not loop:
        if _binary_client is not None:
            await _binary_client.aclose()
        # This client only uses its configured scheme and never follows redirects.
        # Plain HTTP needs no CA bundle; HTTPS retains certificate verification.
        _binary_client = httpx.AsyncClient(trust_env=False, verify=urlsplit(endpoint).scheme != 'http',
                                          limits=httpx.Limits(max_connections=4, max_keepalive_connections=4))
        _binary_endpoint, _binary_loop, _binary_retry_at = endpoint, loop, 0.0
        _register_render_shutdown()
    client = _binary_client
    token = uuid4().hex
    resource = endpoint + '/screenshots/' + token
    attempted = False
    timeout = options.get('timeout')
    deadline = time.monotonic() + timeout / 1000 if timeout and timeout > 0 else None

    def remaining(limit: float | None = None) -> float | None:
        seconds = deadline - time.monotonic() if deadline is not None else None
        if seconds is not None and seconds <= 0:
            raise TimeoutError('Screenshot delivery timed out')
        return min(seconds, limit) if seconds is not None and limit is not None else (limit if seconds is None else seconds)

    async def capture():
        current = dict(options)
        if deadline is not None:
            current['timeout'] = remaining() * 1000
        return await page.screenshot(**current)

    def unavailable(error: Exception) -> None:
        global _binary_retry_at
        if time.monotonic() >= _binary_retry_at:
            logger.warning(f'html_render: 二进制返回不可用，暂用标准协议: {type(error).__name__}')
        _binary_retry_at = time.monotonic() + 60

    try:
        if time.monotonic() >= _binary_retry_at:
            attempted = True
            try:
                async with asyncio.timeout(remaining(.5)):
                    response = await client.post(endpoint + '/screenshots', json={'id': token, 'page': guid}, timeout=remaining(.5))
                response.raise_for_status()
                if response.json() != {'protocol': 1, 'id': token}:
                    raise ValueError('Unexpected screenshot acknowledgement')
            except (httpx.HTTPError, ValueError, TimeoutError) as exc:
                unavailable(exc)
        image = await capture()
        marker = _BINARY_MARKER.fullmatch(image) if len(image) < 100 else None
        if marker is None:
            return image  # Local/old servers and memory-limit fallback return normal image bytes.
        try:
            if marker[1].decode() != token or not 0 < int(marker[2]) <= 16 * 1024**2:
                raise ValueError('Unexpected screenshot identity or size')
            size = int(marker[2])
            async with asyncio.timeout(remaining(1)):
                async with client.stream('GET', resource, timeout=remaining(1)) as response:
                    response.raise_for_status()
                    mime = 'image/jpeg' if options.get('type') == 'jpeg' else 'image/png'
                    if response.headers.get('content-type') != mime or response.headers.get('content-length') != str(size):
                        raise ValueError('Unexpected screenshot headers')
                    chunks = bytearray()
                    async for chunk in response.aiter_bytes():
                        if len(chunks) + len(chunk) > size:
                            raise ValueError('Screenshot too large')
                        chunks.extend(chunk)
                    image = bytes(chunks)
            signature = b'\xff\xd8\xff' if mime == 'image/jpeg' else b'\x89PNG\r\n\x1a\n'
            if len(image) != size or not image.startswith(signature):
                raise ValueError('Incomplete screenshot')
            return image
        except (httpx.HTTPError, ValueError, TimeoutError) as exc:
            unavailable(exc)
            # The arm is consumed by the first shot, so this cannot return its marker again.
            image = await capture()
            if _BINARY_MARKER.fullmatch(image):
                raise RuntimeError('Screenshot transfer remained armed') from exc
            return image
    finally:
        # Cancellation and lost arm replies must not reserve the next screenshot.
        budget = min(.2, max(0, deadline - time.monotonic())) if deadline is not None else .2
        if attempted and budget:
            try:
                async with asyncio.timeout(budget):
                    await client.delete(resource, timeout=budget)
            except (httpx.HTTPError, TimeoutError):
                pass  # The service's bounded TTL is the last-resort cleanup.


async def _run_on_page(page: Any, operation):
    task = asyncio.create_task(operation)
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        # Closing the context unblocks its protocol call. Consume that error
        # instead of cancelling Playwright's waiter and leaking its Future.
        try:
            await asyncio.shield(page.close())
        finally:
            await asyncio.gather(task, return_exceptions=True)
        raise


@dataclass(slots=True)
class _PageSlot:
    page: Any = None
    browser: Any = None
    options: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class _HotCover:
    pixels: int
    used: float
    warmed: float


class _PagePool:
    def __init__(self) -> None:
        self.loop = asyncio.get_running_loop()
        self.slots = [_PageSlot(), _PageSlot()]
        # Prefer the recently used page, which already has the font faces.
        self.available: asyncio.LifoQueue[_PageSlot] = asyncio.LifoQueue(2)
        for slot in self.slots:
            self.available.put_nowait(slot)
        self.waiters = 0
        self.last_used = 0.0
        self.covers: OrderedDict[str, _HotCover] = OrderedDict()

    def remember_covers(self, covers: list[dict[str, Any]]) -> None:
        now = time.monotonic()
        self.last_used = now
        for cover in covers:
            url, pixels = cover['url'], cover['pixels']
            if not url.startswith('file:') or '/jacket/' not in urlsplit(url).path or not 0 < pixels <= 32 * 1024**2:
                continue
            url = urlsplit(url)._replace(query='', fragment='').geturl()
            self.covers[url] = _HotCover(pixels, now, now)
            self.covers.move_to_end(url)
        # Metadata only; Chromium owns native decoded-image eviction.
        total = sum(c.pixels for c in self.covers.values())
        while len(self.covers) > 128 or total > 80 * 1024**2:
            _, old = self.covers.popitem(last=False)
            total -= old.pixels

    async def discard(self, slot: _PageSlot) -> None:
        page, slot.page = slot.page, None
        slot.browser = None
        slot.options = {}
        if page is not None:
            try:
                await page.close()
            except Exception:
                pass  # The old browser may already have disconnected.

    async def close(self) -> None:
        await asyncio.gather(*(self.discard(slot) for slot in self.slots))


_page_pool: _PagePool | None = None
_shutdown_driver: Any = None
_background_build_lock: asyncio.Lock | None = None
_background_build_loop: Any = None


def _register_render_shutdown() -> None:
    global _shutdown_driver
    driver = get_driver()
    if driver is not _shutdown_driver:
        driver.on_shutdown(_close_render_pages)
        _shutdown_driver = driver


async def _close_render_pages() -> None:
    global _page_pool, _binary_client, _binary_endpoint, _binary_loop, _binary_retry_at
    tasks = list(_background_tasks.values())
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    pool, _page_pool = _page_pool, None
    if pool is not None:
        await pool.close()
    client, _binary_client = _binary_client, None
    _binary_endpoint, _binary_loop, _binary_retry_at = '', None, 0.0
    if client is not None:
        await client.aclose()


@asynccontextmanager
async def _local_page(device_scale_factor: float, phases: dict[str, float], *,
                      _idle_only: bool = False, _preserve_page: bool = False, **options):
    global _page_pool
    if _page_pool is None or _page_pool.loop is not asyncio.get_running_loop():
        _page_pool = _PagePool()
    _register_render_shutdown()
    pool = _page_pool
    started = time.perf_counter()
    if _idle_only:
        # Warm one page only while all slots are free; never queue ahead of a
        # foreground renderer or take its last available page.
        if pool.waiters or pool.available.qsize() != len(pool.slots):
            yield None
            return
        slot = pool.available.get_nowait()
    else:
        pool.waiters += 1
        try:
            slot = await pool.available.get()
        finally:
            pool.waiters -= 1
    phases['queue'] = time.perf_counter() - started
    try:
        if _preserve_page:
            # Heartbeats borrow an existing document without reconnecting,
            # navigating, changing its viewport or creating a new context.
            if (slot.page is None or slot.page.is_closed() or slot.browser is None
                    or not slot.browser.is_connected()):
                yield None
            else:
                yield slot.page
            return
        started = time.perf_counter()
        browser = await _get_browser()
        # Viewport is changed on the borrowed page; all other context options
        # require a fresh context. Never hand one page to two renderers.
        viewport = options.pop('viewport', {'width': 500, 'height': 10})
        # Each document supplies its resource base via <base>. Keep the local
        # document URL to retain font faces when switching games.
        options.pop('base_url', None)
        context_options = {**options, 'device_scale_factor': device_scale_factor}
        if (slot.page is None or slot.page.is_closed() or slot.browser is not browser
                or slot.options != context_options):
            await pool.discard(slot)
            slot.page = await browser.new_page(viewport=viewport, **context_options)
            slot.browser, slot.options = browser, context_options
        elif slot.page.viewport_size != viewport:
            await slot.page.set_viewport_size(viewport)
        phases['page'] = time.perf_counter() - started
        yield slot.page
    except BaseException:
        # A cancelled set_content/screenshot may still be executing remotely.
        # Close that context before making the slot available again.
        await asyncio.shield(pool.discard(slot))
        raise
    finally:
        pool.available.put_nowait(slot)


@asynccontextmanager
async def _background_page(scale: float, phases: dict[str, float], width: int, height: int):
    global _background_build_lock, _background_build_loop
    loop = asyncio.get_running_loop()
    if _background_build_lock is None or _background_build_loop is not loop:
        _background_build_lock, _background_build_loop = asyncio.Lock(), loop
    _register_render_shutdown()
    started = time.perf_counter()
    # One temporary background page; never navigate a warm foreground page.
    async with _background_build_lock:
        phases['queue'] = time.perf_counter() - started
        started = time.perf_counter()
        browser = await _get_browser()
        page = await browser.new_page(device_scale_factor=scale, viewport={'width': width, 'height': height})
        phases['page'] = time.perf_counter() - started
        try:
            yield page
        finally:
            await asyncio.shield(page.close())


@lru_cache(maxsize=8)
def _template_environment(roots: tuple[str, ...]) -> jinja2.Environment:
    return jinja2.Environment(  # noqa: S701
        loader=jinja2.ChoiceLoader([jinja2.FileSystemLoader(root) for root in roots]),
        enable_async=True,
        auto_reload=True,
    )


_BACKGROUND_CACHE_DIR = Path(getcwd()) / 'data/chiffon_bot/render_backgrounds'
_BACKGROUND_LIMIT = 32
_background_epochs: dict[str, int] = {}
_background_entries: OrderedDict[str, dict[str, Any]] = OrderedDict()
_background_tasks: dict[str, asyncio.Task[str | None]] = {}
_background_lock = RLock()


def _file_path(uri: str) -> Path:
    parts = urlsplit(uri)
    path = url2pathname(parts.path)
    if parts.netloc and parts.netloc != 'localhost':
        path = f'//{parts.netloc}{path}'
    return Path(path)


def _epoch_path(root_uri: str) -> Path:
    return _BACKGROUND_CACHE_DIR / ('generation-' + hashlib.sha256(root_uri.encode()).hexdigest()[:16])


def _background_epoch(root_uri: str) -> int:
    with _background_lock:
        if root_uri not in _background_epochs:
            try:
                _background_epochs[root_uri] = int(_epoch_path(root_uri).read_text())
            except (OSError, ValueError):
                _background_epochs[root_uri] = 0
        return _background_epochs[root_uri]


def _clear_background_cache(asset_root: str | Path) -> None:
    root_uri = Path(asset_root).resolve().as_uri()
    with _background_lock:
        epoch = time.time_ns()
        _background_epochs[root_uri] = epoch
        _background_entries.clear()
        if _BACKGROUND_CACHE_DIR.exists():
            _epoch_path(root_uri).write_text(str(epoch))


def _resource_versions(paths: Sequence[str]) -> list[list[Any]]:
    versions = []
    for name in sorted(paths):
        stat = Path(name).stat()
        versions.append([name, stat.st_mtime_ns, stat.st_size])
    return versions


def _cached_background(key: str) -> str | None:
    with _background_lock:
        entry = _background_entries.get(key)
        if entry is None:
            try:
                entry = json.loads((_BACKGROUND_CACHE_DIR / f'{key}.json').read_text())
            except (OSError, ValueError):
                return None
        image = _BACKGROUND_CACHE_DIR / f'{key}.png'
        try:
            if not image.is_file() or entry['resources'] != _resource_versions([r[0] for r in entry['resources']]):
                _background_entries.pop(key, None)
                return None
        except (OSError, KeyError, TypeError, IndexError):
            return None
        _background_entries[key] = entry
        _background_entries.move_to_end(key)
        while len(_background_entries) > _BACKGROUND_LIMIT:
            _background_entries.popitem(last=False)
        return image.resolve().as_uri()


def _save_background(key: str, image: bytes, entry: dict[str, Any], root_uri: str, epoch: int) -> str | None:
    with _background_lock:
        if _background_epoch(root_uri) != epoch:
            return None
        _BACKGROUND_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _epoch_path(root_uri).write_text(str(epoch))
        image_path = _BACKGROUND_CACHE_DIR / f'{key}.png'
        manifest = image_path.with_suffix('.json')
        temporary = image_path.with_suffix(f'.{uuid4().hex}.tmp')
        try:
            temporary.write_bytes(image)
            temporary.replace(image_path)
            temporary.write_text(json.dumps(entry))
            temporary.replace(manifest)
        finally:
            temporary.unlink(missing_ok=True)
        # Bound persistent snapshots, including images left by an interrupted
        # write. Resident metadata never contains image bytes or song data.
        images = sorted(_BACKGROUND_CACHE_DIR.glob('*.png'), key=lambda p: p.stat().st_mtime_ns)
        for old in images[:-_BACKGROUND_LIMIT]:
            old.with_suffix('.json').unlink(missing_ok=True)
            old.unlink(missing_ok=True)
            _background_entries.pop(old.stem, None)
        _background_entries[key] = entry
        while len(_background_entries) > _BACKGROUND_LIMIT:
            _background_entries.popitem(last=False)
        return image_path.resolve().as_uri()


async def _build_background(key: str, root_uri: str, uri: str, width: int, height: int,
                            scale: float, epoch: int) -> str | None:
    started = time.perf_counter()
    try:
        source_version = await asyncio.to_thread(_resource_versions, [str(_file_path(uri))])
        resources = {str(_file_path(uri))}
        phases: dict[str, float] = {}
        async with _background_page(scale, phases, width, height) as page:
            failed_resources = []
            def on_request(request):
                if request.url.startswith('file:'):
                    resources.add(str(_file_path(request.url)))

            def on_failed(request):
                if request.resource_type in {'stylesheet', 'image'}:
                    failed_resources.append(request.url)

            page.on('request', on_request)
            page.on('requestfailed', on_failed)
            try:
                async def capture():
                    await page.goto(uri, wait_until='load')
                    await _wait_resources(page, strict=True, phases=phases)
                    if failed_resources:
                        raise RuntimeError(f'背景资源未加载: {failed_resources[:5]}')
                    await page.evaluate("""async () => {
                        document.getAnimations().forEach(a => { a.pause(); a.currentTime = 1000; });
                        await new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)));
                    }""")
                    return await _screenshot(page, type='png', full_page=False, timeout=30000)

                image = await _run_on_page(page, capture())
                versions = await asyncio.to_thread(_resource_versions, list(resources))
            finally:
                page.remove_listener('request', on_request)
                page.remove_listener('requestfailed', on_failed)
        if _background_epoch(root_uri) != epoch or source_version != [r for r in versions if r[0] == str(_file_path(uri))]:
            return None
        result = await asyncio.to_thread(_save_background, key, image, {'resources': versions}, root_uri, epoch)
        logger.debug(f'html_render: background_build={(time.perf_counter() - started) * 1000:.0f}ms '
                     + ' '.join(f'{k}={v * 1000:.0f}ms' for k, v in phases.items()))
        return result
    except Exception as exc:
        logger.warning(f'html_render: 背景快照失败，回退 iframe: {uri} ({exc})')
        return None


async def _background_image_uri(asset_root: str | Path, background: str, width: int,
                                height: int, scale: float = 1) -> str | None:
    started = time.perf_counter()
    if width <= 0 or height <= 0:
        return None
    root_uri = Path(asset_root).resolve().as_uri()
    uri = urljoin(root_uri.rstrip('/') + '/', background)
    if not uri.startswith('file:') or not await asyncio.to_thread(_file_path(uri).is_file):
        return None
    epoch = await asyncio.to_thread(_background_epoch, root_uri)
    key = hashlib.sha256(json.dumps(['bg-v1', uri, width, height, scale, epoch]).encode()).hexdigest()
    cached = await asyncio.to_thread(_cached_background, key)
    if cached is not None:
        logger.debug(f'html_render: background_hit={(time.perf_counter() - started) * 1000:.0f}ms size={width}x{height}')
        return cached
    task = _background_tasks.get(key)
    if task is None:
        task = asyncio.create_task(_build_background(key, root_uri, uri, width, height, scale, epoch))
        _background_tasks[key] = task

        def done(completed):
            if _background_tasks.get(key) is completed:
                _background_tasks.pop(key, None)
            if not completed.cancelled():
                completed.exception()

        task.add_done_callback(done)
    # One cancelled requester must not cancel a build needed by another one.
    result = await asyncio.shield(task)
    logger.debug(f'html_render: background_miss={(time.perf_counter() - started) * 1000:.0f}ms size={width}x{height}')
    return result


# 与 bg_template.html 中注入的 window.__BG_IFRAME_READY__ 对齐；未定义则视为无需等待（非该模板的 HTML）
_RENDER_READY_JS = """() => {
  if (typeof window.__BG_IFRAME_READY__ === 'undefined') return true;
  return window.__BG_IFRAME_READY__ === true;
}"""


_RESOURCES_READY_JS = r"""async ({strict, timeout}) => {
  let timer;
  try { return await Promise.race([(async () => {
  await document.fonts.ready;
  const covers = new Map();
  const remember = image => {
    if (image.src.startsWith('file:') && new URL(image.src).pathname.includes('/jacket/'))
      covers.set(image.src, {url:image.src, pixels:image.naturalWidth*image.naturalHeight*4});
  };
  const decode = async image => {
    try { await image.decode(); } catch (e) {
      if (strict || image.matches('.song-jacket, .bg-container > img') ||
          (document.getElementById('chiffon-cover-gate') && new URL(image.src).pathname.includes('/jacket/'))) throw e;
    }
  };
  await Promise.all([...document.images].map(async image => { await decode(image); if (image.matches('.song-jacket')) remember(image); }));
  const urls = new Set();
  for (const element of document.querySelectorAll('*')) {
    for (const pseudo of [null, '::before', '::after']) {
      const style = getComputedStyle(element, pseudo);
      for (const key of ['backgroundImage', 'maskImage', 'borderImageSource']) {
        for (const match of style[key].matchAll(/url\(["']?([^"')]+)["']?\)/g)) urls.add(match[1]);
      }
    }
  }
  await Promise.all([...urls].map(async url => { const image = new Image(); image.src = url; await decode(image); remember(image); }));
  // Song-table row heights are measured by existing load handlers. Re-run
  // them with the final font metrics, then wait for those styles to paint.
  if (typeof window.__BG_IFRAME_READY__ !== 'undefined') window.dispatchEvent(new Event('load'));
  document.getElementById('chiffon-cover-gate')?.remove();
  await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
  return [...covers.values()];
  })(), new Promise((resolve, reject) => {
    timer = setTimeout(() => reject(new Error('Resource decode timed out')), timeout);
  })]); } finally { clearTimeout(timer); }
}"""


async def _wait_resources(page: Any, *, strict: bool = False, timeout: float = 25000,
                          phases: dict[str, float] | None = None) -> list[dict[str, Any]]:
    deadline = time.perf_counter() + timeout / 1000
    remaining = lambda: max(1, (deadline - time.perf_counter()) * 1000)
    started = time.perf_counter()
    await page.wait_for_load_state('load', timeout=remaining())
    iframe = await page.query_selector('.bg-container iframe')
    if iframe is not None:
        frame = await iframe.content_frame()
        source = await iframe.evaluate('(element) => element.src')
        if frame is not None and source:
            await frame.wait_for_url(source, wait_until='load', timeout=remaining())
    await page.wait_for_function(_RENDER_READY_JS, timeout=remaining())
    if await page.evaluate('() => window.__BG_IFRAME_ERROR__ === true'):
        raise RuntimeError('背景载入失败')
    if phases is not None:
        phases['load'] = time.perf_counter() - started
    started = time.perf_counter()
    for frame in page.frames:
        await frame.evaluate("""async timeout => {
            let timer;
            try { await Promise.race([document.fonts.ready, new Promise((resolve, reject) => {
                timer = setTimeout(() => reject(new Error('Font load timed out')), timeout);
            })]); } finally { clearTimeout(timer); }
        }""", remaining())
    if phases is not None:
        phases['fonts'] = time.perf_counter() - started
    started = time.perf_counter()
    covers = []
    for frame in page.frames:
        await frame.wait_for_load_state('load', timeout=remaining())
        result = await frame.evaluate(_RESOURCES_READY_JS, {'strict': strict or frame != page.main_frame,
                                                           'timeout': remaining()})
        if frame == page.main_frame and isinstance(result, list):
            covers = result
    if phases is not None:
        phases['decode_paint'] = time.perf_counter() - started
    return covers


def _default_ready_timeout_ms(screenshot_timeout: float | None) -> float:
    cap = 25_000.0
    if screenshot_timeout is None:
        return cap
    return min(cap, float(screenshot_timeout))


def _attach_pending_request_tracker(page: Any):
    """Track this render's requests and detach handlers before reusing its page."""
    pending: dict[str, str] = {}

    def on_request(request: Any) -> None:
        pending[request.url] = getattr(request, "resource_type", "?")

    def on_done(request: Any) -> None:
        pending.pop(request.url, None)

    page.on("request", on_request)
    page.on("requestfinished", on_done)
    page.on("requestfailed", on_done)
    def detach() -> None:
        page.remove_listener('request', on_request)
        page.remove_listener('requestfinished', on_done)
        page.remove_listener('requestfailed', on_done)

    return pending, detach


@asynccontextmanager
async def _render_events(page: Any, debug: bool):
    pending, detach = _attach_pending_request_tracker(page)

    def console(message):
        logger.debug(f'浏览器控制台: {message.text}')

    def failed(request):
        logger.debug(f'请求失败: {request.url} {request.failure}')

    if debug:
        page.on('console', console)
        page.on('requestfailed', failed)
    try:
        yield pending
    finally:
        detach()
        if debug:
            page.remove_listener('console', console)
            page.remove_listener('requestfailed', failed)


def _log_pending_requests(prefix: str, pending: dict[str, str], limit: int = 30) -> None:
    if not pending:
        logger.warning(f"{prefix} 当前无 pending 请求记录（或已全部结束）")
        return
    items = list(pending.items())[:limit]
    logger.warning(f"{prefix} 未完成请求（最多 {limit} 条）: {items}")



def _with_resource_base(html: str, uri: str) -> str:
    if re.search(r'<base\b[^>]*\bhref\s*=', html, re.IGNORECASE):
        return html
    base = '<base href="' + escape(uri.rstrip('/') + '/', quote=True) + '">'
    head = re.search(r'<head\b[^>]*>', html, re.IGNORECASE)
    if head is not None:
        return html[:head.end()] + base + html[head.end():]
    return base + html


def _version_image_uri(uri: str) -> str:
    parts = urlsplit(uri)
    if parts.scheme != 'file' or Path(parts.path).suffix.lower() not in {'.png', '.jpg', '.jpeg', '.svg', '.webp', '.gif', '.avif', '.bmp'}:
        return uri
    try:
        _, modified, size = _resource_versions([str(_file_path(uri))])[0]
    except OSError:
        return uri  # Required-resource checks handle missing files.
    return parts._replace(query=f'_chiffon_v={modified}-{size}').geturl()


def _version_local_images(html: str, base: str) -> str:
    declared = re.search(r'<base\b[^>]*\bhref\s*=\s*["\']([^"\']+)', html, re.IGNORECASE)
    if declared:
        base = unescape(declared[1])
    versions = {}
    def replace(match):
        uri = match['uri']
        if uri not in versions:
            absolute = urljoin(base.rstrip('/') + '/', unescape(uri))
            version = _version_image_uri(absolute)
            versions[uri] = (urlsplit(uri)._replace(query=urlsplit(version).query).geturl()
                             if version != absolute else uri)
        return match['lead'] + match['quote'] + versions[uri] + match['quote']
    return re.sub(r'(?P<lead>\b(?:(?:src|href)\s*=\s*|url\(\s*))(?P<quote>["\'])(?P<uri>[^"\']+)(?P=quote)',
                  replace, html, flags=re.IGNORECASE)


async def html_to_pic(
    html: str,
    wait: int = 0,
    debug: bool = False,
    template_path: str = f"file://{getcwd()}",  # noqa: PTH109
    type: Literal["jpeg", "png"] = "png",  # noqa: A002
    quality: int | None = None,
    device_scale_factor: float = 2,
    screenshot_timeout: float | None = 30_000,
    wait_until: Literal["load", "domcontentloaded", "networkidle"] = "domcontentloaded",
    render_ready_timeout_ms: float | None = None,
    fallback_networkidle_on_ready_timeout: bool = True,
    log_render_phases: bool = True,
    **kwargs,
) -> bytes:
    """html转图片

    Args:
        screenshot_timeout (float, optional): 截图超时时间，默认30000ms
        html (str): html文本
        wait (int, optional): 等待时间. Defaults to 0.
        template_path (str, optional): 模板路径 如 "file:///path/to/template/"
        type (Literal["jpeg", "png"]): 图片类型, 默认 png
        quality (int | None, optional): 图片质量 0-100 当为`png`时无效
        device_scale_factor: 缩放比例,类型为float,值越大越清晰(真正想让图片清晰更优先请调整此选项)
        wait_until: 传给 ``set_content`` 的首次导航条件；就绪等待失败时可降级为 ``networkidle``。
        render_ready_timeout_ms: 等待 ``bg_template`` 中 ``__BG_IFRAME_READY__`` 的超时（毫秒）；默认取
            ``min(25000, screenshot_timeout)``。
        fallback_networkidle_on_ready_timeout: 就绪超时时是否再执行一次 ``set_content(..., networkidle)``。
        log_render_phases: 是否记录各阶段耗时（debug）；超时或降级时打 warning。
        **kwargs: 传入 page 的参数

    Returns:
        bytes: 图片, 可直接发送
    """

    if "file:" not in template_path:
        raise Exception("template_path 应该为 file:///path/to/template")

    ready_timeout = (
        float(render_ready_timeout_ms)
        if render_ready_timeout_ms is not None
        else _default_ready_timeout_ms(screenshot_timeout)
    )

    phases: dict[str, float] = {}
    t0 = time.perf_counter()
    reuse_page = kwargs.pop('_reuse_page', False)
    if reuse_page:
        html = _with_resource_base(html, template_path)
        # Stable file versions retain decode reuse while allowing hot updates.
        html = await asyncio.to_thread(_version_local_images, html, template_path)
        phases['assets'] = time.perf_counter() - t0
    manager = (_local_page(device_scale_factor, phases, **kwargs) if reuse_page
               else _get_new_page()(device_scale_factor, **kwargs))
    async with manager as page:
        if not reuse_page:
            phases['page'] = time.perf_counter() - t0
        async def capture():
            async with _render_events(page, debug) as pending:
                t_a = time.perf_counter()
                if not reuse_page or not page.url.startswith('file:'):
                    await page.goto(template_path)
                t_goto = time.perf_counter() - t_a

                t_b = time.perf_counter()
                await page.set_content(html, wait_until=wait_until)
                t_set = time.perf_counter() - t_b

                t_c = time.perf_counter()
                t_fallback = 0.0
                used_fallback = False
                try:
                    covers = await _wait_resources(page, timeout=ready_timeout, phases=phases)
                except Exception as exc:
                    if page.is_closed():
                        raise
                    if log_render_phases:
                        logger.warning(f'html_render: 资源就绪等待失败 ({ready_timeout:.0f}ms): {exc}')
                        _log_pending_requests('html_render[ready]', pending)
                    if not fallback_networkidle_on_ready_timeout:
                        raise
                    used_fallback = True
                    t_fb0 = time.perf_counter()
                    await page.set_content(html, wait_until='networkidle')
                    covers = await _wait_resources(page, timeout=min(15_000.0, ready_timeout), phases=phases)
                    t_fallback = time.perf_counter() - t_fb0
                t_ready = time.perf_counter() - t_c

                if wait:
                    await page.wait_for_timeout(wait)
                if debug:
                    print(await page.content())

                t_d = time.perf_counter()
                shot = await _screenshot(page,
                    full_page=False,
                    type=type,
                    quality=quality,
                    timeout=screenshot_timeout,
                )
                t_shot = time.perf_counter() - t_d
            phases.update(goto=t_goto, set_content=t_set, ready=t_ready,
                          fallback=t_fallback, screenshot=t_shot)
            return shot, used_fallback, covers

        shot, used_fallback, covers = await _run_on_page(page, capture())
        if reuse_page and _page_pool is not None:
            _page_pool.remember_covers(covers or [])
        released = time.perf_counter()

    phases.update(release=time.perf_counter() - released, total=time.perf_counter() - t0)
    if log_render_phases:
        logger.debug('html_render: ' + ' '.join(f'{k}={v * 1000:.0f}ms' for k, v in phases.items())
                     + f' reused={reuse_page} fallback_used={used_fallback}')
    return shot


def _normalize_template_roots(template_path: str | Sequence[str]) -> list[Path]:
    if isinstance(template_path, str):
        return [Path(template_path).resolve()]
    return [Path(p).resolve() for p in template_path]


async def template_to_pic(
    template_path: str | Sequence[str],
    template_name: str,
    templates: dict[Any, Any],
    debug: bool = False,
    filters: dict[str, Any] | None = None,
    pages: dict[Any, Any] | None = None,
    wait: int = 0,
    type: Literal["jpeg", "png"] = "png",  # noqa: A002
    quality: int | None = None,
    device_scale_factor: float = 2,
    screenshot_timeout: float | None = 30_000,
    wait_until: Literal["load", "domcontentloaded", "networkidle"] = "domcontentloaded",
    render_ready_timeout_ms: float | None = None,
    fallback_networkidle_on_ready_timeout: bool = True,
    log_render_phases: bool = True,
) -> bytes:
    """使用jinja2模板引擎通过html生成图片

    Args:
        screenshot_timeout (float, optional): 截图超时时间，默认30000ms
        template_path: 单个模板根目录，或多个根目录列表（Jinja ChoiceLoader 按顺序查找）。
            第一个目录用作资源解析的默认 ``base_url``，除非 ``pages["base_url"]`` 已指定 file URI。
            复用页面保留文档 URL，通过 HTML base 元素切换资源目录。
        template_name (str): 模板名
        templates (Dict[Any, Any]): 模板内参数 如: {"name": "abc"}
        filters (Optional[Dict[str, Any]]): 自定义过滤器
        pages (Optional[Dict[Any, Any]]): 网页参数 Defaults to
            {"base_url": 首目录 file URI, "viewport": {"width": 500, "height": 10}}
        wait (int, optional): 网页载入等待时间. Defaults to 0.
        type (Literal["jpeg", "png"]): 图片类型, 默认 png
        quality (int | None, optional): 图片质量 0-100 当为`png`时无效
        device_scale_factor: 缩放比例,类型为float,值越大越清晰(真正想让图片清晰更优先请调整此选项)
        render_ready_timeout_ms / fallback_networkidle_on_ready_timeout / log_render_phases:
            见 ``html_to_pic``。
    Returns:
        bytes: 图片 可直接发送
    """

    roots = _normalize_template_roots(template_path)
    asset_root_uri = roots[0].as_uri()

    if pages is None:
        pages = {
            "viewport": {"width": 500, "height": 10},
            "base_url": asset_root_uri,
        }
    else:
        pages = dict(pages)
        pages.setdefault("base_url", asset_root_uri)

    goto_uri = pages["base_url"]
    if not str(goto_uri).startswith("file:"):
        goto_uri = Path(str(goto_uri)).resolve().as_uri()

    started = time.perf_counter()
    template_env = _template_environment(tuple(str(root) for root in roots))
    if filters:
        # Custom filters are rare here. Give them their own environment rather
        # than mutating the shared filter dictionary (overlay shares it too).
        template_env = jinja2.Environment(loader=template_env.loader, enable_async=True)
        template_env.filters.update(filters)

    template = template_env.get_template(template_name)
    html = await template.render_async(**templates)
    if log_render_phases:
        logger.debug(f'html_render: jinja={(time.perf_counter() - started) * 1000:.0f}ms template={template_name}')

    return await html_to_pic(
        template_path=goto_uri,
        html=html,
        wait=wait,
        type=type,
        quality=quality,
        debug=debug,
        wait_until=wait_until,
        device_scale_factor=device_scale_factor,
        screenshot_timeout=screenshot_timeout,
        render_ready_timeout_ms=render_ready_timeout_ms,
        fallback_networkidle_on_ready_timeout=fallback_networkidle_on_ready_timeout,
        log_render_phases=log_render_phases,
        _reuse_page=True,
        **pages,
    )
