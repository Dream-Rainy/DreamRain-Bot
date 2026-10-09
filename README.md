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

- 音游功能总览：`/arcade.help` 输出简短纯文本帮助；完整游戏列表见 `/arcade.list`，舞萌/中二详细用法见 `/mai.help`、`/chuni.help`。
- maimai：`/mai.song テオ`、`/mai.pic`（附选曲截图或回复图片）、`/mai.b50`
- CHUNITHM：`/chuni.song 1`
- 通用街机曲库：`/arcade.list` 查看支持的游戏，管理员先用 `/admin.alias sync sdvx` 导入，再用 `/arcade.song sdvx FLOWER` 查询歌曲、`/arcade.games FLOWER` 查询已导入的作品收录、`/arcade.artist sdvx xi` 查询曲师作品。已导入的通用曲库随后台曲库任务更新；跨游戏查询按确认的作品关联展开，不仅凭同名标题判断。
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

## 歌曲别名与审核

需要 arcade-helper 的 S2/S3 别名与持久曲库接口。部署前须将新版子模块代码纳入相应版本并更新子模块指针；仅主仓库修改配合旧子模块版本无法运行。

`/mai.alias <歌曲ID或名称>`、`/chuni.alias <歌曲ID或名称>` 和 `/arcade.alias <game> <歌曲ID或名称>` 显示有效别名、合并后的来源和范围。有歧义时列出候选，不自动选择第一条。舞萌、中二命令使用原生歌曲 ID；其他游戏使用导入后的稳定收录 ID，旧版本的临时枚举 ID 不可沿用。`/arcade.games` 显示游戏、歌曲 ID 和曲名，多个同名作品以“作品 1、作品 2”区分，不展示内部作品 UUID。

曲名与别名在入库和查询时统一使用 Unicode NFKC 规范化（统一全半角）。零宽字符、换行和 emoji 不按字符类别禁止；全空格曲名也保留，例如舞萌 ID 1422 的全角空格标题存为半角空格，可用 `/mai.song 1422` 查询。原始来源快照保留，缺失标题或超过长度限制的项会报告；部分异常不会覆盖已有歌曲或撤销已有别名。

```text
/arcade.alias add sdvx 5459 testAlias
/arcade.alias add sdvx FLOWER 游戏限定简称
/arcade.alias add "Transcend Lights" 跨游戏简称
/arcade.alias request <请求ID>
/arcade.alias withdraw <请求ID> <版本>
```

添加格式为 `/arcade.alias add [游戏] <曲名/已有别名/ID> <新别名>`，含空格的查询词用引号包住。指定游戏时自动使用 `game_song`，只作用于选中的收录；省略游戏时自动使用 `work`，共享到同一作品的其他已关联收录。唯一精确匹配直接提交，同一作品的多个游戏收录视为一个目标；不同作品或仅有近似匹配时，回复数字选择目标，选择不会改变原命令确定的范围。每位用户每天最多提交 20 个新请求（按 UTC 日界线），同时最多 5 个待审请求。待审内容不会进入搜索；重复提交复用已有待审操作。

相同范围、来源游戏和标准化别名的待审请求会复用：`work` 按作品去重，`game_song` 按具体收录去重；不同歌曲可以使用相同别名。兼容升级前已存在的待审请求，不重写审核历史。

`pending` 每页显示最多 20 条曲名、别名与范围摘要；只有还有结果时才提供下一页命令。可直接复制该命令，其中数字表示上一页末尾的请求编号。完整影响、冲突候选与目标版本通过 `show` 查看。

SUPERUSER 使用以下命令审核。请求版本从 `show` 结果获取，批准和驳回均需理由；提交者及共同提交者不能自审，包括管理员。因此管理员自己提交的维护请求需要另一位 SUPERUSER 审核。

