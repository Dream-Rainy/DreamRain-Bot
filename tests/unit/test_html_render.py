from __future__ import annotations

import asyncio
import json
from collections import OrderedDict

import pytest
import pytest_asyncio


class Page:
    def __init__(self, viewport):
        self.viewport_size = viewport
        self.url = 'about:blank'
        self.html = ''
        self.closed = False
        self.close_event = asyncio.Event()
        self.listeners = {}

    def is_closed(self):
        return self.closed

    def on(self, event, callback):
        self.listeners.setdefault(event, []).append(callback)

    def remove_listener(self, event, callback):
        self.listeners[event].remove(callback)

    async def goto(self, url, **options):
        self.url = url

    async def set_viewport_size(self, viewport):
        self.viewport_size = viewport

    async def set_content(self, html, **options):
        self.html = html
        await asyncio.sleep(0)
        if html.endswith('failed'):
            raise RuntimeError('content failed')

    async def screenshot(self, **options):
        await asyncio.sleep(0)
        return json.dumps([self.html, self.viewport_size]).encode()

    async def close(self):
        self.closed = True
        self.close_event.set()


class Browser:
    def __init__(self):
        self.pages = []

    def is_connected(self):
        return True

    async def new_page(self, *, viewport, **options):
        page = Page(viewport)
        self.pages.append(page)
        return page


@pytest_asyncio.fixture
async def render_module(loaded_chiffon_bot, monkeypatch, tmp_path):
    from src.plugins.chiffon_bot.infra import html_render

    monkeypatch.setattr(html_render, '_page_pool', None)
    monkeypatch.setattr(html_render, '_background_tasks', {})
    monkeypatch.setattr(html_render, '_background_entries', OrderedDict())
    monkeypatch.setattr(html_render, '_background_epochs', {})
    monkeypatch.setattr(html_render, '_BACKGROUND_CACHE_DIR', tmp_path / 'cache')
    html_render._template_environment.cache_clear()
    try:
        yield html_render
    finally:
        await html_render._close_render_pages()
        html_render._template_environment.cache_clear()


async def test_concurrent_contents_and_sizes_survive_failure_and_cancellation(render_module, monkeypatch, tmp_path):
    browser = Browser()
    cancelled_entered = asyncio.Event()

    async def get_browser():
        return browser

    async def ready(page, **options):
        if page.html.endswith('cancelled'):
            cancelled_entered.set()
            await page.close_event.wait()
            raise RuntimeError('page closed')

    monkeypatch.setattr(render_module, '_get_browser', get_browser)
    monkeypatch.setattr(render_module, '_wait_resources', ready)

    async def render(text, height):
        result = json.loads(await render_module.html_to_pic(
            text, template_path=tmp_path.as_uri(), device_scale_factor=1,
            viewport={'width': 120, 'height': height}, _reuse_page=True,
        ))
        return [result[0].split('>', 1)[1], result[1]]

    first, second = await asyncio.gather(render('first', 100), render('second', 200))
    assert first == ['first', {'width': 120, 'height': 100}]
    assert second == ['second', {'width': 120, 'height': 200}]
    with pytest.raises(RuntimeError, match='content failed'):
        await render('failed', 300)

    cancelled = asyncio.create_task(render('cancelled', 400))
    await asyncio.wait_for(cancelled_entered.wait(), 1)
    cancelled.cancel()
    with pytest.raises(asyncio.CancelledError):
        await cancelled
    after = await asyncio.wait_for(asyncio.gather(render('after', 500), render('again', 600)), 1)
    assert after == [['after', {'width': 120, 'height': 500}], ['again', {'width': 120, 'height': 600}]]
    assert all(not callbacks for page in browser.pages for callbacks in page.listeners.values())


