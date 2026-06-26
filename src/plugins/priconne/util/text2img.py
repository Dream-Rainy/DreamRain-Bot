import io
import base64
from math import ceil
from PIL import Image, ImageDraw
from ..compat.util import get_font
from ..storage import PRICONNE_DATA_DIR

LINE_CHAR_COUNT = 30*2  # 每行字符数：30个中文字符(=60英文字符)
LINE_CHAR_COUNT_MAX = 0
TABLE_WIDTH = 4
CHAR_SIZE = 32
font_path = PRICONNE_DATA_DIR / "fonts"
FONT_EXTENSIONS = (".otf", ".ttf", ".ttc")
TEXT_MARGIN = 42
FRAME_MARGIN = 16
FRAME_RIGHT_MARGIN = 15
TEXT_SPACING = CHAR_SIZE // 2


def iter_font_candidates():
    if not font_path.exists():
        return []
    if font_path.is_file():
        return [str(font_path)]
    return [
        str(path)
        for path in sorted(font_path.iterdir(), key=lambda item: item.name.lower())
        if path.is_file() and path.suffix.lower() in FONT_EXTENSIONS
    ]


def line_break(line):
    global LINE_CHAR_COUNT_MAX
    LINE_CHAR_COUNT_MAX = 0
    ret = ''
    width = 0
    for c in line:
        if len(c.encode('utf8')) == 3:  # 中文
            if LINE_CHAR_COUNT == width + 1:  # 剩余位置不够一个汉字
                width = 2
                ret += '\n' + c
            else: # 中文宽度加2，注意换行边界
                width += 2
                ret += c
        else:
            if c == '\t':
                space_c = TABLE_WIDTH - width % TABLE_WIDTH  # 已有长度对TABLE_WIDTH取余
                ret += ' ' * space_c
                width += space_c
            elif c == '\n':
                width = 0
                ret += c
            else:
                width += 1
                ret += c
        if width >= LINE_CHAR_COUNT:
            ret += '\n'
            width = 0
            LINE_CHAR_COUNT_MAX = LINE_CHAR_COUNT
        if width > LINE_CHAR_COUNT_MAX:
            LINE_CHAR_COUNT_MAX = width

    if ret.endswith('\n'):
        return ret
    return ret + '\n'

def image_draw(msg,set_max=30*2):
    global LINE_CHAR_COUNT_MAX,LINE_CHAR_COUNT
    LINE_CHAR_COUNT = set_max
    output_str = line_break(msg)
    d_font = get_font(CHAR_SIZE, iter_font_candidates())

    measure_image = Image.new(mode="RGB", size=(1, 1))
    measure_draw = ImageDraw.Draw(im=measure_image)
    text_bbox = measure_draw.multiline_textbbox(
        xy=(TEXT_MARGIN, TEXT_MARGIN),
        text=output_str,
        font=d_font,
        spacing=TEXT_SPACING,
    )
    image_width = max(1, ceil(text_bbox[2] + TEXT_MARGIN))
    image_height = max(1, ceil(text_bbox[3] + TEXT_MARGIN))

    image = Image.new(mode= "RGB", size= (image_width, image_height), color=(255,252,245))
    draw_table = ImageDraw.Draw(im=image)
    draw_table.text(
        xy=(TEXT_MARGIN, TEXT_MARGIN),
        text=output_str,
        fill=(125,101,89),
        font=d_font,
        spacing=TEXT_SPACING,
    )
    draw_table.rectangle(
        xy=(
            FRAME_MARGIN,
            FRAME_MARGIN,
            image_width - FRAME_RIGHT_MARGIN,
            image_height - FRAME_RIGHT_MARGIN,
        ),
        fill=None,
        outline=(220,211,196),
        width=2,
    )
    b_io = io.BytesIO()
    image.save(b_io, format="JPEG")
    base64_str = 'base64://' + base64.b64encode(b_io.getvalue()).decode()
    img = f'[CQ:image,file={base64_str}]'
    return img
