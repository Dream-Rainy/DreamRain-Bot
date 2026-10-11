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
- 自然语言查歌：发送 `conflict是什么歌？`。有多个匹配时，一条消息按乐曲分组列出游戏收录，选项序号在整张列表中连续编号；回复一个序号即可选择歌曲和游戏，无需再输入完整命令。同名但未确认关联的作品分组显示，列表最多展示 10 个收录，30 秒未回复会取消；游戏名仅在该游戏的全部候选中只有一条且已展示时可直接选择。选曲和别名添加的问询只消费当前支持的选择回复和 `取消` / `cancel`；发送其他文本会静默结束旧问询，并按正常规则处理，可直接发送新命令或新的自然语言查询。
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

#### admin.alias 管理命令

以下命令均要求 `SUPERUSER`。发送 `/admin.alias` 可查看简短帮助。尖括号表示必填参数，方括号表示可选参数；示例中的编号、版本和来源记录键均需替换为实际输出。

| 操作方式 | 命令 | 生效方式 |
| --- | --- | --- |
| 查看数据 | `pending`、`show`、`candidates`、`imports` | 只读取数据 |
| 提交维护请求 | `retract`、`replace`、`block`、`unblock`、`relink`、`map` | 返回请求编号，审核通过后生效 |
| 审核请求 | `approve`、`reject`、`confirm` | 当场完成审核；批准时应用请求中的操作 |
| 直接管理 | `decide`、`source`、`sync` | 当场执行，不再创建待审请求 |

提交者及共同提交者不能审核自己的请求，批准和驳回均受此限制，包括管理员。管理员提交的维护请求需要另一位 `SUPERUSER` 审核；重复提交而成为共同提交者也不能自审。

**先区分参数中的 ID 和版本：**

| 参数 | 含义与获取方式 |
| --- | --- |
| 请求 ID | 待审核操作的编号，例如 `pending` 中的 `#42`；用于 `show/approve/reject/confirm` |
| 请求版本 | 请求的版本，例如 `#42 v1` 中的 `1`；从 `show` 获取，用来避免对已变化或已处理的请求重复决策 |
| 证据 ID | 某一来源的一条别名或标题证据的数据库编号；用于 `retract/replace`，不是请求 ID |
| 歌曲 ID | 日常查歌使用的公开 ID；舞萌/中二为原生歌曲 ID，其他游戏为导入后的稳定收录 ID |
| 内部收录 ID | 持久曲库中 `GameSong` 的编号；用于 `relink` 和 `map bind`。可从 `/arcade.alias <game> <歌曲ID或名称>` 输出的“内部收录 #编号”获取 |
| 候选 ID 与版本 | 系统生成的作品关联候选的 `id` 和 `version`；从 `candidates` 获取，用于 `decide` |
| 目标版本 JSON | 请求涉及的歌曲、作品、证据、来源等对象的当前版本集合；从 `show` 的“目标版本”一行完整复制，用于 `confirm` |

请求 ID、证据 ID、候选 ID 是不同表的编号，即使数字相同也不能互换。公开歌曲 ID 与内部收录 ID 对部分游戏可能相同，但不能据此假定所有游戏都相同。

##### 查看和审核请求

**`pending [上一页末尾请求ID]`：查看待审列表。**

每页最多 20 条可见的待审核请求，显示曲名、别名、范围和请求版本。省略参数从第一页开始；分页参数是上一页最后一个请求的 ID，不是页码。只有还有结果时才显示下一页命令，可直接复制发送。

```text
/admin.alias pending
/admin.alias pending 42
```

第二条从请求 ID 大于 `42` 的记录继续读取。列表中自己的请求也可能可见，但不能由自己审核。

**`show <请求ID>`：查看完整请求。**

显示操作类型、内容、状态、请求版本、提交理由、影响游戏、是否可审核、同名候选、当前目标版本 JSON 和处理理由。审核前用它核对目标与范围。

```text
/admin.alias show 42
```

