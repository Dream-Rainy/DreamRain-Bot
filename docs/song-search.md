# 查歌与搜索配置

[返回 README](../README.md)

以下命令均在仓库根目录执行。

## 查询与选曲

- 通用街机曲库：`/arcade.list` 查看支持的游戏。启动时的首次后台更新自动导入所有可见通用曲库，之后随已有自动同步任务更新；初始化尚未完成时，指定游戏查询会按需准备该游戏。可用 `/arcade.song sdvx FLOWER` 查询歌曲、`/arcade.games FLOWER` 查询作品收录、`/arcade.artist sdvx xi` 查询曲师作品；管理员仍可用 `/admin.alias sync sdvx` 立即重试或刷新。来源失败保留已发布数据，不影响其他来源；跨游戏范围尚不完整时不推断唯一游戏。跨游戏查询按确认的作品关联展开，不仅凭同名标题判断。

- 自然语言查歌：发送 `conflict是什么歌？`。有多个匹配时，一条消息按乐曲分组列出游戏收录，选项序号在整张列表中连续编号；回复一个序号即可选择歌曲和游戏，无需再输入完整命令。同名但未确认关联的作品分组显示，列表最多展示 10 个收录，30 秒未回复会取消；游戏名仅在该游戏的全部候选中只有一条且已展示时可直接选择。选曲和别名添加的问询只消费当前支持的选择回复和 `取消` / `cancel`；发送其他文本会静默结束旧问询，并按正常规则处理，可直接发送新命令或新的自然语言查询。

## 匹配规则

查歌先尝试 ID、曲名和已生效别名的精确或归一化匹配。归一化后 1–4 个字符的短查询只做文本检索：保留完整词、完整拼音缩写和完整拼音；1–2 个字符不扩展错字或词片段，3–4 个字符只允许完整目标或完整英文词的一次编辑。不对短查询调用 BM25、embedding 或 reranker。已收录的梗别名仍可精确查询，数字 ID 与数字曲名并存，难度/版本前缀仍只在无结果时重试一次。

较长查询保留模糊、拼音和罗马音匹配；有实际输入覆盖的多关键词查询才进入 BM25。“曲师＋曲名/单个别名”可以组合，不能把多个别名或拼音里的碎片拼成命中。BM25 需要覆盖至少 60% 的查询词项，且包含全部有效英文关键词；模糊文本匹配也不能忽略额外的有效英文关键词。列表中的百分数是排序分数，不是命中概率；精确匹配由匹配类型判定。

指定游戏和全游戏查询共用一条链路：限定游戏范围 → 精确身份解析 → 轻量文本候选 → 按已确认的作品关系去重 → 必要时进行模型验证 → 返回游戏收录。不会只因曲名相同就自动关联作品；maimai/CHUNITHM 仍使用原生歌曲 ID，其他游戏使用内部收录 ID。文本索引与后台预热共享，完整谱面只在候选接受后按需补全。

多个作品的 BM25 得分接近时，可由 reranker 验证；同作品的多个游戏收录不会作为竞争项。每次最多验证 10 个作品、一个批次；跨游戏向量检索最多并发两个游戏，共用一次输入向量推理。reranker 未执行时可以继续尝试 embedding，保留配置的相似度阈值及不同作品之间的最小分差检查。模型明确拒绝即返回未找到，不恢复旧候选；缓存或服务不可用时仅保留该游戏已通过文本规则的候选。别名提交使用同一文本核心，关闭语义兜底，非精确目标仍须明确选择并提交审核。

没有文本依据的纯语义结果，必须同时启用 embedding、reranker，并将已有 `song_search_reranker_threshold` 设为正值；包括单个候选，也要通过 reranker 的绝对分数门槛。默认 `0.0` 只用于文本候选排序，不授权纯语义猜测。阈值须用实际有效查询和无关查询校验，不能将分数当作概率；相对分差也不能代替绝对门槛。两项推理功能默认关闭。

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

## 搜索配置参考

| 变量 | 说明 |
| --- | --- |
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
