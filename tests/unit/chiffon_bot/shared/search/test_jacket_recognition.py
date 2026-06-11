from __future__ import annotations

from PIL import Image, ImageDraw


def _pattern_image(kind: str, size: int = 128) -> Image.Image:
    image = Image.new("RGB", (size, size), "white")
    draw = ImageDraw.Draw(image)
    if kind == "diagonal":
        for offset in range(-size, size, 12):
            draw.line((offset, 0, offset + size, size), fill="navy", width=5)
    elif kind == "horizontal":
        for y in range(0, size, 14):
            draw.rectangle((0, y, size, y + 6), fill="darkgreen")
    else:
        raise ValueError(kind)
    return image


def test_rank_jacket_matches_prefers_exact_pattern() -> None:
    from src.plugins.chiffon_bot.shared.search.jacket_recognition import (
        JacketReference,
        _dhash,
        rank_jacket_matches,
    )

    diagonal = _pattern_image("diagonal")
    horizontal = _pattern_image("horizontal")
    refs = [
        JacketReference(1, "Diagonal Song", "a.png", _dhash(diagonal)),
        JacketReference(2, "Horizontal Song", "b.png", _dhash(horizontal)),
    ]

    result = rank_jacket_matches(diagonal, refs)

    assert result.best is not None
    assert result.best.song_id == 1
    assert result.best.distance == 0
    assert result.is_confident


def test_select_largest_square_crop_uses_largest_candidate() -> None:
    from src.plugins.chiffon_bot.shared.search.jacket_recognition import select_largest_square_crop

    image = Image.new("RGB", (420, 260), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((30, 60, 100, 130), fill="red", outline="black", width=4)
    draw.rectangle((230, 50, 370, 190), fill="blue", outline="black", width=4)

    selection = select_largest_square_crop(image)

    assert selection is not None
    x, _, w, h = selection.box
    assert w == h
    assert x > 190
    assert w >= 120


def test_recognition_confidence_rejects_close_ambiguous_matches() -> None:
    from src.plugins.chiffon_bot.shared.search.jacket_recognition import (
        JacketMatch,
        JacketRecognitionResult,
    )

    result = JacketRecognitionResult(
        matches=[
            JacketMatch(1, "A", "a.png", 58),
            JacketMatch(2, "B", "b.png", 55),
        ],
        reference_count=2,
    )

    assert not result.is_confident