async def test_switching_resources_and_building_background_keep_foreground_page(render_module, monkeypatch, tmp_path):
    browser = Browser()
    entered, release = asyncio.Event(), asyncio.Event()

    async def get_browser():
        return browser

    async def ready(page, **options):
        if page.url.endswith('bg.html'):
            entered.set()
            await release.wait()
            raise RuntimeError('broken background')

    monkeypatch.setattr(render_module, '_get_browser', get_browser)
    monkeypatch.setattr(render_module, '_wait_resources', ready)
    source = tmp_path / 'bg.html'
    source.write_text('background')
    html = '<html><head></head><body><img src="jacket.png"></body></html>'

    async def render(root):
        return json.loads(await render_module.html_to_pic(html, template_path=root.as_uri(),
            device_scale_factor=1, viewport={'width': 120, 'height': 80}, _reuse_page=True))[0]

    first = await render(tmp_path / 'maimai')
    main = browser.pages[0]
    background = asyncio.create_task(render_module._background_image_uri(tmp_path, 'bg.html', 120, 80))
    await asyncio.wait_for(entered.wait(), 1)
    second = await asyncio.wait_for(render(tmp_path / 'chunithm'), 1)
    assert f'<base href="{(tmp_path / "maimai").as_uri()}/">' in first
    assert f'<base href="{(tmp_path / "chunithm").as_uri()}/">' in second
    assert main.url == (tmp_path / 'maimai').as_uri()
    assert not main.closed
    release.set()
    assert await background is None
    assert browser.pages[1].closed
    assert not main.closed

    # Cancel another background build: only its temporary page is discarded.
    entered.clear()
    async def cancelled_ready(page, **options):
        entered.set()
        await page.close_event.wait()
        raise RuntimeError('page closed')
    monkeypatch.setattr(render_module, '_wait_resources', cancelled_ready)
    pending = asyncio.create_task(render_module._background_image_uri(tmp_path, 'bg.html', 120, 80))
    await asyncio.wait_for(entered.wait(), 1)
    build = next(iter(render_module._background_tasks.values()))
    build.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
    assert browser.pages[2].closed and not main.closed


async def test_iframe_wait_uses_resolved_source_with_stable_document_url(render_module):
    from types import SimpleNamespace
    resolved = 'file:///chunithm/bg_html/bg.html'
    waited = []

    class Frame:
        async def wait_for_url(self, source, **options):
            waited.append(source)
        async def wait_for_load_state(self, *args, **options):
            pass
        async def evaluate(self, *args):
            return False

    frame = Frame()
    class Iframe:
        async def content_frame(self):
            return frame
        async def evaluate(self, expression):
            return resolved

    class Document(Frame):
        async def query_selector(self, selector):
            return Iframe()
        async def wait_for_function(self, *args, **options):
            pass

    page = Document()
    page.url = 'file:///maimai/'
    page.main_frame = SimpleNamespace()
    page.frames = [frame]
    await render_module._wait_resources(page)
    assert waited == [resolved]


async def test_template_updates_and_custom_filters_remain_isolated(render_module, monkeypatch, tmp_path):
    template = tmp_path / 'test.html'
    template.write_text('{{ text | upper }}', encoding='utf-8')

    async def capture(*, html, **options):
        return html.encode()

    monkeypatch.setattr(render_module, 'html_to_pic', capture)

    async def render(**options):
        return await render_module.template_to_pic(str(tmp_path), 'test.html', {'text': 'hello'}, **options)

    assert await render() == b'HELLO'
    assert await render(filters={'upper': lambda value: 'custom'}) == b'custom'
    assert await render() == b'HELLO'
    template.write_text('updated: {{ text }}', encoding='utf-8')
    assert await render() == b'updated: hello'


