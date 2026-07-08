# DreamRain-Bot

基于 [NoneBot2](https://github.com/nonebot/nonebot2) 和 [OneBot V11](https://github.com/nonebot/nonebot-adapter-onebot) 协议的 QQ 机器人，主要提供**舞萌 DX** 与 **CHUNITHM** 查分功能，集成多种娱乐插件。

## 功能

### 音游查分（chiffon_bot）

- **舞萌 DX** — Best 50 / 歌曲详情 / 拍照曲绘查歌 / 最近成绩 / 定数查分 / 版本别名
- **CHUNITHM** — Best 50 / 歌曲详情 / 搭档进度
- **通用街机曲库** — 通过 arcade-songs 查询更多音游曲目（文字输出）
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
| 公主连接 | 公会战 / JJC 查询 / 角色猜谜 / Wiki 资料查询 | [pcrjjc](https://github.com/reine-ishyanami/nonebot-plugin-pcrjjc)（改） · [priconne](https://github.com/SonderXiaoming/kanna_connection_redive_2) · [kanna_note](https://github.com/SonderXiaoming/kanna_note)（改） |
| 戳一戳 | 戳一戳互动响应 | [pokepoke_miss](https://github.com/MWNya520/pokepoke_miss)（改） |
| GitHub 卡片 | 检测 GitHub 链接自动发送仓库信息 | [githubcard](https://github.com/ElainaFanBoy/nonebot_plugin_githubcard)（改） |
| 疯狂星期四 | KFC 疯四文案生成 | [crazy-thursday](https://github.com/MinatoAquaCrews/nonebot_plugin_crazy_thursday) |
| Wordle | 猜词游戏 | [wordle](https://github.com/noneplugin/nonebot-plugin-wordle) |

> 标注 **（改）** 的为基于社区插件修改，已合入本仓库源码。其余为 pip 依赖，开箱即用。

## 常用命令示例

- maimai：`/mai.song テオ`、`/mai.pic`（附选曲截图或回复图片）、`/mai.b50`
- CHUNITHM：`/chuni.song 1`
- 通用街机曲库：`/arcade.song sdvx FLOWER`、`查歌 ongeki モンダイナイトリッパー！`
- 账号系统：`/acc help`、`/acc.bind 123456789012345`
- 活动系统：`/event.help`
- 管理命令：`/admin.update`、`/admin.clean`、`/admin.search pending`（SUPERUSER）
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

### 本地调试（无需 QQ / NapCat）

```powershell
# 安装依赖
uv sync

# 初始化 Web 调试器 submodule（首次拉取后需要）
git submodule update --init --recursive src/submodule/onebot-v11-web-debugger

# 启动 bot
uv run bot.py
```

另开一个终端启动 OneBot V11 Web Debugger：

```powershell
cd src/submodule/onebot-v11-web-debugger
uv run onebot-v11-web-debugger --connect ws://127.0.0.1:8080/onebot/v11/ws --self-id 10000
```

打开 `http://127.0.0.1:8088/`，在页面里发送调试消息：

```
/mai.b50
/mai.song テオ
/mai.pic
/chuni.song 1
/acc help
/admin.update
```

Web Debugger 通过真实 OneBot V11 反向 WebSocket 接入，因此 SAA、uniseg、回复段、图片段和 OneBot V11 事件类型都会走正常适配路径。若配置了 `ONEBOT_ACCESS_TOKEN`，启动 debugger 时追加 `--access-token <token>`；若 bot 在 Docker 中运行且需要读取上传图片，追加 `--public-base-url http://host.docker.internal:8088`。

控制台调试仍可作为备用的纯文本入口：

```powershell
$env:ENABLE_CONSOLE_DEBUG = "1"
uv run bot.py
```

等待 `Running NoneBot...` 后直接在终端输入命令。

### 完整部署（Docker Compose）

1. 复制环境变量模板：

```bash
cp .env.example .env.prod
```

2. 编辑 `.env.prod`，填写真实配置（QQ 账号、LXNS API Key、数据库密码等）。

3. 为 priconne 账号密码加密生成 Docker secret 源文件。该文件必须长期保留；如果丢失，已保存的密文密码将无法解密，需要重新绑定账号。

```powershell
New-Item -ItemType Directory -Force secrets
uv run python -c "import secrets; print(secrets.token_urlsafe(32))" > secrets/priconne_credential_key
```

4. priconne 登录默认自动过验证码；自动失败时会发送手动验证链接。完成验证后发送：

```text
/priconne.validate <编号> <validate>
```

可用 `priconne_captcha_auto`、`priconne_captcha_admin_group`、`priconne_captcha_timeout` 调整自动过码、兜底群聊和等待超时。

5. 启动全部服务：

```powershell
docker compose up
```

生产环境：

```powershell
docker compose -f docker-compose.yml pull && docker image prune -f && docker compose -f docker-compose.yml up -d
```

> [!TIP]
> 如果你使用浮动标签（`nightly` / `latest` / `master`），新镜像拉取后旧镜像会变成 dangling（`<none>:<none>`），持续累积占用磁盘空间。上述命令在 `pull` 之后立即执行 `docker image prune -f` 可自动清理。

生产环境数据库迁移：

```powershell
docker compose -f docker-compose.yml run --rm dreamrain-bot uv run python scripts/orm.py upgrade
```

该命令会在项目插件加载完成后执行 `nonebot-plugin-orm` 迁移，适合在启动或重启 `dreamrain-bot` 前作为一次性部署步骤运行。可用 `check`、`current`、`history` 等子命令查看迁移状态：

```powershell
uv run python scripts/orm.py check
uv run python scripts/orm.py current
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
| `lxns_api_key` | LXNS API 密钥（LXNS 查分/数据接口相关功能需要；未配置时插件仍可启动） |
| `song_search_embedding_enabled` | 是否启用查歌 embedding 兜底，默认 `false` |
| `song_search_embedding_endpoint` | 本地 embedding HTTP 端点，兼容 Ollama `/api/embed` 和 Hugging Face TEI `/embed`，默认 `http://127.0.0.1:11434/api/embed` |
| `song_search_embedding_model` | embedding 模型名，例如 `Qwen/Qwen3-Embedding-0.6B` / `bge-m3` / `embeddinggemma` |
| `song_search_embedding_path` | embedding JSONL 缓存路径 |
| `song_search_embedding_threshold` | embedding 命中阈值，默认 `80.0` |
| `song_search_embedding_rebuild_batch_size` | rebuild embedding 时每批请求条数，默认 `32`；如调大 TEI `--max-client-batch-size` 可同步调大 |
| `song_search_reranker_enabled` | 是否启用查歌 reranker 精排，默认 `false` |
| `song_search_reranker_endpoint` | 本地 reranker HTTP 端点，兼容 Hugging Face TEI `/rerank`，默认 `http://127.0.0.1:11435/rerank` |
| `song_search_reranker_model` | reranker 模型名，例如 `Alibaba-NLP/gte-multilingual-reranker-base` / `bge-reranker-v2-m3` |
| `song_search_reranker_threshold` | reranker top1 最低分，默认 `0.0` |
| `song_search_reranker_min_margin` | reranker top1/top2 最小分差，默认 `0.0` |
| `ONEBOT_ACCESS_TOKEN` | OneBot 鉴权 Token |

完整配置项参见 [.env.example](./.env.example)。

## 查歌可靠性

查歌会优先使用确定性结果：ID、标题、别名、归一化标题、简繁/拼音/罗马音和模糊匹配。BM25 只作为候选召回；如果 BM25 返回多个分数接近的候选，会先尝试可选 reranker 精排，再尝试 embedding 语义匹配，并要求 top1 与 top2 拉开差距后才接管，避免宽泛抢答。普通无结果场景也会使用 embedding 兜底；reranker 和 embedding 默认关闭，不影响普通部署。

推荐基准方案是 TEI 跑 Qwen3 dense embedding，再用 GTE multilingual reranker 做重排：

```powershell
docker compose --profile search-ai up -d tei-embedding tei-reranker
```

容器内 `.env.prod` 可配置为：

```env
song_search_embedding_enabled=true
song_search_embedding_endpoint=http://tei-embedding/embed
song_search_embedding_model=Qwen/Qwen3-Embedding-0.6B
song_search_reranker_enabled=true
song_search_reranker_endpoint=http://tei-reranker/rerank
song_search_reranker_model=Alibaba-NLP/gte-multilingual-reranker-base
```

如果在宿主机上测试，可使用 `http://127.0.0.1:11434/embed` 和 `http://127.0.0.1:11435/rerank`。如果使用 Ollama embedding endpoint，请把 `song_search_embedding_endpoint` 改成对应的 `/api/embed` 地址。切换 embedding 模型后需要重新执行 `/admin.search embedding rebuild <game>`。

`Qwen/Qwen3-Reranker-0.6B` 暂不作为 TEI 基准模型；TEI 对它的加载兼容性不稳。后续如要评估 Qwen3 reranker，优先考虑 vLLM `/rerank` 作为实验路线。

如需直接使用 FlagEmbedding 做 BGE-M3/BGE-Reranker 实验，可启动最小 HTTP 服务：

```powershell
uv sync --extra bge-service
uv run uvicorn tools.bge_m3_service:app --host 0.0.0.0 --port 11436
```

然后配置：

```env
song_search_embedding_enabled=true
song_search_embedding_endpoint=http://127.0.0.1:11436/embed
song_search_embedding_model=bge-m3
song_search_reranker_enabled=true
song_search_reranker_endpoint=http://127.0.0.1:11436/rerank
song_search_reranker_model=bge-reranker-v2-m3
```

bot 主链路只消费 dense embedding；`tools.bge_m3_service` 仍保留 `/embed-hybrid` 作为 BGE-M3 sparse / ColBERT 实验入口，但默认搜索链路不读取这些字段。BM25 仍保留为召回层，不建议直接停用。

SUPERUSER 可用 `/admin.search` 维护搜索日志驱动的别名修正：

```text
/admin.search pending [数量]
/admin.search show <line>
/admin.search accept <line>
/admin.search reject <line>
/admin.search export accepted [数量]
/admin.search import <JSONL路径>
/admin.search embedding status
/admin.search embedding rebuild <game>
```

`accepted` alias 会参与后续搜索；`pending` 和 `rejected` 不会影响用户查询。MusicBrainz 只通过离线工具生成 pending 候选，不会在用户查歌时实时请求外部服务。

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
