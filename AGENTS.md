# AGENTS.md

This file provides guidance to AGENTS when working with code in this repository.

## Agent Behavior

All changes **must be presented as a plan and explicitly confirmed by the user before execution**. Use this format:

```
## 执行计划

### 将要修改的文件
- `src/xxx.py` — [具体改动描述]

### 文档变更评估
- 是否需要更新文档：是 / 否
- 原因：[为什么需要/不需要]

是否同意执行？(yes/no)
```

Only update docs when: public API/function signatures change, user-visible commands change, install/build/run steps change, or config fields change. Never update docs for internal refactors, bug fixes, tests, or style changes.

When using matplotlib, **never add `fontfamily` to chart code** — fonts are set globally at the file level.

## Commands

```bash
# ── 日常开发 ──────────────────────────────────────────────────

# 安装依赖
uv sync

# 本地调试（终端交互，无需 Docker / QQ）
$env:ENABLE_CONSOLE_DEBUG = "1"; uv run bot.py
# 等待 "Running NoneBot..." 后输入命令，如 /mai.b50

# ── 完整验证 ──────────────────────────────────────────────────

# 启动完整开发栈（bot + postgres + playwright + napcat）
docker compose -f .\docker-compose-dev.yml up

# 仅重启 bot 容器（代码变更后）
docker compose -f ./docker-compose-dev.yml restart dreamrain-bot

# 查看 bot 容器启动日志
docker logs dreamrain-bot --tail 40

# ── 生产环境 ──────────────────────────────────────────────────

# 启动生产栈
docker compose up

# 构建镜像
docker build . -t dreamrain-bot
```

## Runtime Verification (Mandatory)

There are **two verification tiers**, used at different stages:

### Tier 1 — Automated Tests (pytest + NoneBug)

Use the official NoneBot testing path for feature work: `pytest` for unit/integration tests and `nonebug` for plugin-loading / matcher-level tests.

```powershell
uv run pytest tests/unit tests/integration tests/nonebot
```

**What it catches:**
- Import errors in `src/` files
- DB-backed service and adapter regressions
- Handler/matcher loading issues under NoneBot's test driver
- Pure logic regressions without starting the full Docker stack

### Manual Console Debug

Console debug remains useful for manual exploration, but it is not the primary automated test gate.

```powershell
$env:ENABLE_CONSOLE_DEBUG = "1"
uv run bot.py
```

Once the bot finishes loading (wait for `Running NoneBot...`), type commands directly:
```
/mai.b50
/mai.song テオ
/chuni.song 1
/acc help
```

### Tier 2 — Dev Stack (final verification before reporting complete)

After console debug passes, run the full Docker stack to verify the bot works with OneBot adapter + all services.

```powershell
docker compose -f .\docker-compose-dev.yml up 2>&1 | Select-String "dreamrain-bot"
```

If dev stack is already running, restart only the bot container to pick up code changes:
```bash
docker compose -f ./docker-compose-dev.yml restart dreamrain-bot
docker logs dreamrain-bot --tail 40
```

**What this catches that Tier 1 doesn't:**
- Package import issues specific to the Docker environment
- Plugin interaction issues (SAA + OneBot adapter integration)
- Bind-mount permission problems

**Watch the logs for:**
- **Import errors** — `ModuleNotFoundError`, `ImportError`
- **Plugin load failures** — NoneBot reports which plugins failed to load
- **Tracebacks** — any unhandled exceptions during startup
- **Key line**: `Loaded adapters: OneBot V11` — confirms adapter registered
- **Key line**: `Succeeded to load plugin "chiffon_bot"` — confirms our plugin loaded

A task is **not complete** until automated tests pass and the dev stack smoke test has been checked.

### Docker Desktop on Windows: dev entrypoint

Docker Desktop on Windows maps bind-mounted host files through a file sharing layer where recursive `chmod` can be very slow. `docker-compose-dev.yml` therefore runs `dreamrain-bot` as root and overrides the production `entrypoint.sh`, starting the bot directly with `uv run bot.py`.

Production images still use `entrypoint.sh` and the non-root `appuser` flow. Do not copy the dev compose root/entrypoint override into production compose files.

## Architecture

