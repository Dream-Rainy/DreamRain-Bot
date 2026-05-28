# 共享 HTML 渲染骨架

- `bg_template.html`：全页布局（背景 iframe / 图、overlay），各游戏详情页 `{% extends "bg_template.html" %}`。
- **字体目录**：`shared/render_templates/fonts/`。`@font-face` 中通过 Jinja2 变量 `{{ fonts_dir }}`（file:// URI）引用，由 Python 端注入。

Jinja 搜索路径顺序（见 `mai_bg_draw.template_search_paths`）：maimai 模板根 → 本目录 → `domains/chunithm/template`。
Playwright `base_url` 指向 `data/chiffon_bot/template/maimai/`（素材/外部数据目录）。
