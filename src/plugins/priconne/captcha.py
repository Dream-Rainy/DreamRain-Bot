from __future__ import annotations

import asyncio
import secrets
from dataclasses import dataclass

import httpx
from nonebot import get_driver, logger

from .bsgamesdk import captch
from .compat import Service
from .config import config


captcha_header = {
    "Content-Type": "application/json",
    "User-Agent": "DreamRain-Bot/priconne",
}

sv = Service("priconne验证码", visible=False)
_captcha_auto = config.priconne_captcha_auto
_captcha_local = config.priconne_captcha_local
_pending: dict[str, "ManualCaptchaRequest"] = {}


@dataclass
class CaptchaContext:
    bot: object | None = None
    user_id: int | str | None = None
    group_id: int | str | None = None


@dataclass
class ManualCaptchaRequest:
    token: str
    challenge: str
    gt: str
    userid: str
    event: asyncio.Event
    validate: str | None = None


def _captcha_url(gt: str, challenge: str, userid: str) -> str:
    query = f"captcha_type=1&challenge={challenge}&gt={gt}&userid={userid}&gs=1"
    return f"https://help.tencentbot.top/geetest_/?{query}"


def _new_token() -> str:
    return secrets.token_hex(3)


def _select_pending(token: str | None) -> ManualCaptchaRequest:
    if token:
        if token not in _pending:
            raise ValueError(f"验证码编号不存在或已过期：{token}")
        return _pending[token]
    if len(_pending) == 1:
        return next(iter(_pending.values()))
    if not _pending:
        raise ValueError("当前没有等待中的 priconne 验证码")
    raise ValueError("当前有多个等待中的验证码，请使用 /priconne.validate <编号> <validate>")


def submit_manual_validate(validate_text: str, token: str | None = None) -> str:
    req = _select_pending(token)
    req.validate = validate_text.strip()
    req.event.set()
    return req.token


def set_captcha_auto(enabled: bool) -> None:
    global _captcha_auto
    _captcha_auto = enabled


def is_captcha_auto_enabled() -> bool:
    return _captcha_auto


async def _send_captcha_message(ctx: CaptchaContext | None, message: str) -> None:
    ctx = ctx or CaptchaContext()
    bot = ctx.bot
    if bot is None:
        try:
            bot = get_driver().bots[next(iter(get_driver().bots))]
        except Exception:
            logger.warning(f"priconne captcha needs manual validation, but no bot is available: {message}")
            return

    if ctx.user_id is not None:
        try:
            await bot.send_private_msg(user_id=int(ctx.user_id), message=message)
            return
        except Exception as e:
            logger.warning(f"send priconne captcha private message failed: {e}")

    target_group = ctx.group_id or config.priconne_captcha_admin_group
    if target_group:
        try:
            await bot.send_group_msg(group_id=int(target_group), message=message)
            return
        except Exception as e:
            logger.warning(f"send priconne captcha group message failed: {e}")

    logger.warning(f"priconne captcha message was not delivered: {message}")


# ---- 验证器（对齐 autopcr sdk/validator.py，均自行 start_captcha，返回 {"challenge", "gt_user_id", "validate"}）----

_gtlv_client = None
_gtlv_client_lock = asyncio.Lock()


async def _get_gtlv_client():
    # 复用同一个 Client：首次遇到点选验证码时加载识别模型，这项开销只应付出一次。
    global _gtlv_client
    if _gtlv_client is None:
        async with _gtlv_client_lock:
            if _gtlv_client is None:
                from gtlv import Client
                _gtlv_client = Client(max_attempts=3)
    return _gtlv_client


async def local_captcha_verifier():
    """gtlv 本地过码（对齐 autopcr sdk/validator.py 的 localValidator）。"""
    cap = await captch()
    try:
        client = await _get_gtlv_client()
        result = await client.solve(cap['gt'], cap['challenge'])
        info = {
            "challenge": result.challenge,
            "gt_user_id": cap['gt_user_id'],
            "validate": result.validate,
        }
        logger.info(f"priconne local validator solved a {result.captcha_type} captcha")
    except Exception as e:
        raise Exception(f"本地过码失败：{e}") from e
    return info


