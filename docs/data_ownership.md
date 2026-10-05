# 数据角色与表级所有权

本文件冻结 B5-a1 的现状命名，不迁移物理路径、不改变任何既有读写路由，也不引入新的 schema 版本来源。

## 路径角色

| 角色 | 当前路径 | 当前语义 |
|---|---|---|
| `active_root` | `core/data` | 活跃存储根 |
| `backup_root` | `data`（`config.DATA_DIR`） | 备份/镜像存储根 |
| `active_central` | `core/data/bilibili_monitor.db` | 活跃中央投影库 |
| `backup_central` | `data/bilibili_monitor.db` | 备份中央快照库；现有 UI 查询仍读取此处 |
| `active_video` | `core/data/<BV>/<BV>.db` | 每视频权威明细库 |
| `mirror_video` | `data/<BV>/<BV>.db` | 每视频明细镜像库 |
| `viewer_db` | `<root>/<BV>/viewercount.db` | 在线人数附属快照库 |

`ui/database_query.py`、`ui/monitor/_service.py` 的 watch-list 兜底及 `ui/online_viewers_panel.py` 现有读取保持指向 `data/`；本包只显式记录角色，未变更调用实际读取的文件。

## 表级所有权矩阵

| 位置 | 表 | 所有权 / 重建状态 |
|---|---|---|
| 视频库 | `video_info` | 权威视频元数据明细 |
| 视频库 | `monitor_records` | 权威观测明细 |
| 视频库 | `predictions` | 权威单视频预测明细 |
| 视频库 | `weekly_scores`、`yearly_scores` | 权威单视频分数明细 |
| 视频库 | `danmaku_records` | 权威弹幕明细 |
| 视频库 | `crossing_events` | 权威过线事件明细 |
| 中央库 | `monitor_records`、`predictions`、`weekly_scores`、`yearly_scores` | 从视频库复制的中央投影 |
| 中央库 | `videos` | 中央自有汇总状态，暂不可重建 |
| 中央库 | `video_milestones` | 中央自有状态，暂不可重建 |
| 中央库 | `prediction_ensemble` | 中央自有状态，暂不可重建 |
| 中央库 | `algorithm_coherence` | 中央自有状态，暂不可重建 |

“中央投影”只描述已知明细副本的目标状态，不代表当前同步具备跨库原子性。`videos`、`video_milestones`、`prediction_ensemble` 与 `algorithm_coherence` 在证明可由权威明细完整重建前，均不得归类为可重建投影。

## 当前双写路径清单

- `core/database/video_db.py:882-902`：预测批量写入活跃视频库后写入视频镜像，随后经 `sync_predictions()` 写入中央库兜底。
- `ui/monitor/_prediction.py:477-486`：预测输出保存视频库后，再调用 `_sync_predictions_to_central()` 写入中央预测、集成与共识相关状态。
- `core/database/video_db.py` 的 `_execute_on_all()`：主视频库与镜像库的通用同步执行路径。
- `ui/monitor/_service.py`：监控观测先写视频库，再同步中央库。

这些路径是 B5-b 的治理输入；B5-a1 不删除、合并或改变它们。
