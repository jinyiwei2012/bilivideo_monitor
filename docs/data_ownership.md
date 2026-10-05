# 数据角色与表级所有权

本文件冻结 B5-b（第四批 4.1–4.4-F）交付后的所有权契约。在线多路径双写已取消，中央由 projector 以 outbox 承接，备份走一致性快照。

## 路径角色（B5-b 交付后）

| 角色 | 当前路径 | 当前语义 |
|---|---|---|
| `active_root` | `core/data` | 活跃存储根 |
| `backup_root` | `data`（`config.DATA_DIR`） | 备份/快照存储根 |
| `active_central` | `core/data/bilibili_monitor.db` | 活跃中央投影库 |
| `backup_central` | `data/bilibili_monitor.db` | 备份中央快照库；在线读路由切活跃库后，此路径由一致性快照维护 |
| `active_video` | `core/data/<BV>/<BV>.db` | 每视频权威明细库 |
| `snapshot_video` | `data/<BV>/<BV>.db` | 每视频一致性快照库（镜像已删，仅作离线快照留存） |
| `viewer_db` | `<root>/<BV>/viewercount.db` | 在线人数附属快照库 |

`ui/database_query.py`、`ui/monitor/_service.py` 的 watch-list 读取已路由至活跃中央库（4.4-D）。`data/<BV>` 仅作为离线快照保留，不再是写路径的镜像目标。

## 表级所有权矩阵：现状（B5-b 交付后）

| 位置 | 表 | 所有权 / 重建状态 |
|---|---|---|
| 视频库 | `video_info` | 权威视频元数据明细 |
| 视频库 | `monitor_records` | 权威观测明细 |
| 视频库 | `predictions` | 权威单视频预测明细 |
| 视频库 | `weekly_scores`、`yearly_scores` | 权威单视频分数明细 |
| 视频库 | `danmaku_records` | 权威弹幕明细 |
| 视频库 | `crossing_events` | 权威过线事件明细 |
| 视频库 | `video_milestones` | 权威里程碑明细（4.2 新增，`upsert_milestone`） |
| 视频库 | `prediction_ensemble` | 权威集成预测明细（4.2 新增） |
| 视频库 | `algorithm_coherence` | 权威相干性明细（4.2 新增） |
| 视频库 | `projection_outbox` | durable outbox（4.2 新增，七 stream 投递幂等） |
| 中央库 | `monitor_records`、`predictions`、`weekly_scores`、`yearly_scores` | 从视频库复制的中央投影（`CentralProjector.project_pending`） |
| 中央库 | `videos` | 中央投影（元数据经 `_sync_video_info` 例外同步） |
| 中央库 | `video_milestones` | 中央投影（权威 `video_milestones`） |
| 中央库 | `prediction_ensemble` | 中央投影（权威 `prediction_ensemble`） |
| 中央库 | `algorithm_coherence` | 中央投影（权威 `algorithm_coherence`） |

中央库全部七 stream 均为可重建投影——权威来源在每视频库，`apply_projection_batch` 以幂等 ON CONFLICT 承接。4.1 以 `xfail(strict=True)` 反证并闭合其可重建性。

## B5-b 目标所有权矩阵（已达成）

| 中央表 / stream | 目标权威来源 | 目标定位 |
|---|---|---|
| `videos` | 每视频库 `video_info` 与 BVID 分区名 | 可重建投影 ✅ |
| `monitor_records` | 每视频库 `monitor_records` | 可重建投影 ✅ |
| `predictions` | 每视频库 `predictions` | 可重建投影 ✅ |
| `weekly_scores`、`yearly_scores` | 每视频库同名表 | 可重建投影 ✅ |
| `video_milestones` | 每视频库权威表（已实现） | 可重建投影 ✅ |
| `prediction_ensemble` | 每视频库权威表（已实现） | 可重建投影 ✅ |
| `algorithm_coherence` | 每视频库权威表（已实现） | 可重建投影 ✅ |

## B5-b 交付后的数据流

- **写路径**：监控 / 预测等活动写入只做**一次本地事务**至每视频权威库；里程碑 / 集成预测 / 相干性同时写每视频权威表。在线镜像双写已删（4.4-D）。
- **投影**：`CentralProjector.project_pending` 从 `projection_outbox` 投递七 stream 到中央活跃库（幂等 ON CONFLICT），进程级冻结投影模式（`config/runtime_mode.py`；legacy 生产回退通道完整保留）。
- **快照**：`core/database/snapshot.py` —— `Connection.backup()` → 临时文件 → `PRAGMA quick_check` → `os.replace`；`central_backup.sync_per_video_dbs_to_backup` 委托 `snapshot_file`；`main_gui_tick` 周期快照 + `on_exit` 退出 finalizer。
- **读路由**：在线读取切活跃中央 / 活跃视频库（4.4-D）；`data/<BV>` 仅离线快照。

## B5-b 已删除的旧路径

- `core/database/video_db.py` / `video_db_scores.py` 的在线镜像类目与 `_exec_mirror` / `_execute_on_all` 镜像写（4.4-D 删）。
- `central_crud.sync_from_video_db` / `sync_all_video_dbs` 覆盖式旧同步（4.4-F 删，保守收口）。
- `ui/monitor/_prediction._sync_predictions_to_central` 遗留中央双写分支、`ui/monitor/_service._sync_monitor_record` 遗留双写分支（4.4-B 起以 legacy 守卫隔离）。
- `shutil.copy2` 手动备份拷贝（4.4-D 交由快照）。