“可审核”为 `False` 时，应检查是否为本人或共同提交的请求、权限不足，或者请求已处理。“同名候选”用于判断别名碰撞，不表示这些候选已被自动合并。

**`approve <请求ID> <版本> <理由>`：批准请求。**

版本填 `show` 中的请求版本，理由必填，可以包含空格。批准后应用新增别名、撤销证据、封禁或关联等对应操作；已经处理、请求版本不符或目标变化时会拒绝执行。

```text
/admin.alias approve 42 1 已核实曲名及别名范围
```

**`reject <请求ID> <版本> <理由>`：驳回请求。**

参数与 `approve` 相同。驳回后请求结束，不应用其中的操作；它不会撤销已经生效的别名。

```text
/admin.alias reject 43 1 别名指向错误歌曲
```

**`confirm <请求ID> <版本> <目标版本JSON> <理由>`：目标变化后重新确认并批准。**

若批准时提示 `TARGET_CHANGED`，说明从提交到审核期间，目标歌曲、作品、证据或来源等发生变化。先重新 `show`，核对新的影响与冲突，再将“目标版本”一行的完整 JSON 粘贴到命令中。

```text
/admin.alias show 42
/admin.alias confirm 42 1 <原样复制show输出的目标版本JSON> 已核实变化后的目标
```

第二条中的尖括号部分是粘贴位置，不要照字面发送。JSON 必须是完整对象，不能删字段、加省略号或在外面再包引号；使用 `show` 提供的不含格式化空格的紧凑输出。请求版本和 JSON 中的目标版本是两种不同参数。`confirm` 仍检查权限、自审限制和请求状态，也会拒绝再次发生变化的目标。

##### 维护别名与证据

以下操作先返回“已提交请求 #编号”，仍需另一位管理员用 `show` 和 `approve` 审核。

**`retract <证据ID> <理由>`：撤销一条证据。**

用于纠正某个来源提供的错误别名。批准后将指定证据标记为已撤销，保留历史记录；其他来源的同名证据仍可能使这个别名有效。

```text
/admin.alias retract 16588 该来源的别名对应错误歌曲
```

证据 ID 可从请求详情的同名候选 `evidence_ids` 辅助定位。当前合并来源后的别名展示不会逐条显示证据编号；需要核对来源、范围和编号时，可通过 SDK 或数据库读取证据详情，不能把请求编号当作证据编号。

**`replace <证据ID> <game> <歌曲ID> <work|game_song> <新别名>`：撤销旧证据并添加替代别名。**

`game` 和歌曲 ID 指定新别名的目标，歌曲 ID 使用日常查询的公开 ID；`work` 作用于该作品的所有已关联游戏收录，`game_song` 只作用于指定收录。批准时撤销旧证据，并创建一条经过审核的社区别名证据，操作在同一事务内完成。

```text
/admin.alias replace 16588 sdvx 5459 game_song 修正后的简称
/admin.alias replace 16588 maimai 1451 work 超越之光
```

两条是不同用法的独立示例，不应对同一旧证据连续照抄执行。此命令仍需显式填写范围；它没有沿用 `arcade.alias add` 的自动范围推断。新别名是最后一个参数，可以包含空格；此处不需要用引号包住，输入的引号会成为别名内容。命令没有额外的理由参数。

**`block <game> <歌曲ID> <别名>`：对一个作品封禁指定别名。**

游戏和公开歌曲 ID 用于定位作品。批准后建立作品级规则，使该作品所有关联收录中的同名证据不再生效，覆盖各来源；不是仅封禁参数中指定的游戏，也不会对其他作品封禁同名别名。

```text
/admin.alias block maimai 1451 错误简称
```

封禁按标准化后的文本匹配，保留原有证据。适合多个来源都提供了同一个错误简称，或者不希望它被后续来源同步重新带回的情况。最后的别名可以包含空格，不需要引号；命令没有理由参数。

