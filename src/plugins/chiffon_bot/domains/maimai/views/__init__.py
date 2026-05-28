from ....infra.html_render import html_to_pic, template_to_pic
from .mai_bg_draw import (
	dx_rating_UI,
	get_rating_image,
	gradients,
	render_b50_img,
	render_r50_img,
	render_song_info_img,
	clear_song_info_img_cache,
	clear_b50_img_cache,
	clear_all_img_cache,
	shadows,
	template_search_paths,
)

__all__ = [
	"dx_rating_UI",
	"get_rating_image",
	"gradients",
	"html_to_pic",
	"render_b50_img",
	"render_r50_img",
	"render_song_info_img",
	"clear_song_info_img_cache",
	"clear_b50_img_cache",
	"clear_all_img_cache",
	"shadows",
	"template_search_paths",
	"template_to_pic",
]
"""maimai 视图/渲染层。

放图片渲染、模板渲染等与输出表现相关的代码。
"""
