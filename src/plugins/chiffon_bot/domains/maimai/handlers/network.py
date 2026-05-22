from nonebot import require

require("nonebot_plugin_htmlrender")

from nonebot_plugin_htmlrender.browser import get_new_page

async def get_page_screenshot() -> bytes:
    async with get_new_page(device_scale_factor=1) as page:
        await page.goto("https://mai.chongxi.us/?share=true&dark=auto")
        await page.wait_for_url("**/?share=true&dark=auto", wait_until="networkidle", timeout=30000)
        return await page.screenshot(
            full_page=True,
            type="png",
            timeout=30000,
        )