```text
/admin.alias pending [上一页末尾请求ID]
/admin.alias show <请求ID>
/admin.alias approve <请求ID> <版本> <理由>
/admin.alias reject <请求ID> <版本> <理由>
/admin.alias confirm <请求ID> <版本> <目标版本JSON> <理由>
/admin.alias retract <证据ID> <理由>
/admin.alias replace <证据ID> <game> <歌曲ID> <work|game_song> <新别名>
/admin.alias block <game> <歌曲ID> <别名>
/admin.alias unblock <game> <歌曲ID> <别名>
/admin.alias relink <merge|split> <内部收录ID,内部收录ID> <理由>
/admin.alias candidates [游标]
/admin.alias decide <候选ID> <版本> <accept|reject> <理由>
/admin.alias sync <game>
/admin.alias imports <game>
/admin.alias map <game> <provider> <namespace> <external_key> <bind|new|reject> <内部收录ID或-> <理由>
```

目标发生变化时，先重新 `show` 查看内容、影响游戏和同名候选，再决定是否 `confirm`。复制 `show` 输出的紧凑目标版本 JSON，不要自行编造版本。作品关联使用内部收录 ID，别名查询输出中可查看；`retract/replace/block/unblock/relink/map` 创建维护请求，仍需另一位审核员批准。关联候选的 `decide` 是管理员直接决策，需携带候选版本。`imports` 查看通用曲库导入报告；其中身份不确定的记录可用 `map` 绑定已有收录、确认为新收录或拒绝，原文由库读取已保存的抓取快照。

已知来源的外部别名由 arcade-helper 同步。未知外部来源默认禁用；SUPERUSER 可用 `/admin.alias source <来源键> <game或global> <enable|disable>` 配置外部来源。旧 `/admin.search accept/reject` 已停用：舞萌、中二历史搜索候选可用 `/admin.search submit <旧记录编号>` 转成新版待审请求；其他游戏需核对当前 ID 后重新 `add`。搜索历史的查看、导入和导出仍可用，但不直接使别名生效。

### 首次升级与旧别名迁移

先备份数据库，在隔离副本预览、执行升级并验证。机器人启动会升级缺失的曲库列、创建新表，并回填舞萌/中二原生身份和旧数据库别名；升级失败会中止，不把建表当作修复。旧数据库别名记录为 `legacy:<game>`，旧 JSONL 已通过结果需要显式迁移。

```powershell
# 将 URL 替换为隔离副本；--apply 的 --actor 必须是 .env SUPERUSERS 中的 QQ 账号
uv run python tools/migrate_aliases.py --db-url 'sqlite://docs/plan/catalog-copy.sqlite3' --schema-only
uv run python tools/migrate_aliases.py --db-url 'sqlite://docs/plan/catalog-copy.sqlite3' --schema-only --apply --actor '<QQ>'
# 预览原生身份回填，再执行；不指定 --input 时只回填旧数据库曲库
uv run python tools/migrate_aliases.py --db-url 'sqlite://docs/plan/catalog-copy.sqlite3'
uv run python tools/migrate_aliases.py --db-url 'sqlite://docs/plan/catalog-copy.sqlite3' --apply --actor '<QQ>'
# 检查 ready/unresolved，再执行 JSONL 导入
uv run python tools/migrate_aliases.py --db-url 'sqlite://docs/plan/catalog-copy.sqlite3' --input 'data/chiffon_bot/song_search_history.jsonl' --mapping 'docs/plan/alias-id-map.json'
uv run python tools/migrate_aliases.py --db-url 'sqlite://docs/plan/catalog-copy.sqlite3' --input 'data/chiffon_bot/song_search_history.jsonl' --mapping 'docs/plan/alias-id-map.json' --apply --actor '<QQ>'
```

JSONL 仅迁移 `accepted`，记录为 `bot-legacy:<game>`，范围为 `game_song`；待审、驳回记录保留为历史。通用游戏先导入曲库，再人工提供映射，例如 `{"sdvx:1001":42}`（旧 ID→当前内部收录 ID）；迁移同时核对标题，无法确认的记录不会写入。脚本可以重复执行，也不会复活已撤销的证据。确认隔离副本无误后再对实际数据库执行。

新别名生效或撤销后，搜索索引按修订号刷新。启用 embedding 后，后台自动更新受影响的歌曲向量；更新完成前跳过过期向量，也可用 `/admin.search embedding rebuild <game>` 手动触发。不主动发送审核通知。

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

