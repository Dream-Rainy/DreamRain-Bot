# 部署与配置

[返回 README](../README.md)

以下命令均在仓库根目录执行。

## 完整部署（Docker Compose）

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

### 生产环境数据库迁移

更新镜像或插件后，应在启动 Bot 前执行迁移。若日志出现 `目标数据库未更新到最新迁移, 是否更新? [y/N]`，说明数据库仍有未执行的迁移；后台容器无法回答确认提示，会因 `click.exceptions.Abort` 而启动失败。

先备份数据库，并确保迁移使用的是本次部署的新镜像。停止旧 Bot 后，依次执行以下命令；只有上一条成功退出后才执行下一条，迁移或检查失败时停止部署并查看日志：

```powershell
docker compose --env-file .env.prod -f docker-compose.yml stop dreamrain-bot
docker compose --env-file .env.prod -f docker-compose.yml run --rm -T dreamrain-bot /app/.venv/bin/python scripts/orm.py upgrade
docker compose --env-file .env.prod -f docker-compose.yml run --rm -T dreamrain-bot /app/.venv/bin/python scripts/orm.py check
docker compose --env-file .env.prod -f docker-compose.yml up -d dreamrain-bot
```

`run --rm -T` 使用服务的环境配置、数据卷和容器入口创建一次性容器，并禁用伪终端。`scripts/orm.py upgrade` 在项目插件加载完成后直接执行 `nonebot-plugin-orm` 迁移，无需回答 Bot 启动时的确认提示。此操作只需在部署时执行一次；生产环境保留默认启动检查。

不要通过设置 `ALEMBIC_STARTUP_CHECK=false` 解决生产容器的交互问题：当前插件版本会在关闭检查后自动同步数据库结构，并非单纯跳过确认。

可将容器命令中的 `upgrade` 替换为 `current`、`history` 查看迁移状态；本地环境可直接运行：

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

## Playwright GPU 与字体

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

## Playwright 二进制图片返回

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
| `song_search_reranker_threshold` | reranker top1 最低分，默认 `0.0`；纯语义候选须设置正值并通过此门槛 |
| `song_search_reranker_min_margin` | reranker top1/top2 最小分差，默认 `0.0` |
| `ONEBOT_ACCESS_TOKEN` | OneBot 鉴权 Token |
| `PLAYWRIGHT_GPU_MODE` | 渲染服务模式：`auto`（默认，硬件不可用时回退）、`cpu`、`gpu`（硬件失败则拒绝启动）；通过 Compose 环境传给渲染服务 |

完整配置项参见 [.env.example](../.env.example)。
