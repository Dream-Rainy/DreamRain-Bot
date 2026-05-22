"""maimai NoneBot handlers（命令/事件处理）。"""

from .b50 import b50
from .profile import profile
from .r50 import r50
from .song_info import song_info
from .trend import generate_trend_plot

__all__ = ["b50", "r50", "profile", "generate_trend_plot", "song_info"]
