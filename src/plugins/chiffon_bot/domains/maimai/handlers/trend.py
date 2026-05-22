import io
from datetime import datetime

import matplotlib.pyplot as plt
from matplotlib import rcParams
from matplotlib.dates import AutoDateLocator, DateFormatter

from ....integrations.lxns.player_api import get_trend_data
from ....shared.bot_response import BotResponse

rcParams["font.sans-serif"] = ["SimHei"]
rcParams["axes.unicode_minus"] = False


async def generate_trend_plot(friend_code: str, headers: dict) -> BotResponse:
    trend_data = await get_trend_data(friend_code, headers)
    dates = []
    totals = []
    standard_totals = []
    dx_totals = []

    for entry in trend_data["data"]:
        try:
            date = datetime.strptime(entry["date"], "%Y-%m-%d")
            total = entry["total"]

            dates.append(date)
            totals.append(total)
            standard_totals.append(entry["standard_total"])
            dx_totals.append(entry["dx_total"])
        except (KeyError, ValueError):
            import traceback
            traceback.print_exc()
            print(f"跳过无效数据: {entry}")

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
