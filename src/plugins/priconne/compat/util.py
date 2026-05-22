import base64
import io
import re
import unicodedata
from pathlib import Path

from PIL import Image, ImageFont


def normalize_str(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text or "")
    normalized = normalized.lower().strip()
    return re.sub(r"\s+", "", normalized)


def filt_message(text: str) -> str:
    text = re.sub(r"\[CQ:[^\]]+\]", "", text or "")
    return text.replace("\r", "").replace("\n", "").strip()


def pic2b64(image: Image.Image) -> str:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return "base64://" + base64.b64encode(buffer.getvalue()).decode()


def get_font(size: int, candidates: list[str] | tuple[str, ...] | None = None):
    default_candidates = [
        "msyh.ttc",
        "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJKSC-Regular.otf",
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    if candidates:
        candidate_list = [*candidates, *default_candidates]
    else:
        candidate_list = default_candidates

    for font_path in candidate_list:
        try:
            p = Path(font_path)
            if p.is_absolute() and not p.exists():
                continue
            return ImageFont.truetype(str(font_path), size)
        except OSError:
            continue
    return ImageFont.load_default()
