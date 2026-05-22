# DreamRain-Bot

基于 NoneBot2（OneBot V11）的 QQ 机器人，偏向音游与公会工具场景。

## 功能总览（完整清单）

> 说明：以下按当前代码实际加载的插件列出。

### 一、核心功能插件（`src/plugins`）

1. **chiffon_bot（音游核心）**
   - `mai.*`（maimai）：查歌、别名、随机歌、b50/r50、个人信息、趋势图、缓存清理、曲库更新
   - `chuni.*`（CHUNITHM）：查歌、别名、随机歌、缓存清理、曲库更新
   - `acc.*`（账号系统）：friend_code 绑定、OAuth 绑定、解绑、默认账号管理、账号列表
   - `event.*`（活动系统）：活动创建/绑定/解绑、队伍创建/加入/退出/改名/解散、榜单/提交/曲目管理
   - 自然语言：跨游戏“XXX是什么歌”、随机点歌、活动榜单快捷触发
   - 额外：`断网 / 网炸了?` 网络状态截图

2. **priconne（公主连结功能集）**
   - 自动报刀、会战状态与预约管理
   - 分刀与作业相关查询
   - Arena 相关查询/推送
   - 助战与 Box 查询
   - 猜头像、猜角色等小游戏
   - 切噜语等实用指令

3. **permission_admin**
   - SuperUser 群级插件开关控制（`perm` 指令）
   - 支持当前群开关、跨控制群远程开关、禁用白名单查看与清理

4. **nonebot_plugin_pcrjjc（本地拷贝版）**
   - PCR 竞技场查询、绑定、推送与管理指令

5. **nonebot_plugin_githubcard**
   - 识别 GitHub 仓库链接并自动发送仓库卡片图

6. **nonebot_plugin_fortune**
   - 今日运势/抽签，主题切换与主题管理

7. **nonebot_plugin_tarot**
   - 占卜、塔罗牌抽取、群聊转发模式开关

8. **nonebot_plugin_wordle**
   - 猜单词（Wordle）游戏（支持词典与长度参数）

9. **nonebot_plugin_repeater**
   - 复读机（按群配置、重复阈值触发）

10. **nonebot_plugin_crazy_thursday**
    - 疯狂星期四文案随机回复（中/日触发）

11. **nonebot_plugin_picstatus**
    - 图片化运行状态面板（系统状态查询）

12. **pokepoke_miss**
    - 戳一戳回复与 poke 帮助

13. **platform_adapter**
    - 内部跨平台适配工具层（供插件调用，不直接提供用户命令）

### 二、外部直接加载插件（`bot.py`）

- `nonebot_plugin_analysis_bilibili`：B 站链接解析
- `nonebot_plugin_memes`：表情包制作
- `nonebot_plugin_whateat_pic`：吃什么图片推荐
- `nonebot_plugin_wordcloud`：词云生成
- `nonebot_plugin_guess_song`：猜歌功能
- `nonebot_plugin_saa`：跨平台消息发送能力（基础依赖）

## 常用命令示例

- `/mai.help`、`/mai.song 1`、`/mai.b50`
- `/chuni.help`、`/chuni.song 1`
- `/acc.help`、`/acc.bind <friend_code>`
- `/event.help`
- `/perm`
- `/今日运势`、`/占卜`、`/猜单词`

## 运行（简要）

1. 安装依赖：`uv sync`
2. 本地调试：`ENABLE_CONSOLE_DEBUG=1 uv run bot.py`