def format_timing_msg(fetch_data: float, render_bg: float, total: float) -> str:
    """将三段耗时（秒）格式化为绘制耗时统计文本。"""
    def fmt(s: float) -> str:
        return f"{s * 1000:.2f} ms"

    return (
        "绘制耗时统计\n"
        f"- 获取数据: {fmt(fetch_data)}\n"
        f"- 绘图:     {fmt(render_bg)}\n"
        f"- 总计:     {fmt(total)}\n"
    )
