from __future__ import annotations

import time
from collections.abc import Sequence
from os import getcwd
from pathlib import Path
from typing import Any, Literal

import jinja2
from nonebot import logger, require


def _ensure_htmlrender_loaded() -> None:
    # 延迟加载，避免在“仅导入模块”时触发 NoneBot 初始化链
    require("nonebot_plugin_htmlrender")


def _get_new_page():
    _ensure_htmlrender_loaded()
    from nonebot_plugin_htmlrender.browser import get_new_page as _real_get_new_page

    return _real_get_new_page


# 与 bg_template.html 中注入的 window.__BG_IFRAME_READY__ 对齐；未定义则视为无需等待（非该模板的 HTML）
_RENDER_READY_JS = """() => {
  if (typeof window.__BG_IFRAME_READY__ === 'undefined') return true;
  return window.__BG_IFRAME_READY__ === true;
}"""


def _default_ready_timeout_ms(screenshot_timeout: float | None) -> float:
    cap = 25_000.0
    if screenshot_timeout is None:
        return cap
    return min(cap, float(screenshot_timeout))


def _attach_pending_request_tracker(page: Any) -> dict[str, str]:
    """返回 pending 映射 url -> resource_type，在 requestfinished/failed 时移除。"""
    pending: dict[str, str] = {}

    def on_request(request: Any) -> None:
        pending[request.url] = getattr(request, "resource_type", "?")

    def on_done(request: Any) -> None:
        pending.pop(request.url, None)

    page.on("request", on_request)
    page.on("requestfinished", on_done)
    page.on("requestfailed", on_done)
    return pending


def _log_pending_requests(prefix: str, pending: dict[str, str], limit: int = 30) -> None:
    if not pending:
        logger.warning(f"{prefix} 当前无 pending 请求记录（或已全部结束）")
        return
    items = list(pending.items())[:limit]
    logger.warning(f"{prefix} 未完成请求（最多 {limit} 条）: {items}")



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

    async with _get_new_page()(device_scale_factor, **kwargs) as page:
        pending = _attach_pending_request_tracker(page)

        if debug:
            page.on("console", lambda msg: logger.debug(f"浏览器控制台: {msg.text}"))
            page.on(
                "requestfailed",
                lambda req: logger.debug(f"请求失败: {req.url} {req.failure}"),
            )

        t0 = time.perf_counter()
        t_goto = 0.0
        t_set = 0.0
        t_ready = 0.0
        t_fallback = 0.0
        used_fallback = False

        t_a = time.perf_counter()
        await page.goto(template_path)
        t_goto = time.perf_counter() - t_a

        t_b = time.perf_counter()
        await page.set_content(html, wait_until=wait_until)
        t_set = time.perf_counter() - t_b

        t_c = time.perf_counter()
        ready_ok = False
        try:
            await page.wait_for_function(_RENDER_READY_JS, timeout=ready_timeout)
            ready_ok = True
        except Exception as e:
            if log_render_phases:
                logger.warning(f"html_render: 就绪等待超时 ({ready_timeout:.0f}ms)，将尝试降级: {e}")
                _log_pending_requests("html_render[ready_timeout]", pending)
            if fallback_networkidle_on_ready_timeout:
                used_fallback = True
                t_fb0 = time.perf_counter()
                try:
                    await page.set_content(html, wait_until="networkidle")
                except Exception as fe:
                    logger.warning(f"html_render: networkidle 降级 set_content 失败: {fe}")
                    _log_pending_requests("html_render[fallback_set_content]", pending)
                t_fallback = time.perf_counter() - t_fb0
                try:
                    await page.wait_for_function(
                        _RENDER_READY_JS,
                        timeout=min(15_000.0, ready_timeout),
                    )
                    ready_ok = True
                except Exception as e2:
                    logger.warning(f"html_render: 降级后就绪仍超时，继续截图: {e2}")
                    _log_pending_requests("html_render[fallback_ready_timeout]", pending)
            else:
                raise
        t_ready = time.perf_counter() - t_c

        await page.wait_for_timeout(wait)
        if debug:
            html_debug = await page.content()
            print(html_debug)

        t_d = time.perf_counter()
        shot = await page.screenshot(
            full_page=False,
            type=type,
            quality=quality,
            timeout=screenshot_timeout,
        )
        t_shot = time.perf_counter() - t_d

        total = time.perf_counter() - t0
        if log_render_phases:
            logger.debug(
                "html_render: "
                f"goto={t_goto * 1000:.0f}ms "
                f"set_content={t_set * 1000:.0f}ms "
                f"ready_phase={t_ready * 1000:.0f}ms "
                f"fallback={t_fallback * 1000:.0f}ms "
                f"screenshot={t_shot * 1000:.0f}ms "
                f"total={total * 1000:.0f}ms "
                f"fallback_used={used_fallback} "
                f"ready_ok={ready_ok}"
            )

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
            第一个目录用作资源解析的默认 ``base_url`` / Playwright ``goto``，除非 ``pages["base_url"]`` 已指定 file URI。
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

    if len(roots) == 1:
        loader = jinja2.FileSystemLoader(str(roots[0]))
    else:
        loader = jinja2.ChoiceLoader(
            [jinja2.FileSystemLoader(str(r)) for r in roots]
        )

    template_env = jinja2.Environment(  # noqa: S701
        loader=loader,
        enable_async=True,
    )

    if filters:
        for filter_name, filter_func in filters.items():
            template_env.filters[filter_name] = filter_func
            print(f"加载自定义过滤器 {filter_name}")

    template = template_env.get_template(template_name)

    return await html_to_pic(
        template_path=goto_uri,
        html=await template.render_async(**templates),
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
        **pages,
    )
