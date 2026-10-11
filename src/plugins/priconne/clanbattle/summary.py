"""期末总结逐页发送；冻结输入并持久化已成功发送的页。"""

import asyncio
import json
import os
from pathlib import Path

from .review import REVIEW_PAGES

_send_lock = asyncio.Lock()


def summary_due(period, now):
    return period.end + 300 <= now < period.end + 86400


def _read_state(path, period):
    if not path.exists():
        return None
    state = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(state, dict) or type(state.get("period_id")) is not int:
        raise ValueError("总结发送记录损坏，请人工核验；未自动重新发送。")
    if state["period_id"] != period.id:
        return None
    sent, payload = state.get("sent"), state.get("payload")
    if (not isinstance(sent, list) or sent != list(REVIEW_PAGES[:len(sent)])
            or len(sent) > len(REVIEW_PAGES) or not isinstance(payload, dict)
            or payload.get("period_id") != period.id):
        raise ValueError("总结发送记录损坏，请人工核验；未自动重新发送。")
    return state


def _save_state(path, state):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, path)


async def send_summary(path, period, now, prepare, render, send):
    if not summary_due(period, now):
        return False
    path = Path(path)
    async with _send_lock:
        state = await asyncio.to_thread(_read_state, path, period)
        if state is None:
            payload = await prepare()
            if payload.get("period_id") != period.id:
                raise ValueError("总结数据期次不匹配，取消发送。")
            state = dict(period_id=period.id, sent=[], payload=payload)
            await asyncio.to_thread(_save_state, path, state)
        for page in REVIEW_PAGES[len(state["sent"]):]:
            message = await render(state["payload"], page)
            await send(page, message)
            state["sent"].append(page)
            # ponytail: 群接口确认后、落盘前崩溃可能重复一页；平台支持幂等发送时再消除窗口。
            await asyncio.to_thread(_save_state, path, state)
        return True
