import io
from datetime import datetime

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import rcParams
from matplotlib.dates import AutoDateLocator, DateFormatter
from nonebot import logger

from arcade_helper import MaimaiPlayer

from ....shared.bot_response import BotResponse

rcParams["font.sans-serif"] = ["SimHei"]
rcParams["axes.unicode_minus"] = False


async def generate_trend_plot(player: MaimaiPlayer, headers: dict) -> BotResponse:
    try:
        trend_data = (await player.trend(headers=headers)).data
    except Exception as exc:
        logger.warning(f"查询趋势失败: {player.friend_code} - {exc}")
        return BotResponse(text="查询失败，请稍后重试。")
    payload = trend_data.model_extra or {}
    if payload.get("code", 200) != 200 or payload.get("success") is False:
        return BotResponse(text=f"查询失败, {payload.get('message', '查分器返回异常')}")
    dates = []
    totals = []
    standard_totals = []
    dx_totals = []

    for entry in trend_data.trend:
        try:
            date = datetime.strptime(entry.date, "%Y-%m-%d")
            total = entry.total
            standard = entry.standard if entry.standard is not None else entry.raw["standard_total"]
            dx = entry.dx if entry.dx is not None else entry.raw["dx_total"]
            if total is None or standard is None or dx is None:
                raise ValueError("Missing rating totals")
        except (KeyError, TypeError, ValueError):
            logger.warning(f"跳过无效趋势数据: {entry}")
            continue
        dates.append(date)
        totals.append(total)
        standard_totals.append(standard)
        dx_totals.append(dx)

    if not dates:
        return BotResponse(text="暂无 DX Rating 趋势数据。")

    plt.figure(figsize=(15, 6))
    plt.plot(dates, totals, marker="o", linestyle="-", color="blue", label="DX Rating")

    locator = AutoDateLocator()
    formatter = DateFormatter("%m-%d")
    plt.gca().xaxis.set_major_locator(locator)
    plt.gca().xaxis.set_major_formatter(formatter)

    count = 0
    for i, (x, y, std, dx) in enumerate(zip(dates, totals, standard_totals, dx_totals)):
        if i % 3 == 0:
            count += 1
            annotation_text = f"B35:{std}\n B15:{dx}"
            offset_x = 10 if count % 2 == 1 else -10
            offset_y = 15 if count % 2 == 1 else -50
            plt.annotate(
                annotation_text,
                (x, y),
                textcoords="offset points",
                xytext=(offset_x, offset_y),
                ha="center",
                fontsize=16,
                color="darkred",
            )

    plt.title("DX Rating 趋势图")
    plt.xlabel("日期")
    plt.ylabel("DX Rating")
    plt.grid(True)
    plt.legend()
    plt.tight_layout()

    trend_plot_buffer = io.BytesIO()
    plt.savefig(trend_plot_buffer, format="png", dpi=300)
    plt.close()

    trend_plot_buffer.seek(0)
    trend_plot_bytes = trend_plot_buffer.read()
    trend_plot_buffer.close()

    return BotResponse(image=trend_plot_bytes)