async def auto_captcha_verifier():
    """远程过码（pcrd.tencentbot.top，对齐 autopcr sdk/validator.py 的 remoteValidator）。"""
    cap = await captch()
    async with httpx.AsyncClient(timeout=30) as client:
        res = await client.get(
            "https://pcrd.tencentbot.top/geetest_renew",
            params={
                "captcha_type": "1",
                "challenge": cap["challenge"],
                "gt": cap["gt"],
                "userid": cap["gt_user_id"],
                "gs": "1",
            },
            headers=captcha_header,
        )
        res.raise_for_status()
        data = res.json()
        uuid = data["uuid"]

        for _ in range(10):
            res = await client.get(f"https://pcrd.tencentbot.top/check/{uuid}", headers=captcha_header)
            res.raise_for_status()
            data = res.json()

            if "queue_num" in data:
                wait_seconds = min(int(data["queue_num"]), 3) * 10
                logger.info(f"priconne captcha queue={data['queue_num']}, wait={wait_seconds}s")
                await asyncio.sleep(wait_seconds)
                continue

            info = data["info"]
            if isinstance(info, dict) and "validate" in info:
                return {"challenge": info["challenge"], "gt_user_id": info["gt_user_id"], "validate": info["validate"]}
            if info in ["fail", "url invalid"]:
                raise Exception("自动过码失败")
            if info == "in running":
                await asyncio.sleep(5)
                continue

            raise Exception(f"未知过码状态：{info}")

    raise Exception("自动过码多次失败")


async def manual_captcha_verifier(ctx: CaptchaContext | None = None):
    cap = await captch()
    gt, challenge, userid = cap["gt"], cap["challenge"], cap["gt_user_id"]
    token = _new_token()
    req = ManualCaptchaRequest(
        token=token,
        challenge=challenge,
        gt=gt,
        userid=userid,
        event=asyncio.Event(),
    )
    _pending[token] = req
    try:
        message = (
            "priconne 登录需要验证码，请打开链接完成验证后发送：\n"
            f"/priconne.validate {token} <validate>\n"
            f"验证码链接：{_captcha_url(gt, challenge, userid)}"
        )
        await _send_captcha_message(ctx, message)
        await asyncio.wait_for(req.event.wait(), timeout=max(config.priconne_captcha_timeout, 1))
        if not req.validate:
            raise Exception("未收到 validate")
        return {"challenge": challenge, "gt_user_id": userid, "validate": req.validate}
    except asyncio.TimeoutError as e:
        raise Exception("验证码验证超时") from e
    finally:
        _pending.pop(token, None)


async def captcha_verifier(ctx: CaptchaContext | None = None):
    """过码阶梯：本地(gtlv) → 远程(tencentbot.top) → 手动(QQ)。"""
    if _captcha_auto:
        if _captcha_local:
            try:
                return await local_captcha_verifier()
            except Exception as e:
                logger.warning(f"priconne local captcha failed, fallback to remote: {e}")
        try:
            return await auto_captcha_verifier()
        except Exception as e:
            logger.warning(f"priconne auto captcha failed, fallback to manual: {e}")
    return await manual_captcha_verifier(ctx)


def create_captcha_verifier(ctx: CaptchaContext | None = None):
    async def verifier():
        return await captcha_verifier(ctx)

    return verifier


@sv.on_command("priconne.validate", aliases=("/priconne.validate", "公主连结验证码", "自动报刀验证码"), only_to_me=False)
async def handle_validate(session):
    args = session.current_arg_text.strip().split()
    try:
        if len(args) == 1:
            token = submit_manual_validate(args[0])
        elif len(args) >= 2:
            token = submit_manual_validate(args[1], args[0])
        else:
            await session.send("用法：/priconne.validate <validate> 或 /priconne.validate <编号> <validate>")
            return
    except Exception as e:
        await session.send(str(e))
        return
    await session.send(f"priconne 验证码已提交：{token}")


@sv.on_command("priconne.captcha", aliases=("/priconne.captcha", "自动报刀过码"), only_to_me=False)
async def handle_captcha_mode(session):
    arg = session.current_arg_text.strip().lower()
    if arg in ("auto", "自动", "on", "true", "1"):
        set_captcha_auto(True)
        await session.send("priconne 过码已切换为自动优先")
    elif arg in ("manual", "手动", "off", "false", "0"):
        set_captcha_auto(False)
        await session.send("priconne 过码已切换为手动")
    else:
        mode = "自动(本地+远程)" if is_captcha_auto_enabled() else "手动"
        if is_captcha_auto_enabled() and not _captcha_local:
            mode = "自动(仅远程)"
        pending = ", ".join(sorted(_pending)) or "无"
        await session.send(f"priconne 当前过码模式：{mode}；等待中：{pending}")