async def test_background_dependency_changes_and_failed_builds_do_not_stick(render_module, monkeypatch, tmp_path):
    source = tmp_path / 'bg.html'
    source.write_text('<link href="bg.css">', encoding='utf-8')
    css = tmp_path / 'bg.css'

    async def build(key, root, uri, width, height, scale, epoch):
        if not css.exists():
            return None
        contents = css.read_bytes()
        return render_module._save_background(key, contents, {
            'resources': render_module._resource_versions([str(source), str(css)])
        }, root, epoch)

    monkeypatch.setattr(render_module, '_build_background', build)

    async def background(height=80):
        return await render_module._background_image_uri(tmp_path, 'bg.html', 120, height)

    assert await background() is None
    css.write_text('first', encoding='utf-8')
    uri = await background()
    assert render_module._file_path(uri).read_bytes() == b'first'
    css.write_text('changed decoration', encoding='utf-8')
    assert render_module._file_path(await background()).read_bytes() == b'changed decoration'
    assert await background(160) != uri
    css.unlink()
    assert await background() is None


async def test_clearing_background_during_build_cannot_publish_stale_snapshot(render_module, monkeypatch, tmp_path):
    source = tmp_path / 'bg.html'
    source.write_text('background', encoding='utf-8')
    entered, release = asyncio.Event(), asyncio.Event()

    async def build(key, root, uri, width, height, scale, epoch):
        entered.set()
        await release.wait()
        return render_module._save_background(key, b'complete background', {
            'resources': render_module._resource_versions([str(source)])
        }, root, epoch)

    monkeypatch.setattr(render_module, '_build_background', build)
    pending = asyncio.create_task(render_module._background_image_uri(tmp_path, 'bg.html', 120, 80))
    await asyncio.wait_for(entered.wait(), 1)
    render_module._clear_background_cache(tmp_path)
    release.set()
    assert await pending is None
    uri = await render_module._background_image_uri(tmp_path, 'bg.html', 120, 80)
    assert render_module._file_path(uri).read_bytes() == b'complete background'


async def test_cover_lru_keeps_recent_b50s_with_count_and_pixel_bounds(render_module):
    pool = render_module._PagePool()
    def cover(index, pixels=400 * 400 * 4):
        return {'url': f'file:///assets/maimai/jacket/{index}.png', 'pixels': pixels}

    for start in (0, 50, 100):
        pool.remember_covers([cover(i) for i in range(start, start + 50)])
    assert len(pool.covers) == 128 and cover(21)['url'] not in pool.covers
    pool.remember_covers([cover(22)])
    pool.remember_covers([cover(i) for i in range(150, 160)])
    assert cover(22)['url'] in pool.covers and cover(23)['url'] not in pool.covers

    pool.remember_covers([cover(i, 1024 * 1024 * 4) for i in range(200, 250)])
    assert sum(c.pixels for c in pool.covers.values()) <= 80 * 1024**2
    assert len(pool.covers) < 128
    keys = list(pool.covers)
    pool.remember_covers([{'url': 'https://example.org/jacket/a.png', 'pixels': 100}, cover(999, 0), cover(999, 33 * 1024**2)])
    assert list(pool.covers) == keys


async def test_reused_page_reloads_changed_material_but_keeps_stable_urls(render_module, monkeypatch, tmp_path):
    browser = Browser()
    async def get_browser():
        return browser
    async def ready(page, **options):
        pass
    monkeypatch.setattr(render_module, '_get_browser', get_browser)
    monkeypatch.setattr(render_module, '_wait_resources', ready)
    jacket = tmp_path / 'jacket' / 'cover.png'
    jacket.parent.mkdir()
    jacket.write_bytes(b'first')
    html = '<img src="jacket/cover.png"><style>.cover{background-image:url("jacket/cover.png")}</style><svg><image href="jacket/cover.png"/></svg><img src="https://example.org/a.png?q=1&amp;x=2">'
    async def render():
        return await render_module.html_to_pic(html, template_path=tmp_path.as_uri(), _reuse_page=True)
    first = await render()
    assert await render() == first
    jacket.write_bytes(b'updated material')
    changed = await render()
    assert changed != first and await render() == changed
    from urllib.parse import urlsplit
    import re
    assert len({urlsplit(url).query for url in re.findall(r'jacket/cover.png[^"\']*', json.loads(changed)[0])}) == 1
    assert 'https://example.org/a.png?q=1&amp;x=2' in json.loads(changed)[0]
    assert len(browser.pages) == 1


