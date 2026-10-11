"""会战报表共用的蓝白表格布局。"""

import re

from PIL import Image, ImageDraw

from ..compat.convert2img import _load_font
from ..compat.util import pic2b64


def _wrapped(value, width, font):
    result, line = [], ""
    for word in re.findall(r"[A-Za-z0-9]+(?:[.:/–-][A-Za-z0-9]+)*%?|[^A-Za-z0-9]", str(value)):
        if word == "\n" or (line and font.getlength(line + word) > width):
            result.append(line)
            line = ""
        if word == "\n":
            continue
        for char in word:
            if line and font.getlength(line + char) > width:
                result.append(line)
                line = ""
            line += char
    return result + ([line] if line else [""])


def _report_canvas(title, metadata, cards, sections, note):
    width, ink, muted, blue = 1440, "#172B4D", "#53647B", "#245BBA"
    fonts = {size: _load_font(size) for size in (20, 21, 22, 23, 25, 34, 38)}
    layouts = []
    height = 280
    for label, columns, rows, widths in sections:
        headings = [_wrapped(value, w - 28, fonts[20]) for value, w in zip(columns, widths)]
        header_height = max(len(value) for value in headings) * 29 + 24
        cells = [[_wrapped(value, w - 28, fonts[23]) for value, w in zip(row, widths)] for row in rows]
        row_heights = [max(len(value) for value in row) * 33 + 30 for row in cells]
        layouts.append((label, headings, header_height, cells, row_heights, widths))
        height += (64 if label else 0) + header_height + sum(row_heights) + 26
    note = _wrapped(note, width - 110, fonts[22])
    height += len(note) * 33 + 32
    canvas = Image.new("RGB", (width, height), "#F5F6F9")
    draw = ImageDraw.Draw(canvas)

    def text(x, y, value, size=23, color=ink):
        draw.text((x, y), str(value), font=fonts[size], fill=color)

    draw.rectangle((0, 0, width, 130), fill=ink)
    text(40, 26, title, 38, "#FFFFFF")
    text(40, 88, metadata, 25, "#D8E3F8")
    step = (width - 80) // len(cards)
    for index, (number, label) in enumerate(cards):
        x = 40 + index * step
        draw.rounded_rectangle((x, 154, x + step - 14, 254), radius=14, fill="#FFFFFF")
        text(x + 20, 166, number, 34, blue)
        text(x + 20, 215, label, 21, muted)
    y = 280
    for label, headings, header_height, cells, row_heights, widths in layouts:
        if label:
            draw.rounded_rectangle((40, y, width - 40, y + 52), radius=10, fill=ink)
            text(58, y + 11, label, 25, "#FFFFFF")
            y += 64
        draw.rounded_rectangle((40, y, width - 40, y + header_height), radius=9, fill="#E5EBF6")
        x = 40
        for heading, w in zip(headings, widths):
            for index, line in enumerate(heading):
                text(x + 14, y + 12 + 29 * index, line, 20, blue)
            x += w
        y += header_height
        for row_index, (row, row_height) in enumerate(zip(cells, row_heights)):
            draw.rectangle((40, y, width - 40, y + row_height), fill="#FFFFFF" if row_index % 2 == 0 else "#EEF1F7")
            x = 40
            for cell, w in zip(row, widths):
                for index, line in enumerate(cell):
                    text(x + 14, y + 15 + 33 * index, line)
                x += w
            y += row_height
        y += 26
    for line in note:
        text(44, y, line, 22, muted)
        y += 33
    return canvas


def _report_image(title, metadata, cards, sections, note):
    return f"[CQ:image,file={pic2b64(_report_canvas(title, metadata, cards, sections, note))}]"


def _chart_report_image(title, metadata, cards, label, chart, note):
    header = _report_canvas(title, metadata, cards, [], "")
    font = _load_font(22)
    notes = _wrapped(note, 1330, font)
    y = 344 + chart.height + 20
    canvas = Image.new("RGB", (1440, y + len(notes) * 33 + 24), "#F5F6F9")
    canvas.paste(header.crop((0, 0, 1440, 280)), (0, 0))
    draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle((40, 280, 1400, 332), radius=10, fill="#172B4D")
    draw.text((58, 291), label, font=_load_font(25), fill="white")
    canvas.paste(chart, (40, 344))
    for line in notes:
        draw.text((44, y), line, font=font, fill="#53647B")
        y += 33
    return f"[CQ:image,file={pic2b64(canvas)}]"
