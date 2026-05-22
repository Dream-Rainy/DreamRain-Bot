import base64
import io
import os
from pathlib import Path
from typing import Iterable

from PIL import Image, ImageDraw
from .util import get_font

_PLUGIN_ROOT = Path(__file__).resolve().parents[1]
FONT_PATH = _PLUGIN_ROOT / "fonts" / "SourceHanSansCN-Medium.otf"


def _load_font(size: int = 24):
    return get_font(size, [str(FONT_PATH), "arial.ttf"])


def _to_str_rows(data: Iterable[Iterable[object]]) -> list[list[str]]:
    return [[str(cell) for cell in row] for row in data]


def grid2imgb64(data, title):
    rows = [list(map(str, title))] + _to_str_rows(data)
    if not rows:
        rows = [["空"]]

    font = _load_font(24)
    padding_x = 20
    padding_y = 16
    row_height = 52

    col_count = max(len(row) for row in rows)
    for row in rows:
        if len(row) < col_count:
            row.extend([""] * (col_count - len(row)))

    column_widths = []
    for col_idx in range(col_count):
        max_width = 120
        for row in rows:
            bbox = font.getbbox(row[col_idx])
            max_width = max(max_width, bbox[2] - bbox[0] + padding_x * 2)
        column_widths.append(max_width)

    width = sum(column_widths) + 2
    height = row_height * len(rows) + 2
    image = Image.new("RGB", (width, height), (255, 252, 245))
    draw = ImageDraw.Draw(image)

    y = 1
    for row_idx, row in enumerate(rows):
        x = 1
        fill = (239, 232, 220) if row_idx == 0 else (255, 252, 245)
        for col_idx, cell in enumerate(row):
            cell_width = column_widths[col_idx]
            draw.rectangle(
                (x, y, x + cell_width, y + row_height),
                fill=fill,
                outline=(220, 211, 196),
                width=1,
            )
            draw.text((x + padding_x, y + padding_y - 2), cell, fill=(80, 70, 60), font=font)
            x += cell_width
        y += row_height

    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    payload = base64.b64encode(buffer.getvalue()).decode()
    return f"[CQ:image,file=base64://{payload}]"