**`unblock <game> <歌曲ID> <别名>`：解除作品级封禁。**

参数与 `block` 相同，审核通过后解除对应规则。它不会重新创建证据；实际恢复的仍是来源已启用、来源记录存在且未被撤销等条件均满足的证据。

```text
/admin.alias unblock maimai 1451 错误简称
```

##### 关联跨游戏作品

**`relink <merge|split> <内部收录ID,内部收录ID> <理由>`：提交人工作品关联调整。**

ID 列表使用内部收录 ID，以英文逗号分隔，不能重复，逗号周围不要加空格。理由必填。

- `merge`：将这些收录所属的作品合并。合并范围包括原作品中的其他收录，并非只移动列出的几首歌；`work` 范围别名会随着新关联共享。
- `split`：将列出的收录一起移到一个新作品。它们必须来自同一个原作品，而且原作品至少保留一个未列出的收录；不是把每个 ID 分别拆成一个作品。

```text
/admin.alias relink merge 2510,3828 已核实为同一作品的跨游戏收录
/admin.alias relink split 3828 该收录是不同版本作品，应与原作品分离
```

第二条只有在 `3828` 所属作品还有其他收录时才可执行。这两种操作都是待审请求，审核通过后生效；原作品的封禁规则会保留到合并或拆分后的对应作品中。

**`candidates [上一页末尾候选ID]`：查看系统生成的待定作品关联。**

每次最多 20 条，按候选 ID 升序返回 JSON 数组。可查看 `id`、`version`、`left_id`、`right_id`、`reason` 和 `target_versions` 等字段。`left_id/right_id` 是内部收录 ID，不是请求 ID。

```text
/admin.alias candidates
/admin.alias candidates 17
```

第二条查看候选 ID 大于 `17` 的记录。当前输出没有自动生成的下一页命令，需要取数组最后一条的 `id` 继续查询；返回 `[]` 表示没有更多待定候选。

**`decide <候选ID> <版本> <accept|reject> <理由>`：直接处理作品关联候选。**

ID 和版本从 `candidates` 获取，理由必填。`accept` 合并候选两侧所属作品；`reject` 拒绝这对关联，自动匹配会考虑该拒绝记录。此命令直接执行管理员决策，不创建另一个待审请求。

```text
/admin.alias decide 17 1 accept 已确认两侧为同一作品
/admin.alias decide 18 1 reject 同名但曲师和作品不同
```

版本或目标已变化时，重新查看候选并核对曲库状态；候选不是别名请求，不能用 `confirm` 代替 `decide`。

##### 同步与导入身份处理

**`sync <game>`：立即同步指定游戏曲库。**

`game` 使用游戏代码，例如 `maimai`、`chunithm`、`sdvx`。舞萌和中二走各自数据源同步，成功后显示本地曲库歌曲数量；其他支持的游戏导入通用街机曲库，显示新增、更新、待定和无效记录数量。支持的游戏可先通过 `/arcade.list` 查看。

```text
/admin.alias sync maimai
/admin.alias sync sdvx
```

同步会更新持久曲库和来源提供的别名，并可能产生作品关联候选或待定导入记录。它不等于批准用户提交的别名请求。

**`imports <game>`：查看最近一次通用曲库导入报告。**

返回 JSON，包括 `created`、`updated`、`unchanged`、`withdrawn`、`pending`、`invalid`、`song_ids` 和同步版本等信息。`pending` 中的 `external_key`、标题和原因用于定位身份不确定的来源记录。

```text
/admin.alias imports sdvx
```

当前命令固定读取 `provider=arcade_songs`、`namespace=default` 的报告，没有额外的来源选择参数。因此不能用它查看舞萌/中二原生同步的所有报告；无对应导入报告时返回 `null`。导入报告的 `pending` 是来源身份待定项，与 `/admin.alias pending` 中的维护请求是不同列表。

**`map <game> <provider> <namespace> <external_key> <bind|new|reject> <内部收录ID或-> <理由>`：提交来源记录的身份决策。**

