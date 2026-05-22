# 共享 HTML 渲染骨架

- `bg_template.html`：全页布局（背景 iframe / 图、overlay），各游戏详情页 `{% extends "bg_template.html" %}`。
- **字体目录**：`shared/render_templates/fonts/`。渲染时 Playwright 的 `base_url` 仍指向 `domains/maimai/template/`，`@font-face` 中通过 `../../../shared/render_templates/fonts/...` 解析到本目录。

Jinja 搜索路径顺序（见 `mai_bg_draw.template_search_paths`）：maimai 模板根 → 本目录 → `domains/chunithm/template`。