async def test_binary_delivery_lost_arm_reply_and_truncation_fallback(render_module, monkeypatch):
    from types import SimpleNamespace
    import httpx
    image = b'\x89PNG\r\n\x1a\ncomplete image'
    token = None
    calls = []
    mode = 'lost_arm'
    class RemotePage:
        _impl_obj = SimpleNamespace(_guid='page@' + 'a' * 32)
        shots = 0
        async def screenshot(self, **options):
            self.shots += 1
            return (f'chiffon-binary-v1:{token}:{len(image)}'.encode()
                    if self.shots == 1 else image)
    async def exchange(request):
        nonlocal token
        calls.append(request.method)
        if request.method == 'POST':
            token = json.loads(request.content)['id']
            if mode == 'lost_arm':
                raise httpx.ReadTimeout('reply lost', request=request)
            return httpx.Response(201, json={'protocol': 1, 'id': token})
        if request.method == 'GET':
            return httpx.Response(200, headers={'Content-Type': 'image/png', 'Content-Length': str(len(image))},
                                  content=image if mode == 'lost_arm' else image[:-1])
        return httpx.Response(204)
    monkeypatch.setattr(render_module, 'get_plugin_config', lambda _: SimpleNamespace(htmlrender_binary_endpoint='http://binary'))
    client = httpx.AsyncClient(transport=httpx.MockTransport(exchange))
    monkeypatch.setattr(render_module, '_binary_client', client)
    monkeypatch.setattr(render_module, '_binary_endpoint', 'http://binary')
    monkeypatch.setattr(render_module, '_binary_loop', asyncio.get_running_loop())
    monkeypatch.setattr(render_module, '_binary_retry_at', 0)
    page = RemotePage()
    assert await render_module._screenshot(page, type='png', timeout=1000) == image
    assert page.shots == 1 and calls == ['POST', 'GET', 'DELETE']
    mode, calls = 'truncated', []
    render_module._binary_retry_at = 0
    page = RemotePage()
    assert await render_module._screenshot(page, type='png', timeout=1000) == image
    assert page.shots == 2 and calls == ['POST', 'GET', 'DELETE']
    calls.clear()
    page.shots = 2
    assert await render_module._screenshot(page, type='png', timeout=1000) == image
    assert calls == []  # Cooldown does not pay failed arm/delete calls every time.


async def test_binary_delivery_cancellation_deletes_job_and_deadline_bounds_fetch(render_module, monkeypatch):
    from types import SimpleNamespace
    import httpx
    entered = asyncio.Event()
    token = None
    deleted = []
    class RemotePage:
        _impl_obj = SimpleNamespace(_guid='page@' + 'b' * 32)
        async def screenshot(self, **options):
            return f'chiffon-binary-v1:{token}:20'.encode()
    async def exchange(request):
        nonlocal token
        if request.method == 'POST':
            token = json.loads(request.content)['id']
            return httpx.Response(201, json={'protocol': 1, 'id': token})
        if request.method == 'GET':
            entered.set()
            await asyncio.sleep(10)
        deleted.append(request.url.path)
        return httpx.Response(204)
    monkeypatch.setattr(render_module, 'get_plugin_config', lambda _: SimpleNamespace(htmlrender_binary_endpoint='http://binary'))
    client = httpx.AsyncClient(transport=httpx.MockTransport(exchange))
    monkeypatch.setattr(render_module, '_binary_client', client)
    monkeypatch.setattr(render_module, '_binary_endpoint', 'http://binary')
    monkeypatch.setattr(render_module, '_binary_loop', asyncio.get_running_loop())
    monkeypatch.setattr(render_module, '_binary_retry_at', 0)
    pending = asyncio.create_task(render_module._screenshot(RemotePage(), type='png', timeout=1000))
    await asyncio.wait_for(entered.wait(), 1)
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
    assert deleted == ['/screenshots/' + token]
    render_module._binary_retry_at = 0
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(render_module._screenshot(RemotePage(), type='png', timeout=30), .5)
