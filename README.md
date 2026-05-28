# DreamRain-Bot

基于 [NoneBot2](https://github.com/nonebot/nonebot2) 和 [OneBot V11](https://github.com/nonebot/nonebot-adapter-onebot) 协议的 QQ 机器人，主要提供**舞萌 DX** 与 **CHUNITHM** 查分功能，集成多种娱乐插件。

## 功能

### 音游查分（chiffon_bot）

- **舞萌 DX** — Best 50 / 歌曲详情 / 最近成绩 / 定数查分 / 版本别名
- **CHUNITHM** — Best 50 / 歌曲详情 / 搭档进度
- **LXNS OAuth 绑定** — 通过 LXNS 平台绑定玩家账号
- **自然语言识别** — 直接发送谱面封面图触发的相关查询

### 权限管理（permission_admin）

- 按群控制插件启用/禁用
- 远程管理（跨群设置）
- SUPERUSER 全局控制

### 娱乐功能

| 插件 | 说明 | 来源 |
|------|------|------|
| 随机吃啥 | 今日伙食选择困难症终结者 | [whateat-pic](https://github.com/MinatoAquaCrews/nonebot_plugin_what2eat) |
| B站解析 | 分享 Bilibili 链接自动解析 | [analysis-bilibili](https://github.com/mengshouer/nonebot_plugin_analysis_bilibili) |
| 表情包生成 | nonebot-plugin-memes | [plugin-memes](https://github.com/MemeCrafters/nonebot-plugin-memes) |
| 词云 | 群聊词云统计 | [wordcloud](https://github.com/he0119/nonebot-plugin-wordcloud) |
| 猜歌 | 舞萌猜曲小游戏 | [guess-song](https://github.com/apshuang/nonebot-plugin-guess-song) |
| 抽签 / 塔罗 | 运势占卜 | [fortune](https://github.com/MinatoAquaCrews/nonebot_plugin_fortune) · [tarot](https://github.com/MinatoAquaCrews/nonebot_plugin_tarot)（改） |
| 复读 | 群聊复读机 | [repeater](https://github.com/Utmost-Happiness-Planet/nonebot-plugin-repeater)（改） |
| 状态图 | 服务器状态图生成 | [picstatus](https://github.com/lgc-NB2Dev/nonebot-plugin-picstatus)（改） |
| 公主连接 | 公会战 / JJC 查询 / 角色猜谜 | [pcrjjc](https://github.com/reine-ishyanami/nonebot-plugin-pcrjjc)（改） · [priconne](https://github.com/SonderXiaoming/kanna_connection_redive_2) |
| 戳一戳 | 戳一戳互动响应 | [pokepoke_miss](https://github.com/MWNya520/pokepoke_miss)（改） |
| GitHub 卡片 | 检测 GitHub 链接自动发送仓库信息 | [githubcard](https://github.com/ElainaFanBoy/nonebot_plugin_githubcard)（改） |
| 疯狂星期四 | KFC 疯四文案生成 | [crazy-thursday](https://github.com/MinatoAquaCrews/nonebot_plugin_crazy_thursday) |
| Wordle | 猜词游戏 | [wordle](https://github.com/noneplugin/nonebot-plugin-wordle) |

> 标注 **（改）** 的为基于社区插件修改，已合入本仓库源码。其余为 pip 依赖，开箱即用。

## 常用命令示例

- maimai：`/mai.song テオ`、`/mai.b50`
- CHUNITHM：`/chuni.song 1`
- 账号系统：`/acc help`、`/acc.bind 123456789012345`
- 活动系统：`/event.help`
- 权限管理：`/perm`
- 公主连结：`/猜头像`
- 今日运势：`/今日运势`
- 塔罗占卜：`/占卜`
- 猜单词：`/猜单词`
- B 站解析：直接发送 B 站视频链接（如 `https://www.bilibili.com/video/BV1xx411c7mD`）
- GitHub 卡片：直接发送 GitHub 仓库链接（如 `https://github.com/Dream-Rainy/DreamRain-Bot`）
- 戳一戳回复：在群里戳机器人

## 快速开始

### 前置依赖

- [Docker](https://docs.docker.com/desktop/) + Docker Compose
- [uv](https://docs.astral.sh/uv/)（Python 包管理器，本地开发用）
- Python >= 3.12

### 本地调试（无需 QQ / Docker）

```powershell
# 安装依赖
uv sync

# 启动控制台调试模式
$env:ENABLE_CONSOLE_DEBUG = "1"
uv run bot.py
```

等待 `Running NoneBot...` 后直接输入命令：

```
/mai.b50
/mai.song テオ
/chuni.song 1
/acc help
```

### 完整部署（Docker Compose）

1. 复制环境变量模板：

```bash
cp .env.example .env.prod
```

2. 编辑 `.env.prod`，填写真实配置（QQ 账号、LXNS API Key、数据库密码等）。

3. 启动全部服务：

```powershell
docker compose up
```

生产环境：

```powershell
docker compose -f docker-compose.yml up
```

开发环境（含代码热重载）：

```powershell
docker compose -f docker-compose-dev.yml up
```

仅重启 bot 容器（代码变更后）：

```bash
docker compose -f docker-compose-dev.yml restart dreamrain-bot
```

服务组成：

| 容器 | 说明 |
|------|------|
| `napcat` | QQ 协议端（NapCat） |
| `dreamrain-bot` | NoneBot2 机器人本体 |
| `playwright` | HTML 渲染服务 |
| `postgres` | PostgreSQL 数据库 |

## 配置

主要环境变量（`.env` / `.env.prod`）：

| 变量 | 说明 |
|------|------|
| `SUPERUSERS` | 管理员 QQ 号列表 |
| `COMMAND_START` | 命令前缀，默认 `/` |
| `COMMAND_SEP` | 命令层级分隔符，默认 `.`（如 `/mai.b50`） |
| `db_engine` | 数据库引擎：`postgres` / `sqlite` |
| `lxns_api_key` | LXNS API 密钥（音游查分必需） |
| `ONEBOT_ACCESS_TOKEN` | OneBot 鉴权 Token |

完整配置项参见 [.env.example](./.env.example)。

## 项目结构

```
src/plugins/
├── chiffon_bot/          # 音游查分（主插件）
│   ├── app/commands/     #   NoneBot 命令处理器
│   ├── domains/          #   领域逻辑（maimai / chunithm）
│   ├── infra/            #   基础设施（数据库 / HTTP）
│   ├── integrations/     #   外部集成（LXNS API）
│   └── shared/           #   公共工具（BotResponse 等）
├── platform_adapter/     # 跨平台适配层
├── permission_admin/     # 权限管理
├── priconne/             # 公主连接 Re:Dive
└── ...                   # 娱乐插件
```

## 架构特点

- **跨平台兼容** — 通过 SAA（send-anything-anywhere）和 `platform_adapter` 实现消息抽象，核心业务不依赖特定适配器
- **领域驱动分层** — `chiffon_bot` 采用 command → domain → infra 三层架构，业务逻辑返回 `BotResponse`，与消息平台解耦
- **Tortoise ORM** — 异步 ORM，支持 PostgreSQL / SQLite 切换
- **Playwright 渲染** — 复杂数据展示渲染为图片（排行榜、B50 等）
- **Docker 容器化** — 完整 Docker Compose 编排，一键部署

## 开发

```powershell
# 安装开发依赖
uv sync --group dev

# 运行测试
uv run pytest tests/unit tests/integration tests/nonebot

# 代码变更后重启开发栈
docker compose -f docker-compose-dev.yml restart dreamrain-bot
```

## 许可

本项目原创代码以 MIT License 开源，详见 [LICENSE](LICENSE)。

本仓库包含或改造了部分第三方插件、子模块和资源；这些内容仍遵循其各自的原始许可证，而不一定适用本项目的 MIT License。完整来源、路径与许可证说明请参见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) 和 [REUSE.toml](REUSE.toml)。

需要特别注意的第三方内容包括：

- `src/plugins/nonebot_plugin_pcrjjc/`：AGPL-3.0
- `src/plugins/nonebot_plugin_repeater/`：GPL-3.0
- `src/submodule/autopcr/`：CC-BY-NC-SA-4.0
- `src/plugins/priconne/`：未识别到明确的仓库级许可证，部分文件另有单独许可证说明

如果你计划分发本项目、发布 Docker 镜像，或部署为公开网络服务，请先核对上述第三方许可证义务，尤其是 GPL / AGPL 相关条款。