| 参数 | 含义 |
| --- | --- |
| `game` | 来源记录所在的游戏代码 |
| `provider` | 导入提供方；当前通用曲库通常为 `arcade_songs` |
| `namespace` | 同一提供方下的记录命名空间；当前通用曲库通常为 `default` |
| `external_key` | 导入报告中的来源记录键，可能是身份摘要，不是临时枚举 ID；原样复制 |
| `bind` | 绑定到同游戏内已有收录，下一参数填内部收录 ID |
| `new` | 确认为新收录并创建作品，下一参数必须填 `-` |
| `reject` | 拒绝该来源记录，下一参数必须填 `-` |
| 理由 | 说明人工判断依据，可以包含空格 |

```text
/admin.alias map sdvx arcade_songs default <external_key> bind 3828 核实为现有收录
/admin.alias map sdvx arcade_songs default <external_key> new - 已确认是新增曲目
/admin.alias map sdvx arcade_songs default <external_key> reject - 来源记录有误
```

将 `<external_key>` 替换为报告中的实际键后再发送。命令从已保存的最新抓取快照读取原文，无需粘贴整首歌曲的 JSON。记录必须在快照中唯一存在；`bind` 不能跨游戏，批准后还会更新目标收录的曲库信息及对应来源证据。`reject` 会撤下该来源引用和证据；如果收录已没有其他有效来源引用，该收录也会变为不活跃。三种决策都先创建待审请求。

##### 配置别名来源

**`source <来源键> <game或global> <enable|disable>`：直接启用或禁用来源。**

来源键是别名展示中的完整名称，例如 `lxns:maimai`、`dxrating:maimai`、`yuzuchan:maimai`。第二个参数表示来源所属游戏；`global` 表示来源没有限定游戏，不是修改一个现有来源的作用范围。

```text
/admin.alias source lxns:maimai maimai disable
/admin.alias source lxns:maimai maimai enable
```

已知来源的外部别名由 arcade-helper 同步，未知外部来源默认禁用。禁用后，该来源的证据不再生效，但记录仍保留；启用后，满足其他有效条件的证据可重新生效。此命令当场更新，不需另行审核，也不会代替 `sync` 抓取新的数据。

现有来源的所属游戏和类型不可更改，需填写其原有游戏或 `global`；命令保留现有来源的类型及导入信任设置。未知来源会以指定归属创建为外部来源，命令本身不会将其升级为可信导入。

##### 兼容入口与常用流程

当前实现还接受以下两个未列在管理员简短帮助中的入口：

```text
/admin.alias add [游戏] <曲名/已有别名/ID> <新别名>
/admin.alias request <请求ID>
```

`add` 与 `/arcade.alias add` 共用提交逻辑，仍需审核，指定游戏自动使用 `game_song`，省略游戏使用 `work`；例如 `/admin.alias add "Transcend Lights" 超越灯`。`request` 与管理员 `show` 共用详情逻辑，例如 `/admin.alias request 42`。撤回本人请求的入口仍为 `/arcade.alias withdraw <请求ID> <版本>`，`admin.alias` 没有管理员撤回他人请求的命令；拒绝待审请求使用 `reject`。

审核用户新别名的常用顺序：

```text
/admin.alias pending
/admin.alias show 42
/admin.alias approve 42 1 已核实
/arcade.alias maimai 1451
```

管理员维护别名时，先用 `retract/replace/block/unblock/relink/map` 提交，再由另一位管理员按上述流程审核。作品关联候选直接走 `candidates` → `decide`；通用曲库身份待定项走 `imports` → `map` → 另一位管理员审核。

旧 `/admin.search accept/reject` 已停用：舞萌、中二历史搜索候选可用 `/admin.search submit <旧记录编号>` 转成新版待审请求；其他游戏需核对当前 ID 后重新 `add`。搜索历史的查看、导入和导出仍可用，但不直接使别名生效。

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
