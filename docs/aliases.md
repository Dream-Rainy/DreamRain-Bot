# 歌曲别名与审核

[返回 README](../README.md)

以下命令均在仓库根目录执行。

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

## 别名网页工作台

采用 LuckPerms 式独立编辑器：在独立服务器部署 `arcade-helper[web]` 的网页/中继，机器人设置 `alias_web_relay_url=https://编辑器域名`、`alias_web_relay_token=<中继服务密钥>`，只发起出站 HTTPS/WSS 连接，不注册别名网页 HTTP 路由。默认 `alias_web_enabled=true`；中继未配置时提示补全配置，不提供直连方式。`alias_web_enabled=false` 可关闭编辑器命令。

私聊 `/arcade.editor` 获取临时链接，打开即可进入工作台，无需再次发送确认指令。机器人在创建链接时绑定真实平台账号，浏览器自动证明持有链接密钥；密钥仅放在 URL fragment，页面读取后立即清除地址栏中的凭据。链接最长一小时，是创建者身份的临时凭证，拿到链接的人可以使用该身份，请勿转发。审核权限实时沿用 `SUPERUSERS`，禁止审核自己或共同提交的请求。

页面支持按曲名、ID、别名搜索和选择收录，提交共享或单收录别名、查看和撤回自己的请求；管理员可核对影响游戏、同名候选和来源原文并审核，处理跨游戏匹配及 arcade-songs 待定映射，以及提交证据撤回、替换、屏蔽、恢复和作品关系调整申请。所有维护申请继续由另一位管理员审核，目标变化时需明确确认当前版本，过期来源观察需重新选取。

部署说明和 Docker/Caddy 模板见 [arcade-helper 独立编辑器部署](../src/submodule/arcade-helper/README.md#独立别名网页与中继)。中继不接数据库、不保存明文业务快照，网页资源无需 CDN 或前端构建。断线、刷新、退出或重启后需新建会话；若刚提交操作，重连后先检查状态。会话保存在当前进程，机器人与中继均使用单进程部署。

## admin.alias 管理命令

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

### 查看和审核请求

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

### 维护别名与证据

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

### 关联跨游戏作品

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

### 同步与导入身份处理

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

### 配置别名来源

**`source <来源键> <game或global> <enable|disable>`：直接启用或禁用来源。**

来源键是别名展示中的完整名称，例如 `lxns:maimai`、`dxrating:maimai`、`yuzuchan:maimai`。第二个参数表示来源所属游戏；`global` 表示来源没有限定游戏，不是修改一个现有来源的作用范围。

```text
/admin.alias source lxns:maimai maimai disable
/admin.alias source lxns:maimai maimai enable
```

已知来源的外部别名由 arcade-helper 同步，未知外部来源默认禁用。禁用后，该来源的证据不再生效，但记录仍保留；启用后，满足其他有效条件的证据可重新生效。此命令当场更新，不需另行审核，也不会代替 `sync` 抓取新的数据。

现有来源的所属游戏和类型不可更改，需填写其原有游戏或 `global`；命令保留现有来源的类型及导入信任设置。未知来源会以指定归属创建为外部来源，命令本身不会将其升级为可信导入。

### 兼容入口与常用流程

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

## 首次升级与旧别名迁移

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