**NoneBot2** (v2.4.3) bot using **OneBot v11 adapter** for QQ as primary platform. Entry point is `bot.py` which registers adapters, loads plugins, and wires up the permission guard.

Multi-adapter support: additional adapters (Telegram, Discord, Kaiheila) can be enabled via environment variables (`ENABLE_TELEGRAM`, `ENABLE_DISCORD`, `ENABLE_KAIHEILA`). Messages are sent via **nonebot-plugin-send-anything-anywhere** (SAA) for platform-agnostic delivery.

### Plugin System

All plugins live in `src/plugins/` and are loaded via `nonebot.load_plugins("src/plugins")`. Some external NoneBot plugins are also loaded directly in `bot.py`.

Key plugins:

- **`chiffon_bot/`** — Main game tracking plugin for Maimai DX and CHUNITHM. Uses a layered domain architecture:
  - `app/commands/` — NoneBot command handlers (entry points); converts BotResponse → SAA messages
  - `domains/maimai/` and `domains/chunithm/` — Business logic, services, views, handlers (return BotResponse)
  - `infra/db/` — Tortoise ORM models and migrations
  - `infra/http/` — HTTPX client wrappers
  - `integrations/lxns/` — LXNS API integration (OAuth binding, score fetching)
  - `shared/` — Cross-domain utilities: BotResponse, DomainAdapter, song search

- **`priconne/`** — Princess Connect Re:Dive features (guild battle, arena, character guessing). Interfaces with the `autopcr` git submodule at `src/submodule/autopcr/`.

- **`permission_admin/`** — Global per-plugin, per-group permission control. Installs a matcher guard that runs before every NoneBot handler. Must be initialized after all plugins are loaded (see `bot.py`).

- **`pokepoke_miss/`** — Poke reaction handler.

- Several copied external plugins (fortune, tarot, repeater, wordle, githubcard, picstatus, crazy_thursday, pcrjjc).

### Configuration

Configuration is via `.env` (dev) or `.env.prod` (production) — NoneBot reads these automatically via `python-dotenv`.

Key config variables:
- `db_engine` — `sqlite` / `postgres` / `mysql`
- `db_credentials` — JSON object with DB connection params
- `lxns_api_key`, `lxns_base_url` — LXNS API access
- `lxns_oauth_redirect_uri` — OAuth callback URL
- `SUPERUSERS` — QQ user IDs with admin access
- `COMMAND_START` — Default `["/", ""]`; commands use `.` as separator (e.g., `/mai.b50`)
- `htmlrender_connect` — WebSocket URL for Playwright rendering service

### Database

Uses **Tortoise ORM** with async drivers (`asyncpg` for PostgreSQL, `aiosqlite` for SQLite). Schema migrations live in `src/plugins/chiffon_bot/infra/db/migrations/`. Alembic config is also present at `alembic.ini`.

### Rendering

Image/HTML rendering uses **nonebot-plugin-htmlrender** which connects to a Playwright service. In Docker Compose, this is the `playwright` container on `ws://playwright:3000`.

### Message Layer: BotResponse + SAA

Domain handlers return `BotResponse` (a platform-agnostic dataclass: `text`, `image`, `reply_to`, `suffix`). The command layer converts it via `finish_with()` / `send_with()` from `app/commands/_response.py`, which uses SAA's `MessageFactory` to build adapter-specific messages.

When writing new handlers:
- Return `BotResponse` — never import `Message`/`MessageSegment` from any adapter
- In command handlers, use `finish_with(response)` / `send_with(response)` instead of `matcher.finish(msg)`

`app/commands/_response.py` is the **only** place where SAA imports live.

### Internal Adapter Bridge

Internal plugins should prefer `src.plugins.platform_adapter` for adapter-neutral event context and sending helpers. Use `PlatformContext.from_event(event)` instead of checking OneBot event classes directly, and route transitional OneBot-style sends through `send_to_event()`, `send_group()`, or `send_private()`.

`priconne.compat` is the compatibility entry point for migrated Koishi/OneBot-style priconne modules. New or actively refactored priconne code should depend on `platform_adapter` or `priconne.compat`, not import adapter-specific event classes in feature modules unless the feature is explicitly OneBot-only.

### Package Management

Uses **uv** (Astral). `uv.lock` pins exact versions. Run `uv sync` to install; `uv run` to execute within the venv.
