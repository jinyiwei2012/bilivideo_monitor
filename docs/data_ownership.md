# 数据角色与表级所有权

本文件冻结 B5-b 前的现状与目标所有权契约。本包不迁移物理路径、不改变任何既有读写路由，也不引入新的 schema 版本来源。

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

## 表级所有权矩阵：现状

| 位置 | 表 | 所有权 / 重建状态 |
|---|---|---|
| 视频库 | `video_info` | 权威视频元数据明细 |
| 视频库 | `monitor_records` | 权威观测明细 |
| 视频库 | `predictions` | 权威单视频预测明细 |
| 视频库 | `weekly_scores`、`yearly_scores` | 权威单视频分数明细 |
| 视频库 | `danmaku_records` | 权威弹幕明细 |
| 视频库 | `crossing_events` | 权威过线事件明细 |
| 中央库 | `monitor_records`、`predictions`、`weekly_scores`、`yearly_scores` | 从视频库复制的中央投影 |
| 中央库 | `videos` | 当前中央自有汇总状态，尚未按投影器重建 |
| 中央库 | `video_milestones` | 中央自有状态，暂不可重建 |
| 中央库 | `prediction_ensemble` | 中央自有状态，暂不可重建 |
| 中央库 | `algorithm_coherence` | 中央自有状态，暂不可重建 |

“中央投影”只描述已知明细副本的目标状态，不代表当前同步具备跨库原子性。`videos`、`video_milestones`、`prediction_ensemble` 与 `algorithm_coherence` 在证明可由权威明细完整重建前，均不得归类为可重建投影。

## B5-b 目标所有权矩阵

| 中央表 / stream | 目标权威来源 | 目标定位 |
|---|---|---|
| `videos` | 每视频库 `video_info` 与 BVID 分区名 | 可重建投影 |
| `monitor_records` | 每视频库 `monitor_records` | 可重建投影 |
| `predictions` | 每视频库 `predictions` | 可重建投影 |
| `weekly_scores`、`yearly_scores` | 每视频库同名表 | 可重建投影 |
| `video_milestones` | 新增每视频权威表（尚未实现） | 当前无权威来源，不可重建 |
| `prediction_ensemble` | 新增每视频权威表（尚未实现） | 当前无权威来源，不可重建 |
| `algorithm_coherence` | 新增每视频权威表（尚未实现） | 当前无权威来源，不可重建 |

在 B5-b 后续实现补足权威表之前，后三项中央独有数据必须保留为“不可重建”的显式风险，而不能被误标为投影。

## 当前双写与镜像路径清单

- `core/database/video_db.py:889-891`：预测批量写入活跃视频库后，经 `sync_predictions()` 向中央库兜底双写。
- `ui/monitor/_prediction.py:486`：预测输出保存后调用 `_sync_predictions_to_central()`；该函数在 `:79`、`:81` 写入中央集成预测与共识。
- `core/database/video_db.py:_exec_mirror()` 与 `_execute_on_all()`：主视频库与镜像库的逐条/通用镜像写路径；`video_db_scores.py` 也镜像分数写入。
- `ui/monitor/_service.py`：监控观测先写视频库，再同步中央库。
- `core/database/central_backup.py:sync_per_video_dbs_to_backup()`：通过 `shutil.copy2` 进行备份文件拷贝。
- `core/database/central_crud.py:upsert_milestone()` 由 `central_db.py:upsert_milestone()` 门面暴露，当前直接写中央 `video_milestones`。

这些路径是 B5-b 的治理输入；本包不删除、合并或改变任何写路由。
