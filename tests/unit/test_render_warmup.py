from __future__ import annotations

import asyncio
import json
import time

from tests.unit.test_html_render import Browser, Page, render_module  # noqa: F401


async def test_font_warmup_does_not_block_or_cancel_foreground(render_module, monkeypatch, tmp_path):
    from src.plugins.chiffon_bot.infra import render_warmup

    entered, closed = asyncio.Event(), asyncio.Event()
    class WarmPage(Page):
        async def evaluate(self, expression, *args):
            entered.set()
            await self.close_event.wait()
            closed.set()
            raise RuntimeError('warm page closed')

    class WarmBrowser(Browser):
        async def new_page(self, *, viewport, **options):
            page = WarmPage(viewport)
            self.pages.append(page)
            return page

    browser = WarmBrowser()
    async def get_browser():
        return browser
    async def ready(page, **options):
        pass
    monkeypatch.setattr(render_module, '_get_browser', get_browser)
    monkeypatch.setattr(render_module, '_wait_resources', ready)
    monkeypatch.setattr(render_warmup, '_ASSETS', tmp_path)
    monkeypatch.setattr(render_warmup, '_task', None)
    try:
        render_warmup.start_render_warmup()
        await asyncio.wait_for(entered.wait(), 1)
        image = await asyncio.wait_for(render_module.html_to_pic('foreground', template_path=tmp_path.as_uri(),
            device_scale_factor=1, viewport={'width': 120, 'height': 80}, _reuse_page=True), 1)
        assert json.loads(image)[0].endswith('foreground')
        main = browser.pages[1]
        await asyncio.wait_for(render_warmup.stop_render_warmup(), 1)
        assert closed.is_set() and browser.pages[0].closed
        assert not main.closed
        image = await asyncio.wait_for(render_module.html_to_pic('after', template_path=tmp_path.as_uri(),
            device_scale_factor=1, viewport={'width': 120, 'height': 80}, _reuse_page=True), 1)
        assert json.loads(image)[0].endswith('after')
    finally:
        await render_warmup.stop_render_warmup()


async def test_busy_or_failed_warmup_leaves_foreground_usable(render_module, monkeypatch, tmp_path):
    from src.plugins.chiffon_bot.infra import render_warmup

    browser = Browser()
    async def get_browser():
        return browser
    monkeypatch.setattr(render_module, '_get_browser', get_browser)
    monkeypatch.setattr(render_warmup, '_ASSETS', tmp_path)
    async with render_module._local_page(1, {}, viewport={'width': 120, 'height': 80}) as foreground:
        await asyncio.wait_for(render_warmup._warm_fonts(), 1)
        assert not foreground.closed and len(browser.pages) == 1

    async def failed_fonts():
        raise RuntimeError('fonts unavailable')
    monkeypatch.setattr(render_warmup, '_warm_fonts', failed_fonts)
    # Missing local assets are allowed; warmup completes without a browser error.
    await asyncio.wait_for(render_warmup._warm_up(), 1)
    async with render_module._local_page(1, {}, viewport={'width': 120, 'height': 80}) as after:
        assert after is foreground and not after.closed


async def test_heartbeat_yields_between_batches_and_preserves_foreground(render_module, monkeypatch, tmp_path):
    from src.plugins.chiffon_bot.infra import render_warmup

    warming, resume, foreground_entered, finish = (asyncio.Event() for _ in range(4))
    calls = []
    class HotPage(Page):
        async def evaluate(self, expression, args):
            calls.append(args['urls'])
            warming.set()
            await resume.wait()
            return {'decoded': args['urls'], 'failed': [], 'skipped': [], 'pixels': len(args['urls']) * 640000}

    class HotBrowser(Browser):
        async def new_page(self, *, viewport, **options):
            page = HotPage(viewport)
            self.pages.append(page)
            return page

    browser = HotBrowser()
    async def get_browser():
        return browser
    async def ready(page, **options):
        if page.html.endswith('foreground'):
            foreground_entered.set()
            await finish.wait()

    monkeypatch.setattr(render_module, '_get_browser', get_browser)
    monkeypatch.setattr(render_module, '_wait_resources', ready)
    monkeypatch.setattr(render_warmup, '_COMMON_URLS', [])
    monkeypatch.setattr(render_warmup, '_WORK_SECONDS', 10)
    async with render_module._local_page(1, {}, viewport={'width': 1280, 'height': 2280}):
        pass
    pool = render_module._page_pool
    pool.remember_covers([{'url': (tmp_path / 'jacket' / f'{i}.png').as_uri(), 'pixels': 640000} for i in range(8)])
    for cover in pool.covers.values():
        cover.warmed = time.monotonic() - 31
    hot = asyncio.create_task(render_warmup._heartbeat())
    foreground = None
    try:
        await asyncio.wait_for(warming.wait(), 1)
        foreground = asyncio.create_task(render_module.html_to_pic('foreground', template_path=tmp_path.as_uri(),
            device_scale_factor=1, viewport={'width': 120, 'height': 80}, _reuse_page=True))
        await asyncio.wait_for(foreground_entered.wait(), 1)
        resume.set()
        await asyncio.wait_for(hot, 1)
        assert len(calls) == 1 and len(calls[0]) == 4
        assert browser.pages[0].viewport_size == {'width': 1280, 'height': 2280}
        assert not any(page.closed for page in browser.pages)
        finish.set()
        assert json.loads(await asyncio.wait_for(foreground, 1))[0].endswith('foreground')

        pool.last_used = time.monotonic() - 601
        await render_warmup._heartbeat()
        assert len(calls) == 1
    finally:
        resume.set()
        finish.set()
        await asyncio.gather(hot, *([foreground] if foreground is not None else []), return_exceptions=True)


async def test_single_maintenance_task_stops_during_heartbeat(monkeypatch, loaded_chiffon_bot):
    from src.plugins.chiffon_bot.infra import render_warmup

    entered, stopped = asyncio.Event(), asyncio.Event()
    async def prepared():
        pass
    async def heartbeat():
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()
    monkeypatch.setattr(render_warmup, '_warm_up', prepared)
    monkeypatch.setattr(render_warmup, '_heartbeat', heartbeat)
    monkeypatch.setattr(render_warmup, '_INTERVAL', 0.001)
    monkeypatch.setattr(render_warmup, '_task', None)
    try:
        render_warmup.start_render_warmup()
        task = render_warmup._task
        render_warmup.start_render_warmup()
        assert render_warmup._task is task
        await asyncio.wait_for(entered.wait(), 1)
        await asyncio.wait_for(render_warmup.stop_render_warmup(), 1)
        assert stopped.is_set() and task.done() and render_warmup._task is None
    finally:
        await render_warmup.stop_render_warmup()