5. 使用 `docker-compose.example.yml` 作为部署配置，首次构建并启动全部服务：

```powershell
cp docker-compose.example.yml docker-compose.yml
docker compose --env-file .env.prod up --build
```

生产环境：

```powershell
docker compose --env-file .env.prod -f docker-compose.yml pull --ignore-buildable
docker compose --env-file .env.prod -f docker-compose.yml up -d --build
```

> [!TIP]
> 如果你使用浮动标签（`nightly` / `latest` / `master`），新镜像拉取后旧镜像可能变成 dangling（`<none>:<none>`）。需要清理时可执行 `docker image prune`。

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
docker compose -f docker-compose-dev.yml up --build
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

### Playwright GPU 与字体

渲染镜像由 `Dockerfile.playwright` 构建，Node 服务和 Python 客户端均固定 Playwright 1.57.0。默认 `PLAYWRIGHT_GPU_MODE=auto`：在实际渲染进程核对 renderer、GPU 合成和栅格状态，硬件不可用时退回软件渲染。`cpu` 强制软件，`gpu` 要求硬件成功，否则服务启动失败。就绪检查在探测和回退结束后才通过。

Linux NVIDIA 部署需先安装宿主 NVIDIA 驱动与 NVIDIA Container Toolkit，再启用设备覆盖：

```bash
docker compose --env-file .env.prod -f docker-compose.yml -f docker-compose.gpu.yml up -d --build
docker logs playwright --tail 30
```

开发栈将第一个配置换为 `docker-compose-dev.yml`。覆盖只为 Playwright 预留 GPU，并开放 `graphics,utility` 驱动能力；普通 Docker/Windows Docker Desktop 使用基础配置即可。设备预留报错需检查宿主驱动/Toolkit，浏览器的软件回退无法绕过 Docker 的设备配置错误。GPU 模式是 Compose 服务配置；写在 `.env.prod` 时需要上面的 `--env-file .env.prod`。启动日志会列出实际 mode、renderer、hardware、features 和回退原因；仅 `nvidia-smi` 可见不能证明 Chromium 已加速。

本地 Windows 可用同版本 Node Playwright 执行 `node tools/playwright_server.cjs`，启用 GPU 时使用 ANGLE/D3D11；Linux 使用 Vulkan 参数。服务端按自己的操作系统选择参数，远程 `HTMLRENDER_CONNECT` 不受 bot 的 `htmlrender_browser_args` 控制。其他平台可使用默认/软件路径；本轮未验证 macOS 硬件加速。

镜像将 Inter、NotoSansJP、Hiragino W3、FOT NewRodin M/DB/B、思源 CN Bold、思源 CN 可变字体（`SourceHanSansCN-VF.ttf`）和修复后的六个 GenSen TW 字重注册为系统字体。辅助中文使用思源 CN 可变字体，歌曲标题和曲师保留原字体。模板优先 `local()`，缺少系统字体时回退到同一字体文件 URL；复用现有同页字体预热。原 GenSen TTC 的损坏 cmap 已修复为保留完整 TW 字形的 TTF，可核对或重新生成：

```bash
uv run python tools/repair_gensen_fonts.py --check
uv run python tools/repair_gensen_fonts.py
```

本地浏览器要获得 `local()` 收益，需从 `src/plugins/chiffon_bot/shared/render_templates/fonts` 安装上述相同文件和版本；GenSen 安装修复的 `GenSenRounded2-TW-*.ttf`，避免同时安装同名旧 TTC。Windows 选择字体文件后使用“为所有用户安装”；Linux 将指定字体复制到 `/usr/local/share/fonts/chiffon` 并执行 `fc-cache -f`。无需安装全部展示字体，未安装字体仍由 URL 加载。

字体和启动器随渲染镜像打包；修改后执行 `docker compose -f docker-compose-dev.yml up -d --build playwright`，生产配置同理。bot 源码热更新挂载保留。容器内字体位于 `/app/src/.../fonts`，素材在双方共同挂载的 `/app/data`；本地/远端浏览器必须能访问模板里的文件路径，跨操作系统 `file:` URI 不会自动映射。

