# Song Search Quality Workflow

乐曲搜索可以把每次最终匹配结果追加到 JSONL 历史文件，方便从真实查询里挑错例，再把错例复制到固定回归集。

## 开启历史记录

```powershell
$env:SONG_SEARCH_AUDIT_LOG = "1"
$env:SONG_SEARCH_AUDIT_PATH = "data/chiffon_bot/song_search_history.jsonl"
uv run bot.py
```

`SONG_SEARCH_AUDIT_PATH` 可省略，默认写入 `data/chiffon_bot/song_search_history.jsonl`。记录失败不会影响正常查歌。

每行是一条可编辑 JSON：

```json
{"query":"eris","game":"maimai","results":[{"rank":1,"song_id":1002,"title":"ERIS -Legend of Gaidelia-","score":99.0,"match_type":"fuzzy_title","matched_text":"ERIS -Legend of Gaidelia-"}],"expected_top_id":null,"failure_reason":null,"notes":null}
```

发现错例后，可以直接补字段：

```json
"expected_top_id": 1002,
"should_not_top_ids": [1001],
"failure_reason": "short_ascii_cross_token_compact_match",
"notes": "eris 不应被 Summer is over 的跨词 compact 命中压过"
```

## 筛选历史

```powershell
uv run python tools/song_search_eval.py data/chiffon_bot/song_search_history.jsonl --suspicious
uv run python tools/song_search_eval.py data/chiffon_bot/song_search_history.jsonl --empty-only
uv run python tools/song_search_eval.py data/chiffon_bot/song_search_history.jsonl --failed-only --annotated-only
uv run python tools/song_search_eval.py data/chiffon_bot/song_search_history.jsonl --reason short_ascii_cross_token_compact_match
```

## 固化回归

确认重要错例后，把对应 JSONL 行复制到 `tests/fixtures/song_search_quality_cases.jsonl`，并填写期望字段。然后运行：

```powershell
uv run pytest tests/unit/test_song_search_quality.py
```

固定回归集只放稳定、确认过的错例；大量待观察样本保留在本地历史文件里即可。
