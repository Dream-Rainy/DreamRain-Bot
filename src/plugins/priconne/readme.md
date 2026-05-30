# priconne 公主连结 Re:Dive 插件

本插件整合了自动报刀（KCR 环奈连结R）、分刀、猜头像、猜角色、切噜语、arena 查作业等功能，已迁移为 NoneBot2 插件。

## 配置

环境变量（或 `bot.py` 所在目录的 `.env` 文件）：

- `priconne_arena_auth_key`：arena 查询 API 认证密钥（用于 bjjc/rjjc/tjjc 查作业）

群权限与 `chiffon_bot` 等相同，由 `permission_admin` 统一管理：默认全群可用，在群内使用 `perm off priconne` 可禁用本群（`perm list` 可查看本群是否可用）。

## 功能说明

### 1. 自动报刀（源自 KCR）

加机器人好友，私聊【绑定账号 账号 密码】

- 【出刀监控】【催刀】【当前战报】【我的战报】【今日/昨日战报】【出刀详情】等
- 【预约】【取消预约】【挂树】【下树】【sl】等

### 2. 分刀

- 分刀 [阶段] [毛分/毛伤] (类型) (BOSS)
- 数据来源：https://www.caimogu.cc/gzlj.html

### 3. 小游戏

- 【猜头像】【猜头像排行】
- 【猜角色】【猜角色排行】

### 4. 其他

- 【切噜一下】【切噜～♪】切噜语转换
- bjjc/rjjc/tjjc + 防守队伍：arena 查作业（需配置 `arena_auth_key`）
- 【更新花名册】/【重载花名册】：超管更新角色数据

## 数据目录

- 账号、会战、助战、分刀用户配置、设备 ID 等持久数据由 `nonebot_plugin_localstore` 接管，默认位于 `localstore` 的 `data/priconne/`
- 角色头像、arena 查询结果、识别库、作业网数据等可再生成缓存由 `nonebot_plugin_localstore` 接管，默认位于 `localstore` 的 `cache/priconne/`