### Playwright 二进制图片返回

`HTMLRENDER_BINARY_ENDPOINT` 指定同一 Playwright 服务的 HTTP 地址，例如容器间 `http://playwright:3002`。截图仍使用标准 Playwright API，图片字节经 HTTP 返回，避免大图片在服务端到 bot 的协议链路中反复序列化。留空继续使用标准协议；旧服务、版本不兼容或 HTTP 失败会回退。图片质量、尺寸、资源检查和素材热更新保持原行为。

Compose 示例默认启用容器内地址，不发布生产 HTTP 端口。开发栈另提供 `127.0.0.1:23002`，主机运行 bot 时设 `HTMLRENDER_BINARY_ENDPOINT=http://127.0.0.1:23002`；本机 Node 服务使用 `http://127.0.0.1:3002`。HTTP 服务须与 WebSocket 连接指向同一服务，仅供可信内网使用。每个请求独立关联页面，结果领取后删除，最多16个请求/64MiB临时图片字节、单张16MiB、60秒过期，不复用结果图片或落盘。

升级时重建 Playwright 镜像并重建 bot 容器以载入端点环境变量，例如 `docker compose -f docker-compose-dev.yml up -d --build playwright dreamrain-bot`。清空该配置可回到标准返回路径。二进制适配固定 Playwright1.57.0；升级版本时需同时验证服务端和 Python 客户端，未知服务端版本保留标准截图路径。

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
| `song_search_embedding_path` | embedding 缓存基准路径；歌曲向量按游戏保存在同目录 `<文件名>.<游戏>.npz`，查询向量保存在 `<文件名>.queries.jsonl`；旧歌曲 JSONL 缓存可读取并在后台更新时迁移，原文件保留 |
| `song_search_embedding_threshold` | embedding 命中阈值，默认 `80.0` |
| `song_search_embedding_rebuild_batch_size` | rebuild embedding 时每批请求条数，默认 `32`；如调大 TEI `--max-client-batch-size` 可同步调大 |
| `song_search_reranker_enabled` | 是否启用查歌 reranker 精排，默认 `false` |
| `song_search_reranker_endpoint` | 本地 reranker HTTP 端点，兼容 Hugging Face TEI `/rerank`，默认 `http://127.0.0.1:11435/rerank` |
| `song_search_reranker_model` | reranker 模型名，例如 `Alibaba-NLP/gte-multilingual-reranker-base` / `bge-reranker-v2-m3` |
| `song_search_reranker_threshold` | reranker top1 最低分，默认 `0.0` |
| `song_search_reranker_min_margin` | reranker top1/top2 最小分差，默认 `0.0` |
| `ONEBOT_ACCESS_TOKEN` | OneBot 鉴权 Token |
| `PLAYWRIGHT_GPU_MODE` | 渲染服务模式：`auto`（默认，硬件不可用时回退）、`cpu`、`gpu`（硬件失败则拒绝启动）；通过 Compose 环境传给渲染服务 |

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

如果在宿主机上测试，可使用 `http://127.0.0.1:11434/embed` 和 `http://127.0.0.1:11435/rerank`。如果使用 Ollama embedding endpoint，请把 `song_search_embedding_endpoint` 改成对应的 `/api/embed` 地址。切换 embedding 模型或端点后，后台自动重新生成歌曲向量，旧查询向量不会混用；也可手动执行 `/admin.search embedding rebuild <game>`。

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

启用 embedding 后，bot 启动时会在后台构建本地已收录游戏的歌曲向量，并每 30 秒检查曲库修订号；后台失败会重试，不阻塞启动和普通查询。相同模型与端点下只对新增或文本变化的歌曲推理，其余向量直接复用。文件原子替换，构建失败保留原文件；过期歌曲向量不参与搜索。

歌曲向量索引保存在内存中，文件变更后重新加载。新输入第一次仍需推理，相同输入的并发请求共用一次推理，后续查询复用缓存。查询向量按模型、端点和全半角统一后的输入隔离，最多缓存 512 条，并写入歌曲向量文件旁的 `<文件名>.queries.jsonl`，重启后可复用。无需 Redis。

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
