# B5-b 投影与重建契约

本设计冻结后续实施的行为边界。本包只记录契约和测试，不创建 outbox、不改 schema，亦不改生产写路由。

## 权威来源、目标与幂等键

| Stream | 权威来源 | 中央投影目标 | 稳定幂等键 |
|---|---|---|---|
| monitor | 每视频 `monitor_records` | `monitor_records` | `(bvid, source_row_id)`，不得依赖秒级 timestamp |
| predictions | 每视频 `predictions` | `predictions` | `(bvid, algorithm, target_threshold)` |
| scores | 每视频 `weekly_scores`、`yearly_scores` | 同名中央表 | `(bvid, timestamp)` |
| milestones | 新增每视频权威 milestones 表 | `video_milestones` | `(bvid, period)` |
| ensemble | 新增每视频权威 ensemble 表 | `prediction_ensemble` | `(bvid, source_row_id)` |
| coherence | 新增每视频权威 coherence 表 | `algorithm_coherence` | `(bvid, source_row_id)`，或 `(bvid, cycle_id, algorithm)` |

`milestones`、`ensemble` 和 `coherence` 的权威表在本设计冻结时尚不存在，因此当前中央数据不可完整重建。

## Outbox 契约

后续版本在每视频权威库创建：

```text
projection_outbox(
  event_id PRIMARY KEY, stream, entity_key, operation,
  payload/source_row_id, created_at, delivered_at NULL,
  attempt_count, last_error
)
```

业务数据写入与 outbox 插入必须位于同一 SQLite 事务。投递语义是 at-least-once；中央端必须通过以上幂等键 upsert。

## 投影器与崩溃恢复

投影器按 `event_id` 顺序读取未投递事件，在中央库一个事务内执行幂等 upsert。中央事务提交后才回标源 outbox 的 `delivered_at`。中央提交与回标之间崩溃时，重启必须重放该事件，且中央幂等写不得产生重复。

## 退出契约

进入 STOPPING 后拒绝新任务，drain 已开始的本地事务。投影器可以完成投递，或留下可恢复 pending 事件；最终快照必须位于本地事务完成后执行。下次启动继续投递 pending 事件。

## 快照契约

快照必须使用 SQLite `Connection.backup()` 写入临时文件，执行 `quick_check` 后通过 `os.replace` 原子替换。禁止裸 `shutil.copy2` 快照及手工拼接 WAL 文件。
