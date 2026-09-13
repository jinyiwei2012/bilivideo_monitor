# BiliVideo Monitor — 优化方案（Optimization Plan）

> 状态：**方案文档（未实施）**
> 生成方式：4 路只读并行审计（UI/性能、数据库、预测引擎、代码质量）+ 客观静态分析（flake8 / radon），全程未改动任何代码。
> 目标：在不改动整体架构、可逐项回滚的前提下，降低预测延迟、消除 UI 主线程卡顿、抑制数据库无限增长、恢复工程门禁。

---

## 0. 背景与审计口径

**代码规模**（静态统计）：

| 模块 | 文件数 | 行数 |
|---|---|---|
| algorithms | 170 | 35,130 |
| ui | 69 | 24,261 |
| core | 26 | 7,443 |
| utils | 20 | 3,239 |
| config | 1 | 166 |
| tests | 6 | 1,035 |

**客观静态分析**（`python -m flake8 . --count --statistics`，遵循仓库 `.flake8`）：

- 合计 **959** 项，主要构成：`F401` 未使用导入 **527**、`F841` 未使用变量 **84**、`C901` 复杂函数 **39**、`F821` 未定义名 **3**、`E402` 37、`F811` 重定义 13、`E121/E126/E127` 缩进类 108。
- `radon cc`：2991 个块，平均复杂度 A(4.54)；顶部热点 `registry._prepare_video_data` **CC52**、`try_torch_predict` **CC50**、`SnapshotBarChart.paintEvent` **CC40**、`PredictionAccuracyPanel._load_data` **CC38**。
- `radon mi`：可维护性最差 `algorithms/registry.py` **MI 0.00**、`ui/training_panel.py` **0.00**、`ui/danmaku_analysis.py` 2.92、`ui/snapshot_tab.py` 5.81。

**审计发现总量**：约 73 条（UI 20 / 数据库 18 / 预测引擎 20 / 代码质量 17），完整清单见 [附录 A](#附录-a完整发现清单)。

---

## 1. 执行原则与约束

1. **不改架构**：保留 120+ 算法自动注册、加权集成、A+B 双尺度训练目标、每视频 worker 线程、per-video SQLite + central 结构。
2. **可观测**：每项改动附带验证方法（计数/计时/单测/压测），完成后必须有证据。
3. **可回滚**：每项独立提交；涉及行为变化的提供配置开关。
4. **先安全网后优化**：先补最小回归测试与静态基线，再动热路径。
5. **风险偏好**：P0 只做"低风险高收益"；P1/P2 允许小步重构但必须带测试。
6. **不做的事**：不引入新框架、不替换 PyQt/SQLite、不在本次修复中顺带重构无关代码。
7. **原子化 commit（强制）**：每个改动单元 = 一个 commit，**只做一件事**。禁止把多个步骤、或"功能改动 + 格式化 / 清死代码 / 改 import"混在同一提交。提交信息统一 `refactor(<scope>): <what> (M#/S#)` 或 `fix(<scope>): <what> (M#)`。**回滚以单个 commit 为单位**；提交前先 `git status` + `git diff --staged` 确认只暂存了本单元的文件。
8. **运行环境固定（强制，唯一允许）**：所有命令（pytest / flake8 / radon / black / import 冒烟 / `python main.py`）**只能**在 conda 环境 **`bili`** 中执行——路径 `C:\ProgramData\anaconda3\envs\bili\python.exe`（Python 3.10.20 / Anaconda）。开工前必须激活并校验：
   ```powershell
   conda activate bili
   python -c "import sys; assert sys.prefix == r'C:\ProgramData\anaconda3\envs\bili', sys.prefix; print('env OK', sys.executable)"
   ```
   禁止使用 `base` 或其它环境（注：README 写的 `bilibili` 环境**不存在**，实际为 `bili`；也不要用 `agent` 等），禁止跨环境 pip 安装。原因：torch / NPU / ONNX 及其它依赖仅在该环境装好，换环境会得到错误的测试/运行结果。

---

## 2. 里程碑总览

| 里程碑 | 内容 | 预估 | 依赖 |
|---|---|---|---|
| **M0 安全网** | 静态检查基线 + 5 个最小回归测试 | 0.5–1 天 | — |
| **M1 P0** | 预测性能 4 项 + 锁/线程 2 项 + DB 快项 3 项 + 缺陷 2 项 | 6–8 天 | M0 |
| **M2 P1** | 主线程阻塞、图表、同步、模型缓存、数据保留、**分数中心窗口（M2.11，新增）** | 10–15 天 | M1 |
| **M3 P2** | 门禁、清理、拆模块、去重、主题/加密/类型/测试/卫生 | 10–15 天 | M2 |

依赖关系（关键）：

```
M0.2(测试) ──► M1.1/M1.2(模型缓存) ──► M2.6(模型按内容缓存)
M0.1(基线) ──► M3.1(门禁生效) ──► M3.2(清理)
M1.11(移除每抓取写分数) ──► M2.11(分数惰性物化 + 分数中心窗口)
M1.11(单事务) ──► M2.5(增量同步)
M1.12(统一连接) ──► M2.8(连接泄漏) / M2.9(保留与索引)
```

---

## 3. M0 — 安全网（先做）

### M0.1 锁定静态检查基线
- **位置**：`.flake8`、`.github/workflows/code-quality.yml`
- **做法**：
  1. 运行 `python -m flake8 . --statistics` 存档当前 959 项，按规则分类。
  2. 在 `.flake8` 中把 `F821,F811` 设为 **必须为零**（当前 3/13 条，单独先修）。
  3. 其余规则用 `--extend-ignore` 暂时冻结，并在 CI 中让 `flake8` **真实失败**（去掉复杂度检查里的 `exit 0` 与 mypy 的 `|| true` 只针对本步新增的规则）。
- **验证**：CI 在引入新 F821/F811 时变红。
- **风险**：低。**估时**：0.25 天。

### M0.2 补 5 个最小回归测试（后续改动的前置保护）
- **位置**：`tests/`
- **做法**：新增针对后续高风险改动的测试：
  1. `_torch_upgrade.try_torch_predict` 缓存命中时 **不调用** `load_best_checkpoint`（mock 计数）。
  2. `utils/crypto` 加密/解密 round-trip（含无 `cryptography` 时的 XOR 分支）。
  3. `AlgorithmRegistry` 载入后 **`algorithm_id` 唯一**（覆盖重复的 `bass_diffusion`）。
  4. `ui/settings_notification` 测试通知失败路径不抛异常（覆盖闭包 `e`）。
  5. `tbats_simple` 预测路径可返回结果（覆盖未定义 `forecast`）。
- **验证**：`pytest tests/` 全绿。
- **风险**：低。**估时**：0.5 天。

---

## 4. M1 — P0 低风险高收益

### M1.1 [预测#1] 缓存优先，避免每次预测重读 checkpoint
- **位置**：`algorithms/models/deep_learning/_torch_upgrade.py:1986`（`try_torch_predict` 入口无条件 `load_best_checkpoint`）、`algorithms/training/checkpoint_manager.py:430-448`（`_try_load_checkpoint`）、`:253`（`torch.load`）。
- **根因**：模型缓存 `_cached_torch_model` 的命中判断在 `:2048` 之后，位于磁盘加载之后；缓存只省了"建模"，没省"反序列化"。
- **改动**：
  1. 在入口先判 `algo._cached_torch_model is not None and getattr(algo, "_cached_bvid", None) == bvid`：命中则直接进入推理分支，**不调用** `load_best_checkpoint`。
  2. 为缓存增加 checkpoint 签名 `(active.json mtime, *.pt mtime/size)`；仅签名变化时重新读取并重建。
  3. 抽出 `_get_or_load_model(algo, algo_id, bvid, build_fn)` 统一缓存读写，消除多处重复判断。
- **验证**：单测断言第二次调用 0 次磁盘读取；实测同一视频连续 3 轮预测 `torch.load` 次数为 0（首轮/重训后除外）。
- **风险**：中/低（重训后未失效会用到旧权重 → 用 mtime 签名覆盖，并在保存 checkpoint 后主动失效）。
- **估时**：0.5–1 天。

### M1.2 [预测#2] `release_cached_models()` 不再每 3 轮清空
- **位置**：`ui/monitor/_prediction.py:440-455`（`_maybe_release_memory`）、`_torch_upgrade.py:1890-1920`（`release_cached_models`）。
- **根因**：固定计数器触发全量清缓存，放大 M1.1。
- **改动**：改用真实内存压力判定（复用 `utils/memory_guard`）；仅在 RSS 超阈值或 CUDA OOM 时释放；释放策略改 LRU，保留当前活跃 bvid 的模型；记录释放事件与原因。
- **验证**：多视频长跑观察 RSS 峰值与模型重载次数；释放日志可解释。
- **风险**：中（内存可能上升 → 阈值可配置，默认保守）。**估时**：0.5 天。

### M1.3 [预测#4] 权重反馈批量化
- **位置**：`algorithms/weight_manager.py:173-193`（`update_accuracy`）、`:195-237`（`_recalculate_ml_weights`）、`ui/monitor/_prediction.py:481-492`（每算法调用一次）。
- **根因**：每个算法每周期触发一次全量重算 + 全量 JSON 落盘（≈120 次/视频/周期）。
- **改动**：
  1. 新增 `update_accuracy_batch(records: list[tuple[name, acc]])`：一次加锁写入全部 → `_recalculate_ml_weights()` 一次 → 标 dirty。
  2. `_save_weights_sync` 改为 flush 时落盘（5–10s 去抖 / 每周期结束一次）。
- **验证**：单测统计重算与落盘次数由 ~120 降为 1；权重数值与旧实现逐位一致。
- **风险**：低（数值等价；崩溃丢最近几秒，可接受）。**估时**：1 天。

### M1.4 [预测#5] `get_algorithm_stats` 从 O(T²) 降到 O(T)
- **位置**：`algorithms/online_learner.py:266-283`、`:502-512`（`_quick_weight`）、`:302-329`（`get_weights`）。
- **改动**：`get_algorithm_stats` 先 `weights = self.get_weights()` 一次，循环内用 `weights.get(name)`；或让 `_quick_weight(name, weights=None)` 接受预计算快照。
- **验证**：T=2000 时计时线性；结果与旧实现一致。
- **风险**：低。**估时**：0.25 天。

### M1.5 [预测#6] `_adjust_eta` 增量化 + 节流
- **位置**：`algorithms/online_learner.py:217-218,399-423`。
- **改动**：每个 tracker 维护 `recent_errors` 的增量 `sum/sumsq`（deque 追加/弹出时更新）；`_adjust_eta` 用聚合值或 numpy 一次展开；触发从"每 5 次全局 update"改为"每预测周期一次"。
- **验证**：计时；eta 调整结果与旧实现数值一致（容差内）。
- **风险**：低–中。**估时**：0.5 天。

### M1.6 [UI#1/#2] 网络 I/O 移出全局锁
- **位置**：`ui/monitor/_service.py:206-215`（`_save_up_data(owner_id)` 在 `with gui._data_lock:` 内，含 1–2 次 HTTP）、`:225-229`（`get_video_viewers` 在 `with gui._viewers_lock:` 内，把所有抓取串行化）。
- **改动**：
  1. `_save_up_data`：锁内只取 `owner_id`/必要数据，**出锁后**再发请求；需要写回时出锁后再取锁写。
  2. viewers：出锁调用 `get_video_viewers` 得结果，再取 `_viewers_lock` 只写 `video["viewers_*"]`；或按 bvid 分锁。
- **验证**：批次总时长计时下降；多视频并发抓取压力测试无数据竞争/丢失写回。
- **风险**：中（写回时序 → 小步改 + 压测）。**估时**：0.5–1 天。

### M1.7 [UI#6] 修复状态栏去抖
- **位置**：`ui/monitor/_service.py:360-366`。
- **改动**：把 `invoke(...)`（更新 `last_ref`）移入 `if now - last_sb > 0.2:` 分支内并更新时间戳。
- **验证**：抓取 N 个视频时状态栏 invoke 次数由 N 降到 ≤5/s。
- **风险**：低。**估时**：0.1 天。

### M1.8 [质量#2] 修复 3 处真实 NameError（F821）
- **位置/改法**：
  - `algorithms/models/ensemble/bagging_simple.py:107`：`Optional` 未导入 → 补 `from typing import Optional`（或移除注解）。
  - `algorithms/models/time_series/tbats_simple.py:143`：`forecast` 未定义、被 `:156` 的 except 静默吞掉 → 确认是否漏写 `model.forecast(...)`，补全或移除该死分支。
  - `ui/settings_notification.py:189`：lambda 引用的 `e` 在 `except ... as e` 结束后已被删除 → 改为先 `err = str(e)` 再在闭包用 `err`。
- **验证**：`flake8 --select F821` 归零；M0.2 中相关测试通过。
- **风险**：低。**估时**：0.5 天。

### M1.9 [质量#3] 收敛静默异常（关键路径优先）
- **位置（清单）**：`core/database/central_backup.py:67`、`core/threshold_escalation.py:107`、`core/bilibili_auth.py:430`、`core/database/video_db_danmaku.py:129`、`ui/monitor/_prediction.py:343,453,491`、`ui/settings_window.py:329,334`、`ui/main_gui.py:198,233,253`、`ui/training_panel.py`(5 处)、`utils/memory_guard.py:67,77`、`core/database/central_query.py:19-28`。
- **改动规则**：
  - 可选依赖的 `ImportError` 保持静默；
  - 其余 `except Exception: pass/continue` → `logger.warning("...: %s", e)` 并收窄异常类型；
  - `_run_query` 不再吞成 `[]`，改为抛出或返回带 `error` 字段的结果，调用方区分"空结果 vs 失败"。
- **验证**：注入失败（只读 DB、无效 SQL）后日志出现；不产生重复告警风暴。
- **风险**：低–中（可能暴露既有隐藏错误，需逐个评估）。**估时**：1 天。

### M1.10 [DB#1] 消除镜像双写
- **位置**：`core/database/video_db.py:50-57`（`mirror_base` 选择）、`:77-89`、`:91-106`、`:421-433`、`:508-512`；`core/database/central_db.py:339`。
- **根因**：`mirror_base`(`data/`) != `base_dir`(`core/data`)，故每次写入落两份（各带提交与 WAL）。
- **改动**：新增配置 `db.mirror_enabled`（默认 false）；仅在启用且 `mirror_base != base_dir` 时设置 `_mirror_path`；备份改由 `sync_per_video_dbs_to_backup()` 在退出/定时执行。
- **验证**：单次抓取的写文件/提交次数减半；定时同步后备份仍生成。
- **风险**：中（备份时效下降 → 开关可回退）。**估时**：0.5–1 天。

### M1.11 [DB#2/#3] 单事务快照 + 停止每抓取写分数
- **位置**：`ui/monitor/_service.py:280-309`（6 次独立提交）、`core/database/video_db.py:509-511`、`core/database/central_crud.py:201,240`、`ui/main_gui_data.py:71-100`（weekly/yearly 每抓取写）。
- **改动**：
  1. 新增 `VideoDatabase.write_snapshot(record)`：**一次事务**写 monitor 记录；移除 `_ConnectionCtx` 内与显式 `conn.commit()` 的重复提交。
  2. 新增 `CentralCRUD.sync_snapshot(...)` 批量写 monitor+video_info。
  3. **移除**每次抓取时对 `_save_weekly_score/_save_yearly_score` 的调用（`ui/monitor/_service.py:281-282`）；分数改由 **M2.11 的惰性物化**按需补齐（注：该分数是当前计数器的纯函数、并非"周键/年键"时间窗聚合，详见 M2.11）。
- **验证**：单次抓取提交次数 6→1；单次抓取不再触及 `weekly_scores/yearly_scores`。
- **风险**：中（事务原子性与 UI 读数一致性）。**估时**：1 天。

### M1.12 [DB#5] 统一连接：WAL + busy_timeout
- **位置**：`core/database/connection.py:33-64`、`video_db.py:44-48`、`central_db.py:115-119`、`central_backup.py:41,92,129`、`central_crud.py:28`、`core/up_database.py:30`、`algorithms/training/dataset.py:190,571`。
- **改动**：提供 `core/database/connection.py::open_conn(path, ro=False)` 统一设置 `journal_mode=WAL, synchronous=NORMAL, busy_timeout=5000, foreign_keys=ON`，替换所有裸 `sqlite3.connect`。
- **验证**：并发读写压测无 `SQLITE_BUSY`；断言 `PRAGMA busy_timeout`。
- **风险**：低–中。**估时**：1 天。

**M1 验收**：单视频单轮预测的磁盘 `torch.load` 次数 = 0（缓存命中）；权重反馈重算/落盘次数 ≤1/周期；抓取批次总时长显著下降且无竞争；单抓取提交次数 = 1；`F821=0`；关键路径失败可见。

---

## 5. M2 — P1 高收益（需小步重构）

### M2.1 [UI#4] 图表重绘缓存
- **位置**：`ui/chart.py:76`（`scene.clear()`）、`:225-234`（逐段 line/oval）、`:113-129`（`QGraphicsTextItem`）、`:49-50`（全局抗锯齿）。
- **改动**：改用单个自定义 `QGraphicsItem` 以一次 `QPainter` 绘制全部折线/点；静态网格/坐标轴缓存为独立图层；文字改用 `QGraphicsSimpleTextItem` 或 `painter.drawText`；默认 step 模式限制点数。
- **验证**：同一数据重绘的 item 数量与帧耗时显著下降（基准截图+计时）。
- **风险**：中（视觉一致性 → 截图对比）。**估时**：2 天。

### M2.2 [UI#3/#8/#9] 主线程同步查库全部后台化
- **位置**：`ui/dashboard_mode.py:508-513`（健康页每 15s 对全部视频查库+异常检测）、`ui/detail_panel.py:928,935`（主线程查 weekly/yearly）、`ui/detail_tabs.py:104-127`（主线程查弹幕+`setHtml`）、`ui/online_viewers_panel.py:340,276`（主线程逐视频查询）。
- **改动**：在后台线程计算，经 `ui/invoker.py` 回主线程仅做展示；健康页数据缓存，轮转时复用；弹幕仅在计数变化时重渲染。
- **验证**：主线程单帧无 DB/磁盘调用（用计时或 Qt 事件耗时日志）；页面切换不卡顿。
- **风险**：中。**估时**：2–3 天。

### M2.3 [UI#5] `update_card` 索引化 + 封面缓存
- **位置**：`ui/video_list_panel.py:352-379`（O(N²) 扫描 + `:370` 主线程 `get_valid_cover`）、`utils/cover_manager.py:111-118`（整文件读取+MD5）。
- **改动**：维护 `bvid → QListWidgetItem` 映射，避免每次线性查找；封面有效性缓存（按路径+mtime），MD5 计算移入加载线程；`rebuild_list` 同理。
- **验证**：N 增加时刷新耗时近似线性；主线程不再读封面文件。
- **风险**：低–中。**估时**：1–1.5 天。

### M2.4 [UI#7] 集中抓取改有界线程池
- **位置**：`ui/monitor/_service.py:389-409`（每视频一个线程 + `:406` `time.sleep(0.2)` + 顺序 `join(60)`）、`:431-435`。
- **改动**：改用有界 `ThreadPoolExecutor` + `as_completed`；用 `Event.wait` 代替 sleep 节流；限制并发数。
- **验证**：N=100 视频时线程数受限、批次时长不再随 N 线性爆炸。
- **风险**：中。**估时**：1 天。

### M2.5 [DB#7/#8] 增量同步 central
- **位置**：`ui/main_gui_tick.py:119-152`（每小时触发）、`core/database/central_backup.py:18-69,142-189,191-232`（全表 O(N) + 持锁 + N+1）、`core/database/central_crud.py:118-127,246-256`（每视频重建整个 `VideoDatabase` 含建表/迁移）。
- **改动**：用高水位标记（`MAX(ts)`）做集合化 `INSERT..SELECT` 增量同步，锁外执行；`sync_from_video_db` 改用轻量只读读取器，缓存实例。
- **验证**：同步耗时从 O(全表) 降到 O(增量)；同步期间抓取写入不被阻塞。
- **风险**：中。**估时**：2 天。

### M2.6 [预测#10/#11] 模型按内容缓存 / 参数缓存
- **位置**：约 15 个重型拟合器（`random_forest_simple.py:147`、`xgboost_simple.py:170`、`gradient_boost_simple.py:141`、`extra_trees_simple.py:329`、`bagging_simple.py:297,396`、`gaussian_process.py:123`、`tabnet_simple.py:158`、`stacking_ensemble.py:170`、`blending_ensemble.py:169`、`residual_correction.py:167`、`quantile_ensemble.py:178`、`ngboost_simple.py:126`、`tsfc_classification.py:199`、`narx_simple.py:166`）与 4 个 `curve_fit(maxfev=5000)`（`logistic_growth.py:209`、`gompertz_growth.py:213`、`richards_curve.py:218`、`weibull_growth.py:216`、`base.py:303-316`）。
- **改动**：以 `(algo_id, content_digest, n)` 为键缓存已拟合模型/拟合参数；按"N 个新点或 TTL"失效；支持 `warm_start`；重训可异步化。
- **验证**：历史未变时同一算法不重复拟合；预测结果与旧实现一致（容差）。
- **风险**：中（陈旧性 → 明确的失效策略）。**估时**：3 天。

### M2.7 [预测#7/#8/#9/#16] 共享输入预计算
- **位置**：`_torch_upgrade.py:2000,2350-2390`（40 个 DL 算法各自构建 z-score/velocity/derived）、`algorithms/base.py:436-448`（`get_video_age_hours` 每次排序）、`:209-227`（`_normalize_history` 每算法深拷贝）、`short_term_hotness.py:70` / `change_point_detection.py:341,345`（未缓存的 surge 计算）。
- **改动**：在 `AlgorithmRegistry._prepare_video_data` 一次性计算并存入 `video_data`（`_torch_input`、`history_age_hours`、`_normalized_history`、每视频 surge），算法改为消费；`roll_std` 用 numpy 向量化。
- **验证**：单轮预测中历史遍历次数从 40× 降到 1×；结果一致。
- **风险**：中（耦合 → 保留覆盖入口）。**估时**：2–3 天。

### M2.8 [DB#10/#11] 连接泄漏修复
- **位置**：`core/database/central_backup.py:92-95,129-132`（`with sqlite3.connect(...)` 不会 close）、`core/database/central_db.py:64-65`、`central_crud.py:22-37,291-325,313`（`_query_backup` 异常时泄漏）。
- **改动**：统一用 `contextlib.closing` / `try/finally`；`_query_backup` 仅在需要时命中备份并对 LIMIT 下推；缓存只读连接。
- **验证**：长跑后句柄数稳定；同步后备份文件不残留旧版本。
- **风险**：低。**估时**：0.5–1 天。

### M2.9 [DB#4/#14/#15] 数据保留 + 索引 + 时间戳统一
- **位置**：`config/__init__.py:44-46`（`history_days`/`save_history` 从未被读取）、索引缺口（`video_db.py:156-173,227-254,628-630`、`central_db.py:142-165,207-215,236-262`、`up_database.py:64-67,169-187`）、时间戳格式混用（`ui/monitor/_service.py:268,291` 用空格分隔 vs `ui/main_gui_data.py:133,143` 用 `T`-ISO）。
- **改动**：
  1. 在 `do_periodic_sync` 中按 `history_days` 执行 `DELETE FROM monitor_records WHERE timestamp < :cutoff`（含 central），可选聚合为小时级。
  2. 补 `created_at`/`video_ts`/`(uid,timestamp)`/`owner_id` 等索引。
  3. 统一写入 UTC ISO（或 epoch INTEGER），提供一次性迁移与校验。
- **验证**：库大小进入稳态；范围查询命中索引；跨格式比较测试通过。
- **风险**：中–高（数据删除/格式迁移 → 先备份 + 干跑 + 开关）。**估时**：2–3 天。

### M2.10 [UI#11/#12/#14/#16、预测#12/#18] 其余主线程/CPU 热点
- `ui/main_gui_tick.py:48,113-114`：`tracemalloc.take_snapshot()` 移出主线程。
- `ui/invoker.py:28-31`：增加按 key 合并与背压；异常走 logger。
- `ui/log_panel.py:248,157,173-174`：用计数替代全量 `toPlainText()`；`_pending_logs` 加锁。
- `ui/video_list_panel.py:60-68`：worker 内用 `QImage`，主线程转 `QPixmap`；封面线程池有界。
- `ui/video_list_panel.py:286-296`：搜索去抖或 `QSortFilterProxyModel`。
- 预测侧：`np.random.seed(42)` 改为局部 `default_rng`（`tabnet_simple.py:240`、`time_moe_simple.py:121`、`timesfm_simple.py:123`、`deepar_simple.py:111`、`diffusion_ts.py:342`）；`diffusion_ts.py:191-207` 改用少步采样。

### M2.11 [DB#3] 分数存储重构（惰性物化 + 每小时桶）+ 新增「周/年分数中心」窗口 ★
- **事实前提**：`weekly_scores/yearly_scores` 存的是**当前计数器的排行榜分数**，不是周/年时间窗聚合 —— `utils/yearly_score.py:37`(`calculate_yearly_score`) 与 `utils/weekly_score.py`(`calculate_weekly_score`) 的输入仅为 `view/like/coin/favorite/danmaku/reply` 六个快照字段；这 6 项全部保留在 `monitor_records`（视频库与中央库，见 `central_crud.py:218-239`），因此任意时点分数都可重算。
- **消费方**：仅 `ui/detail_panel.py:928,935`（取最近 5 点画趋势）与 `ui/database_query.py:387,400`（原始 SQL 按 `timestamp <= ?` 查"当时分数"）。`ui/ranking_panel.py` 用实时内存数据、**不读**分数表；中央 `weekly_scores/yearly_scores` 暂未发现读取方（仅 `central_crud.sync_weekly_score/sync_yearly_score` 在写）。
- **存储策略**：**惰性物化 + 每小时桶 + 当前值实时算 + 水位线增量**。
  - `utils/score_materializer.py::ensure_scores(bvid, granularity="hour", until=None) -> {"computed": int, "written": int}`：
    1. watermark = 视频库 `SELECT MAX(timestamp) FROM weekly_scores`（视频库表无 `bvid` 列）；
    2. 取 `monitor_records` 中 `timestamp > watermark` 的记录；
    3. 按整点桶 `strftime('%Y-%m-%d %H:00:00')` 分组，每组取最后一条；
    4. 用公式算分，`INSERT OR REPLACE` upsert 到视频库 + 中央；**幂等**。
  - `current_scores(bvid)`：从最新 `monitor_record` 现算当前分，**不落库**（保证显示最新）。
  - `ui/monitor/_service.py:281-282` 的每抓取写入**移除**（见 M1.11）；详情面板读路径改为"先 `ensure_scores(bvid)`，再 `get_weekly_scores(limit=5)`"（后台线程，见 M2.2）。
  - **schema 迁移**：视频库 `weekly_scores/yearly_scores` 现仅普通索引 `idx_weekly_timestamp/idx_yearly_timestamp`（`video_db.py:210,226`）；`INSERT OR REPLACE` 需 `UNIQUE(timestamp)` 才幂等 → 增加唯一索引/约束（迁移前备份 + dry-run）。
  - 可选：停止 `sync_weekly_score/sync_yearly_score` 到中央以省写入（需先确认报表/导出无消费）。
- **新增窗口「周/年分数中心」**（建议 `ui/score_center.py`，入口挂主菜单/工具栏）：
  - **定位**：专注三件事 —— **计算**、**查询**、**把"之前未写入但刚算出的数据"补齐写库**。
  - 顶部：视频选择（单个 / 全部）+「计算并补齐」按钮 + 状态（最近归档时间；当前值标注"实时计算"）。
  - 中部：Tab（周刊分数 / 年刊分数）；表格列 = 时间戳 / 总分 / view·interaction·favorite·coin·like / corrections；下方迷你趋势（复用 `ui/chart.py` 或轻量 sparkline）。
  - 查询：按视频 + 时间范围过滤；"按时间点查当时分数"（对齐 `database_query` 语义）。
  - 进度/日志：复用 `ui/async_queue_runner.py` + `ui/invoker.py`，显示"待补齐 N / 已写入 M"，支持取消。
  - UI 标注：`分数按需计算 · 趋势按小时归档`；代码注释说明"非每帧写入"。
- **验证**：重复点击「计算并补齐」不产生重复行（幂等）；未打开窗口/未请求的视频零写入；详情趋势始终含最新点；`database_query` 按时间点查询仍命中；主线程无计算。
- **风险**：中（唯一约束迁移；首次全量回填耗时 → 分批/可取消；中央同步位点一致性）。
- **估时**：后端 1–1.5 天 + 窗口 2–3 天。

**M2 验收**：主线程无可达的 DB/磁盘/网络调用；图表重绘 item 数大幅下降；历史未变不重复拟合；库大小有上限；分数按小时桶归档且补齐幂等、未查看视频零写入。

---

## 6. M3 — P2 架构 / 质量 / 仓库卫生

### M3.1 [质量#1] 恢复真实 CI 门禁
- `.github/workflows/code-quality.yml`：`flake8 .` 现状 959 项必失败 → 先用 `--extend-ignore` 冻结历史项、逐步清零；删除复杂度检查的 `exit 0`；mypy 去掉 `|| true`。**估时**：1 天。

### M3.2 [质量#4/#8/#14] 清理死代码
- `autoflake`/`ruff --select F401,F841 --fix` 清理 527 未用导入 + 84 未用变量（重点 `ui/` 331、`deep_learning/` 77、`settings_*.py`）；`ui/monitor/_prediction.py` 函数内重复 import 提到模块级。**估时**：1 天。

### M3.3 [质量#5] 拆分巨型模块
- `_torch_upgrade.py`(2577)、`training_panel.py`(1518)、`registry.py`(1218)、`main_gui_events.py`(1183)、`finetune_panel.py`(1070) 按职责拆分，置于测试之后。**估时**：3–5 天。

### M3.4 [质量#6] 降复杂度
- `registry._prepare_video_data` CC52、`try_torch_predict` CC50、`SnapshotBarChart.paintEvent` CC40、`PredictionAccuracyPanel._load_data` CC38 等 40 个超标函数：提取辅助函数/分派表 + 单测。**估时**：3–5 天。

### M3.5 [质量#7] 去重算法 + 唯一性断言
- `advanced/bass_diffusion.py` 与 `growth/bass_diffusion.py` 同 `algorithm_id="bass_diffusion"` → 合并或改唯一 id；`gompertz` vs `gompertz_growth`、`theta_forecast` vs `theta_method` 同理；在注册时断言 `algorithm_id` 唯一（M0.2 测试）。**估时**：1 天。

### M3.6 [质量#9] 主题色回归 `ui/theme.py`
- `dashboard_mode.py:21-29,302`、`chart.py:22-24,252,268,416,425`、`health_probe.py:103,109,198`、`data_comparison.py:22-44`、`crossover_analysis.py:29-33,332`、`bottom_bar.py:51`、`entry_tab.py:277,523,590` 改为引用 `C` 字典。**估时**：1 天。

### M3.7 [质量#11] 加密加固
- `utils/crypto.py:105-139`（XOR 回退）改为失败关闭或显式标记明文；`:36-86,65` 的导入时 PowerShell 改惰性/可缓存；`:86` 硬编码 salt 移入配置/每装机密钥；`:171-176` 的 `is_encrypted` 启发式加显式版本头。**估时**：1–2 天。

### M3.8 [质量#16] 类型门禁
- 去掉 mypy 的 `|| true`，先修/挂起现有错误，再按包逐步收紧（`algorithms.training`、`utils`）。**估时**：2–3 天。

### M3.9 [质量#17] 测试覆盖
- 为高风险逻辑补测试：集成权重、训练目标构建、异常检测器、crypto round-trip、注册表唯一性、`_prepare_video_data`。**估时**：3–5 天。

### M3.10 [质量#15、DB#13/#16] 仓库与 DB 访问卫生
- `git rm --cached` 移除 `.omo/`(19 文件) 与 `data/*.json` 运行产物，完善 `.gitignore`；统一 DB 访问走 `open_conn`；`search_videos` 的 `%kw%` 考虑 FTS5；`dataset.py:196,200,203` 的列名加白名单校验；`central_query.py:77-84` 合并三次 COUNT。**估时**：1–2 天。

---

## 7. 验收标准（Definition of Done）
- [x] `F821 = 0`、`F811 = 0`；`flake8` 总项数在 CI 中单调下降（有 ratchet）。
- [x] 缓存命中场景下，单轮预测 `torch.load` 次数为 0；权重反馈重算/落盘 ≤1/周期。
- [x] 抓取批次的锁外网络调用比例 100%；`_data_lock`/`_viewers_lock` 不在网络 I/O 期间持有。
- [x] 单次抓取的 DB 提交次数 = 1；每次抓取不再写分数表；分数按小时桶归档且补齐幂等（重复计算不产生重复行）。
- [x] 主线程无可达的 SQLite/磁盘/网络调用（仪表盘、详情、弹幕、封面）。
- [x] 库大小进入稳态（`history_days` 生效）；常见查询命中索引。
- [x] `pytest tests/` 全绿；新增 5 个回归测试持续通过。


> **完成状态（分支 `refactor/optimization`，领先 main 76 个提交）**
>
> - **门禁**：`flake8 .` = **0 项**（棘轮 `scripts/lint_gate.py`，复杂度基线 **0**）；`mypy` 棘轮 `scripts/type_gate.py`（历史 738 条唯一键已挂起在 `.mypy-baseline.json`，CI 无 `|| true`）；`black --check` 全仓通过；`bandit -ll` Medium/High = 0。
> - **测试**：`pytest tests/` = **258 passed**（重构前基线 115）；新增回归测试覆盖加密、主题令牌、A+B 训练目标、告警检测器、Hedge 在线学习、锁作用域、注册表唯一性等。
> - **结构**：`registry.py` 1333→126、`_torch_upgrade.py` 3051→126、`main_gui_events.py` 1262→96、`training_panel.py` 1375→43、`finetune_panel.py` 953→472 行，**对外导入面零变**（`_torch_upgrade` 41 个名字、`main_gui_events` 41 个名字、注册表算法数仍为 137）。
> - **主题**：`ui/theme.py` 集中 78 个令牌（series/dash/pred/sentiment/heatmap/warn 等），`ui/` 内硬编码色值仅剩 2 处文档描述性提及。
> - **已知观察（未改行为，已用测试锁定）**：`algorithms/training/dataset.py` 的长期目标 `long_rate[N-1]` 补 0 会被末端样本的均值纳入，轻微稀释靠近序列尾部的长期监督（`test_tail_zero_pad_dilutes_long_target`）。
>
> 修正：M3.7 = 加密加固（原计划编号），M3.8 = 类型门禁；此前若干提交信息中的 “M3.8” 实际指 M3.7。
---

## 8. 风险登记（Top）

| 风险 | 关联项 | 缓解 |
|---|---|---|
| 缓存失效不当 → 用旧权重预测 | M1.1 | mtime 签名 + 保存后主动失效 + 测试 |
| 数据删除/时间戳迁移造成数据丢失 | M2.9 | 先备份、干跑、可配置开关、分批 |
| 内存上升（不再频繁释放） | M1.2 | 阈值可配、LRU、监控 RSS |
| 主线程后台化引入竞态 | M2.2 | 统一经 `invoker` 回主线程、压力测试 |
| 拆分巨型模块引入行为漂移 | M3.3/M3.4 | 先补测试再拆，逐文件小步提交 |
| 释放镜像后备份不新鲜 | M1.10 | 保留定时/退出备份 + 开关 |
| 分数表唯一约束迁移失败 → 回填重复行 | M2.11 | 迁移前备份 + dry-run + 幂等校验 |

---

## 附录 A：完整发现清单

> 格式：`[区域] #序号 标题 — 位置`。详细描述见本方案正文对应项；标记 ★ 的建议优先。

### A.1 UI / 性能（20）
1. ★ 网络 I/O 持 `_data_lock` — `ui/monitor/_service.py:206,214-215`
2. ★ `_viewers_lock` 跨网络调用 — `ui/monitor/_service.py:225-229`
3. ★ 仪表盘健康页主线程查库 — `ui/dashboard_mode.py:508-513`
4. ★ 图表整场景重建 — `ui/chart.py:76,225-228,232-234,113-129,49-50`
5. ★ `update_card` O(N²)+主线程封面 MD5 — `ui/video_list_panel.py:352-379`; `utils/cover_manager.py:111-118`
6. ★ 状态栏去抖失效 — `ui/monitor/_service.py:360-366`
7. ★ 集中抓取无限线程 — `ui/monitor/_service.py:389-409`
8. 详情页主线程 SQLite+重复算分 — `ui/detail_panel.py:928,935,681,683`
9. 弹幕页主线程 DB+setHtml — `ui/detail_tabs.py:104-127`
10. `_merge_history` 每次重排/解析 — `ui/monitor/_prediction.py:135,143-144`
11. 主线程 `tracemalloc` — `ui/main_gui_tick.py:48,113-114`
12. 每预测起线程+每 3 次 GC — `ui/monitor/_prediction.py:431,444-455`
13. 在线观看面板主线程逐视频查库 — `ui/online_viewers_panel.py:340,276`
14. invoker 无合并/无背压 — `ui/invoker.py:28-31`
15. worker 内建 QPixmap + 无界线程 — `ui/video_list_panel.py:60-68`
16. 日志面板全量 `toPlainText` + 竞态 — `ui/log_panel.py:248,157,173-174`
17. 搜索每次按键 O(N) — `ui/video_list_panel.py:286-296`
18. delegate paint 反复分配 — `ui/video_list_panel.py:117,140,155`
19. 仪表盘预测页整页重建 — `ui/dashboard_mode.py:682-683,691,54-56`
20. per-video 间隔仅装饰；历史切片每抓取拷贝 — `ui/main_gui_tick.py:78-83`; `ui/monitor/_service.py:23,431,260-261`

### A.2 数据库（18）
1. ★ 镜像双写 — `core/database/video_db.py:50-57,77-89,91-106,421-433,508-512`; `central_db.py:339`
2. ★ 每抓取 5–6 次提交 — `ui/monitor/_service.py:280,281-282,288,309`; `video_db.py:509-511`; `central_crud.py:201,240`
3. ★ weekly/yearly 每抓取写（→ 改为惰性物化，见 M2.11） — `ui/monitor/_service.py:281-282`; `ui/main_gui_data.py:71-100`; 消费方 `ui/detail_panel.py:928,935` / `ui/database_query.py:387,400`
4. ★ 无保留（`history_days` 未用） — `config/__init__.py:44-46`
5. ★ 单连接+全局锁、无 busy_timeout — `core/database/connection.py:33-64`; `video_db.py:44-48`; `central_db.py:115-119`
6. 无界 `SELECT *` — `video_db.py:559-561,629-630`; `video_db_danmaku.py:147-150`
7. 每小时全表 `sync_to_central` 持锁 — `ui/main_gui_tick.py:119-152`; `central_backup.py:18-69,142-232`
8. 每视频重建整个 `VideoDatabase` — `central_crud.py:118-127,246-256`
9. 逐行 INSERT + 每次 DDL — `central_crud.py:471-474,475-490,529-533`
10. `with sqlite3.connect` 不关闭（泄漏） — `central_backup.py:92-95,129-132`; `central_db.py:64-65`
11. `_query_backup` 每次新连接 — `central_crud.py:22-37,291-325`
12. 每 5 分钟 TRUNCATE 全库；central 未加锁 — `ui/main_gui_tick.py:109-110,306-319`; `central_db.py:360-365`
13. ensemble/coherence 同步路径死代码 — `ui/monitor/_prediction.py:60,61,99,31-41,384-405`
14. 索引缺口 — `video_db.py:156-173,227-254,628-630`; `central_db.py:142-165,207-215,236-262`; `up_database.py:64-67,169-187`
15. 时间戳 TEXT 格式混用 — `ui/monitor/_service.py:268,291`; `ui/main_gui_data.py:133,143`
16. 三次 COUNT + `%LIKE%` 全扫 — `core/database/central_query.py:77-84,57-60`
17. `UpDatabase` 每次新连接 — `core/up_database.py:28-30,79,122,142`
18. `dataset.py` 异常泄漏连接 — `algorithms/training/dataset.py:571-578,190-205`

### A.3 预测引擎（20）
1. ★ 每次预测重读 checkpoint — `_torch_upgrade.py:1986`; `checkpoint_manager.py:430-448,253`
2. ★ 每 3 轮清空模型缓存 — `ui/monitor/_prediction.py:440-455`; `_torch_upgrade.py:1890-1920`
3. ★ `load_best_checkpoint` O(N) 扫描 — `checkpoint_manager.py:474-481`; `registry.py:197-209`
4. ★ `update_accuracy` 每算法全量重算+落盘 — `weight_manager.py:173-193,195-237`; `_prediction.py:481-492`
5. ★ `get_algorithm_stats` O(T²) — `online_learner.py:266-283,502-512`
6. ★ `_adjust_eta` 每 5 次全扫 — `online_learner.py:217-218,399-423`
7. ★ 40 个 DL 算法重复构建输入 — `_torch_upgrade.py:2000,2350-2390,2307-2347`
8. `get_video_age_hours` 每次排序 — `algorithms/base.py:436-448`
9. `_normalize_history` 深拷贝 — `algorithms/base.py:209-227`
10. ~15 个模型每预测重训 — 见 M2.6 列表
11. 4 个增长模型每次 `curve_fit` — `logistic_growth.py:209`; `gompertz_growth.py:213`; `richards_curve.py:218`; `weibull_growth.py:216`
12. `np.random.seed` 污染全局 — `tabnet_simple.py:240` 等
13. 每周期约 120 次取权重加锁 — `registry.py:557`; `weight_manager.py:239-256,258-270`
14. `_content_digest` 每预测重建数组+MD5 — `registry.py:226-240,281`
15. `_prepare_video_data` 多次 O(n) 遍历 — `registry.py:250-275`
16. `detect_surge` 重复未缓存 — `short_term_hotness.py:70`; `change_point_detection.py:341,345`
17. `_rank_backends` 首轮基准 — `_torch_upgrade.py:2159-2249`; `device.py:443,456`
18. `diffusion_ts` 100 步反向扩散 — `diffusion_ts.py:191-207,301,313`
19. 137 个算法对象全部急切实例化 — `registry.py:158-182`
20. 杂项（每调用 import、三次重建列表） — `registry.py:580-581,892-914,644-657`; `base.py:249,287,289,362,309`

### A.4 代码质量（17）
1. ★ CI 门禁失效 — `.github/workflows/code-quality.yml`; `.flake8`; `mypy.ini`
2. ★ 3 处 NameError — `bagging_simple.py:107`; `tbats_simple.py:143,156`; `settings_notification.py:189`
3. ★ 静默吞异常 — 见 M1.9 清单
4. ★ 527 未用导入 / 84 未用变量 — `ui/`(331), `deep_learning/`(77), `settings_*.py`
5. ★ 巨型模块 — `_torch_upgrade.py` 2577 …
6. 40 个超复杂度函数 — `registry.py:243` CC52 等
7. 重复算法同 id — `advanced/bass_diffusion.py` vs `growth/bass_diffusion.py`
8. 异常/日志风格不一致 — `ui/dialogs.py` 等
9. 硬编码颜色 — `dashboard_mode.py:21-29` 等
10. f-string SQL 标识符 — `central_query.py:48,58,69,82`; `dataset.py:196,200,203`
11. crypto XOR 回退 + 导入时 PowerShell — `utils/crypto.py:105-139,65,86`
12. settings 面板重复样板 — `settings_common.py` 未被采用
13. DB 访问不一致 — `dataset.py:190`; `browser_cookies.py`; `scripts/*`
14. `_prediction.py` import 混乱 — `ui/monitor/_prediction.py:3,8,9,10,22,23` 等
15. 运行产物入库 — `.omo/`(19) ; `data/*.json`
16. 类型未强制 — `mypy.ini` + `|| true`；49 处 `# type: ignore`
17. 测试覆盖薄 — `tests/` 6 文件 vs 303 模块

---

## 9. 大型文件与高复杂度函数重构步骤（M3.3 / M3.4 详细化）

> 生成方式：5 份只读分析（algorithm 核心 / registry+base / torch 训练核心 / main GUI / 复杂面板 / 训练 UI），全部基于实读源码 + `radon cc` + AST 行号 + 调用方检索。**未改动任何文件**。所有行号对应当前磁盘版本。

### 9.0 通用约定与验证底座

- **测试先行**：每个文件先补特征化测试（characterization tests），锁定当前行为，再搬移。
- **行为零变**：不改函数签名、PyQt 信号/槽、线程模型、消息文案、`fire_and_forget(name=...)` 线程名、定时器间隔。
- **兼容门面**：被广泛 import 的模块（`_torch_upgrade.py`、`base.py`、`registry.py`）保留原路径并 **re-export** 全部对外符号；torch 不可用时的 `None` 占位行为必须保留。
- **原子化 commit（强制）**：每步一个 commit、只做一件事（见 §1.7）；回滚 = `git restore <file>`（或删新建文件）。
- **运行环境（强制）**：所有命令必须在 conda **`bili`** 中执行（见 §1.8）。
- **通用验证命令**（须先 `conda activate bili`）：
  ```bash
  python -m pytest tests/ -q
  python -m flake8 <file...>
  python -m radon cc -s <file...>
  python -c "import <module>"          # 导入冒烟
  ```
- **绘制类改动**（`paintEvent`）额外验证：`QT_QPA_PLATFORM=offscreen` + `widget.grab()` 出 PNG 前后对比（新增一次性脚本 `scripts/ui_paint_diff.py`）。
- **通用风险**：循环导入（沿用仓库"函数内惰性 import"惯例）、QObject 父子关系（`QTimer(gui)`/`QDialog(gui)` 不得把 parent 改为 `None`）、`ui/invoker.py` 跨线程回主线程的 `invoke`/`invoke_later` 不得改成同步调用。

---

### 9.1 `algorithms/registry.py` — 1218 LOC，MI 0.00（全仓最差）

**热点实测**：`_prepare_video_data` **CC52**（L243–449，207 行）·`predict_all` **CC37**（L835–998，164 行）·`_compute_log_eta` C19（L777–832）·`_load_model_algorithms` C16（L145–188）·`_run_parallel_predictions` CC12（L550–632）·`_apply_coherence_weights` CC11。

**拆分目标（保留 `AlgorithmRegistry` 于 `algorithms/registry.py`，改为 Mixin 组合；禁止创建 `algorithms/registry/` 包——与 `registry.py` 同名会导入歧义）**

| 新模块 | 移入符号 |
|---|---|
| `algorithms/registry_cache.py` | `_MAX_CACHE_SIZE`, `_LRUDict`（**必须 re-export**：`tests/test_defect_regressions.py:21` 直接 import） |
| `algorithms/registry_discovery.py` | `initialize`, `_load_model_algorithms`, `get_algorithm`, `get_registry_key`, `get_all_algorithms`, `get_algorithm_names` |
| `algorithms/video_data.py` | `_content_digest`, `_prepare_video_data`, `_merge_history` |
| `algorithms/prediction_execution.py` | `_to_registry_result`, `_make_na_result`, `_run_parallel_predictions`, `shutdown` |
| `algorithms/ensemble.py` | `_apply_window_weights`, `_detect_surge_from_cached`, `_apply_coherence_weights`, `_compute_ensemble`, `_compute_log_eta` |
| `algorithms/prediction_pipeline.py` | `predict_all` |
| `algorithms/registry_feedback.py` | `_record_ensemble_feedback`, `reset_ensemble_bias`, `update_accuracy`, `update_ensemble_accuracy`, `get_weights_info` |
| `algorithms/registry_training.py` | `warmup_weights_from_backtest`, `get_trainable_info`, `get_trainable_algorithms` |

类级可变状态与锁（`_algorithms`/`_pool`/`_pool_lock`/`_derived_cache`/`_cache_lock`/`_history_lock`/`_window_weight_history`/`_surge_cache`/`_prev_ensemble_pred`）**全部留在门面类**。

**`_prepare_video_data`（L243–449, CC52）→ 9 段**：`_normalize_history_tuples`(248–275)、`_get_cached_features`(278–286)、`_compute_velocity_features`(289–316)、`_add_motion_features`(317–324)、`_compute_robust_velocity`(330–391，再拆 `_clean_recent_rates`/`_recover_freeze_velocity`/`_mad_weighted_velocity`)、`_compute_lifecycle_features`(396–415)、`_add_lag_and_rolling_features`(416–431)、`_build_video_data`(435–449)。**锁定**：返回的 `derived_features` 与缓存中对象同一引用，勿引入拷贝；`velocity_polyfit` 存在且为 0 时不得回退到顶层 `velocity`。

**`predict_all`（L835–998, CC37）→ 10 阶段**：`_prepare_prediction_input`(851–857)、`_inject_live_features`(859–867)、`_resolve_threshold_anchor`(869–879)、`_record_feedback_and_run_predictions`(881–890)、`_weight_and_combine_predictions`(892–916，含两次"重建 valid_predictions"必须保留)、`_attach_eta_consensus`(918–938)、`_apply_surge_correction`(940–966，钳位 `[0.4,1.0]`)、`_apply_bias_correction`(968–985)、`_log_prediction_summary`(987–996)。

**顺序（12 步，摘要）**：① 测试（85 个既有用例基线）→ ② `_LRUDict` 外移 → ③ video_data mixin 原样搬 → ④ 分解 `_prepare_video_data`（每次一段）→ ⑤ discovery → ⑥ execution（保留真实 ThreadPoolExecutor）→ ⑦ 分解 `_run_parallel_predictions` → ⑧ ensemble mixin → ⑨ 分解 `_compute_log_eta`/coherence/ensemble → ⑩ 分解 `predict_all` → ⑪ feedback/training → ⑫ 门面收口。
**调用方/风险**：`predict_all` ← `ui/monitor/_prediction.py:345`、`ui/crossover_analysis.py:558`、`tests/test_model_algorithms.py:252`、`scripts/characterize_algorithms.py:151`；`_prepare_video_data` ← `tests/test_defect_regressions.py:33,46,218,219`、`scripts/characterize_algorithms.py:55`（私有名需保留）；`get_registry_key` ← `checkpoint_manager.py:477`。结果顺序为 `as_completed` 完成序，勿排序。

---

### 9.2 `algorithms/base.py` — 858 LOC

**热点实测**：`detect_surge` **CC37**（L539–703，165 行）·`calculate_velocity` C17（L333–392）·`_npu_infer` CC12（L793–858）。

**拆分目标（`BaseAlgorithm` 保留于 `algorithms/base.py`，Mixin 组合）**

| 新模块 | 移入符号 |
|---|---|
| `algorithms/prediction_result.py` | `PredictionResult`（**必须 re-export**：约 159 个文件 `from algorithms.base import BaseAlgorithm, PredictionResult`） |
| `algorithms/base_results.py` | `_fallback`, `_std_result`, `_to_prediction_result` |
| `algorithms/history_features.py` | `_normalize_history`, `_prepare_timeseries_data`, `_timestamp_sort_key`, `calculate_velocity`, `get_video_age_hours`, `_extract_view_series`, `_calc_velocity_window`, `_find_period_window`, `_TS_FMT` |
| `algorithms/model_metrics.py` | `_growth_confidence`, `_safe_curve_fit`, `get_engagement_rate`, `get_quality_score`, 常量 `_W_*` |
| `algorithms/surge_detection.py` | `detect_surge`, `_compute_surge_adjusted_velocity`, `calculate_surge_aware_velocity`, `get_surge_decay_factor` |
| `algorithms/npu_adapter.py` | `_npu_infer` |

**`detect_surge`（L539–703, CC37）→ 10 段**：`_default_surge_result`(559–576)、`_extract_surge_series`(578–582)、`_calculate_surge_windows`(584–598)、`_calculate_period_comparisons`(600–619)、`_populate_surge_metrics`(621–636)、classify(642–682 → `_is_seasonal_surge`/`_classify_ratio_surge`/`_apply_seasonal_override`)、`_adjust_half_life_for_age`(684–693)。阈值 3.0/2.0/1.5/1.3、age 系数 0.6/0.8/1.3、钳位 `[1.0,24.0]` 全部冻结。
**`calculate_velocity`（L333–392, CC17）→ 4 段**：`_get_precomputed_velocity`(339–349，优先级：`velocity_robust_hourly`>存在 `velocity_polyfit`(含 0)>`velocity`>polyfit>两点)、`_ordered_history`(351–359)、`_polyfit_velocity`(361–371)、`_two_point_velocity`(372–389)。
**顺序（10 步）**：测试 → `PredictionResult` 外移 → result mixin → history mixin（原样）→ 分解 `calculate_velocity` → metrics mixin → surge mixin（原样）→ 分解 `detect_surge` → npu adapter → 门面校验。
**风险**：`calculate_velocity` **163 处调用**、`_normalize_history` 11 处、`_prepare_timeseries_data` 4 处（详见分析）；首轮必须零调用方改动。

---

### 9.3 `algorithms/models/deep_learning/_torch_upgrade.py` — 2577 LOC，58 顶层符号（36 类）

**热点实测**：`try_torch_predict` **CC50**（L1928–2150，223 行）·`_rank_backends` **CC22**（L2159–2249）·`_try_npu_predict` C14·`load_checkpoint_model` C12。**41 个文件**直接 import。

**拆分目标**：模型类按建模范式拆 8 个 `_torch_models_*.py`（recurrent / attention / segmented / decomposition / mixing / frequency / convolutional / specialized）；共用层 `_torch_layers.py`（`RevIN`/`nn_pad1d`/`nn_avg_pool1d`，避免循环依赖）；基础设施拆 `_torch_features.py`、`_torch_checkpoint.py`、`_torch_cache.py`、`_torch_backends.py`、`_torch_result.py`、`_torch_inference.py`。`_torch_upgrade.py` 保留为**兼容门面**（含 `__all__` 与 torch 缺失时的 `None` 占位）。
**关键约束**：`_GPU_MODEL_LRU`/`_model_load_semaphore`/`_BENCHMARK_LOCK` 各只能有一个归属模块；缓存键 `algo_id` vs `f"{algo_id}@{bvid}"` 不得归一化；后端顺序（`cuda` 跳过 ONNX、`onnx_dml`/`cpu` 跳过 torch、`auto` 按缓存排名）不变；`load_checkpoint_model` 先试 H 宽再 H+1 扩。
**`try_torch_predict`（L1928–2150）→ 8 段**：`_ensure_algorithm_inference_state`(1968–1979)、`_resolve_prediction_context`(1981–1998)、`_try_preferred_accelerated_backend`(2000–2038)、`_get_or_load_cached_torch_model`(2048–2086)、`_run_torch_prediction`(2088–2099)、`_retry_after_cuda_oom`(2101–2111)、`_try_npu_after_torch_failure`(2113–2134)、`_try_onnx_after_torch_failure`(2136–2147)。目标 CC≤10。
**`_rank_backends` → 4 段**：`_benchmark_torch_backend`(2174–2200)、`_benchmark_npu_backend`(2202–2222)、`_benchmark_onnx_backend`(2224–2238)、`_cache_backend_ranking`(2240–2249)；benchmark 函数改为**返回数据**而非改共享列表，锁仍由 wrapper 持有。
**顺序（10 步）**：特征化测试 → `_torch_layers` → 8 个模型族模块 → `_torch_features` → `_torch_checkpoint` → `_torch_cache` → `_torch_backends`（含 `_rank_backends` 分解）→ `_torch_result` → `_torch_inference`（含 `try_torch_predict` 分解）→ 门面收口。
**风险**：41 个 import 方（逐文件列出）；`torch.save` 只存 `state_dict`（移动类定义不影响 checkpoint，但需断言无 `torch.save(model)`）。

---

### 9.4 `algorithms/training/checkpoint_manager.py` — 573 LOC

无 CC>15。**拆分**：`checkpoint_storage.py`（`_CheckpointStorageMixin`：`_read/_write_active`、`_read/_write_metadata`）、`checkpoint_queries.py`（`_CheckpointQueryMixin`）、`checkpoint_mutations.py`（`_CheckpointMutationMixin`）、`checkpoint_catalog.py`（6 个模块函数）。`CheckpointManager` 类与导入路径不变，**必须 re-export** `CheckpointManager`/`load_best_checkpoint`/`list_video_finetune_bvids`/`list_all_trained_algorithms`/`get_all_activation_status`/`activate_latest_for_all`。
**顺序（5 步）**：临时目录特征化测试 → storage mixin → query mixin → mutation mixin → catalog + re-export。
**风险**：`checkpoint_catalog` 与 `checkpoint_manager` 双向引用 → **在门面底部再 import/再导出 catalog 函数**，或把 manager 类型作为参数传入私有 helper（选前者，diff 更小）。

---

### 9.5 `algorithms/training/trainer.py` — 1014 LOC（+ `trainer_io.py` 待补）

**热点实测**：`ModelTrainer._train_one` **CC31**（L296–469，174 行）·`_train_epoch` **CC29**（L737–900，164 行）·`_init_model_optimizer` CC15（L571–675）·`_prepare_dataset` CC11（L473–569）·`train_global` 93 行。
**拆分目标（`ModelTrainer` 保留门面 + 内部 Mixin，`__init__` 暂不外移）**：`trainer_entrypoints.py`（`train_global`/`finetune_for_video`）、`trainer_workflow.py`（`_train_one` + resume/scheduler/checkpoint 选择 helper）、`trainer_data.py`（`estimate_data_size`/`_prepare_dataset`）、`trainer_setup.py`（`_init_model_optimizer`/`_instantiate_algorithm`/`_default_preprocess`）、`trainer_epoch.py`（`_check_control`/`_train_epoch` + 增强/loss/优化步 helper）、`trainer_progress.py`（`_validate_and_emit`/`_emit`）。
**顺序（摘要）**：训练特征化测试 → 逐 Mixin 原样搬移 → 逐个分解 `_train_one`/`_train_epoch`/`_init_model_optimizer`/`_prepare_dataset` → 门面收口。关键：resume 元数据、best-checkpoint 选择与清理、AMP/NaN 分支、`warm_start` 与早停状态语义冻结。
**数据缺口**：~~本文件步骤 2+ 与 `trainer_io.py` 章节未完整提取~~ → **已补全如下**。

#### 9.5.1 `algorithms/training/trainer.py` 完整方案

**File summary**：`trainer.py — 1014 LOC，2 顶层符号`（`ModelTrainer` 909 LOC，L91–999；`_default_preprocess` 13 LOC，L1002–1014）。

**符号大纲（top-8 / CC）**：`_train_one` L296–469（174 LOC，**CC31**）·`_train_epoch` L737–900（164，**CC29**）·`_init_model_optimizer` L571–675（105，CC15）·`_prepare_dataset` L473–569（97，CC11）·`train_global` L155–247（93，CC4）·`_validate_and_emit` L902–960（59）·`_check_control` L678–735（58，CC9）·`finetune_for_video` L251–292（42）。

**职责聚类（7）**：①公开入口 ②训练编排 ③数据集/DataLoader ④模型/优化器初始化 ⑤epoch 计算 ⑥运行时控制/调度 ⑦进度与校验。

**拆分**（保留 `ModelTrainer` 门面 + 内部 Mixin；`__init__` 暂不外移）：`trainer_entrypoints.py`(`train_global`/`finetune_for_video`)、`trainer_workflow.py`(`_train_one`+resume/scheduler/checkpoint helper)、`trainer_data.py`(`estimate_data_size`/`_prepare_dataset`)、`trainer_setup.py`(`_init_model_optimizer`/`_instantiate_algorithm`/`_default_preprocess`)、`trainer_epoch.py`(`_check_control`/`_train_epoch`+helper)、`trainer_progress.py`(`_validate_and_emit`/`_emit`)。

**分步（每步独立提交）**：
- **Step1 训练特征化测试**：`estimate_data_size`；`_prepare_dataset`（零样本 / 小集无验证 / 确定性分割 / batch 缩放 / CPU·CUDA 预载）；`_init_model_optimizer`（视频优先·全局回退·不兼容回退·H/H+1 扩头·默认/覆盖优化器）；`_check_control`；`_train_epoch`（无增强·label noise·MixUp·feature dropout·amplitude·activation decay·NaN/Inf 早停·grad clip·AMP）；`_train_one`（resume·scheduler 恢复·每 epoch 存档·best 保留·早停）；回调载荷与异常隔离。验证 `python -m pytest tests/test_trainer_data.py tests/test_trainer_setup.py tests/test_trainer_epoch.py tests/test_trainer_workflow.py -q`。回滚：删测试。
- **Step2 抽进度**：`_validate_and_emit`/`_emit` → `trainer_progress.py`。验证 pytest + `hasattr` 冒烟 + flake8。回滚：整体搬回。
- **Step3 抽数据**：`estimate_data_size`/`_prepare_dataset` → `trainer_data.py`。
- **Step4 抽 setup**：`_init_model_optimizer`/`_instantiate_algorithm`/`_default_preprocess` → `trainer_setup.py`（`_default_preprocess` 过渡期 re-export）。
- **Step5 分解并迁 epoch**：先分解 `_train_epoch`（每段绿测后再下一步），再连同 `_check_control` 迁 `trainer_epoch.py`；目标 `_train_epoch` CC≤10、无 helper >15。
- **Step6 分解并迁 workflow**：先分解 `_train_one`，再迁 `trainer_workflow.py`；目标 CC≤10。
- **Step7 抽入口**：`train_global`/`finetune_for_video` → `trainer_entrypoints.py`。
- **Step8 门面校验**：`python -m radon cc -s algorithms/training/trainer*.py`。

**分解（精确行界）**：
- `_train_one`(296–469)：`_require_trainable_algorithm`(340–345)、`_load_resume_progress`(347–359)、`_build_resumed_scheduler`(370–386)、`_new_training_state`(388–395，建议内部 dataclass)、`_run_training_epochs`(397–452)、`_retain_best_epoch_checkpoint`(453–469)。**训练循环保持同步串行**。
- `_train_epoch`(737–900)：`_batch_report_interval`(761–774)、`_augmentation_config`(776–787)、`_prepare_training_batch`(789–794)、`_apply_target_noise_and_mixup`(796–810)、`_apply_feature_dropout`(812–828)、`_forward_training_loss`(830–858)、`_detect_non_finite_loss`(860–867)、`_backward_and_step`(869–884)、`_emit_batch_progress`(886–898)。**保持 NumPy Beta 采样与 torch permutation 的调用顺序**。
- `_init_model_optimizer`(571–675)：嵌套 `_load_state_dict_dual` 提为模块级 `_load_checkpoint_state(model,state,horizon)`(591–610)、`_load_initial_checkpoint`(612–643)、`_ensure_dual_output`(645–656)、`_training_components`(666–674)；保持"视频优先于全局"与当前宽异常语义。

**调用方**：`ui/finetune_panel.py:699,703`、`ui/detail_panel.py:176,178`、`ui/training_panel.py:425,427,451,453,800,802,990,1012`、`ui/settings_training.py:270-271,418-419`。
**风险**：Mixin MRO 每方法唯一实现、`self.device`/`self._scaler` 先于继承方法初始化；`control_dict` 为可变且被 `pop`/置位，勿拷贝；调度顺序（`_check_control`→epoch→`step_hyperbolic`→validation/checkpoint→`scheduler.update`）冻结；每 epoch 存档、循环结束才删中间档；随机性（seed42 分割、MixUp `np.random.beta`、dropout/permutation torch RNG）不得新增 RNG 调用；DataLoader（GPU `num_workers=0`、CPU 两 worker + persistent）不变。

#### 9.5.2 `algorithms/training/trainer_io.py` 完整方案

**File summary**：`trainer_io.py — 107 LOC，3 顶层符号`，flake8 干净。
**符号**：`save_checkpoint` L22–72（51 LOC，CC10）、`_save_model_to_video_dir` L75–85（11，CC3）、`evaluate_model` L88–107（20，CC5）。
**职责聚类（4）**：①版本化 checkpoint 持久化 ②per-video 模型镜像 ③ONNX 导出（best-effort）④校验评估。
**拆分**：文件已低于 250 LOC，**不做文件级拆分**。若 `trainer_progress.py` 成为 `evaluate_model` 唯一调用方，可迁入其中，或保留 `from algorithms.training.trainer_io import evaluate_model` 兼容 re-export；**不新建 `trainer_evaluation.py`**（除非出现第二个生产调用方）。
**分步**：Step1 特征化测试（metadata 有无 val loader / scheduler 状态 / `_orig_mod` 解包 / 镜像路径 / ONNX 可用·不可用·失败 / 评估 no-grad·squeeze·H+1 截断·批次均值·空 loader 返 0）。Step2 仅提内部 helper（不拆文件）：`_unwrap_compiled_model`(取自 L60/L81)、`_build_checkpoint_metadata`(L47–59)，不改公开签名。Step3 仅在 trainer-progress 拆分时移动 `evaluate_model`，并保留≥1 个迁移周期的兼容 re-export。
**分解**：`save_checkpoint`(22–72)：`_build_checkpoint_metadata`(47–59)、`_unwrap_compiled_model`(60–61,81–82)、`_try_export_onnx`(65–71)；顶层顺序不变（建 metadata→存版本→存镜像→ONNX→返回版本）。`evaluate_model`(88–107) 保持不动。
**调用方**：`trainer.py:74` 导入三符号；实际调用 `trainer.py:442`(`save_checkpoint`)、`trainer.py:942`(`evaluate_model`)；`_save_model_to_video_dir` 仅 `save_checkpoint` 内部调用（`trainer.py` 导入未用）。
**风险**：`trainer.py` 删未用导入前确认无导入副作用（当前无）；ONNX 导出刻意非致命；`_try_export_onnx` 的惰性 import 与异常边界不变；`_orig_mod` 对编译模型保持一致。

---

### 9.6 `ui/main_gui_events.py` / `main_gui.py` / `main_gui_tick.py` / `main_gui_data.py`

**架构事实**：项目已是"函数模块（`fn(gui,...)`）+ `BilibiliMonitorGUI` 薄包装方法（约 50 个）"。外部（`bottom_bar`/`dialogs`/`monitor/_service` 等）只调用**包装方法**。**保持 delegation，不引入 Mixin**（Mixin 会与既有两模块风格分裂；`__getattr__` 魔法会破坏 `hasattr(gui,"_select_video")` 探测）。包装方法一律原样保留。

**实测**：`main_gui_events.py` 1183 LOC / 47 函数（`build_push_msg` C14、`run_post_training_predict` C13、`build_daily_push_msg` C11；最大 `show_update_dialog` 151 行）；`main_gui.py` 915 LOC / 1 类 77 法（`_build_titlebar` **221 行**、`_init_tray` C10）；`main_gui_tick.py` 319 LOC（**`scan_alerts_background` D21、`global_tick` C16 —— 全批仅有的两个 CC>15**）；`main_gui_data.py` 181 LOC（健康，不拆）。

**拆分目标**：`ui/push_formatters.py`（两个消息构建器）、`ui/push_cycle.py`、`ui/update_flow.py`、`ui/app_lifecycle.py`（`on_exit`）、`ui/model_activation.py`、`ui/refresh_cycle.py`、`ui/video_ops.py`（增删撤销）、`ui/training_callbacks.py`、`ui/panel_callbacks.py`（`prediction_done`/`copy_bvid`/`open_*`）、`ui/maintenance_tasks.py`（tick 的养护+告警）、`ui/tray_control.py`、`ui/titlebar.py`、`ui/window_layout.py`。
**高复杂度函数拆解（精确行界）**：
- `build_push_msg`（1040–1097）→ `_yearly_score_value`(1054–1060)/`_velocity_and_eta`(1062–1078)/`_top_algo_lines`(1080–1089)/`_push_video_section`(1047–1095)；保留 `with gui._data_lock:` 快照。
- `build_daily_push_msg`（982–1037）→ `_daily_increment`(1001–1012)/`_prediction_suffix`(1022–1030)/`_daily_video_section`(991–1035)。
- `run_post_training_predict`（883–948）→ `_predict_one_safe`(896–905)/`_run_prediction_pool`(907–913，`max_workers=min(len,8)`)/`_npu_stats_fragment`(917–934)/`_refresh_selected_prediction`(936–947，`invoke`/`invoke_later` 保持)。
- `show_update_dialog`（124–274）→ `_build_update_header`(142–167)/`_build_changelog_area`(169–190)/`_build_channel_selector`(192–216)/`_build_update_actions`(218–273)。
- `remove_monitor`（672–728）→ `_detach_video`(686–701)/`_reset_panels_after_remove`(702–707)/`_schedule_finalize`(714–728，`QTimer(gui)`+30s+`_delete_timers` 语义冻结)。
- `global_tick`（64–116, C16）→ `_scan_timer_state`(74–83)/`_refresh_countdown_badge`(85–92，保留 `_last_countdown_text` 去重)/`_refresh_mode_pill`(94–99)/`_refresh_interval_text`(101–104)/`_run_maintenance_slots`(106–114，槽位算术与线程名原样)。目标 CC≤4。
- `scan_alerts_background`（207–303, D21）→ `_load_recent_records`(227–240)/`_collect_alert_hits`(221–247)/`_log_all_hits`(258–263)/`_format_high_alert_message`(268–285)/`_dispatch_high_alerts`(286–303)。目标 CC≤5。
- `_build_titlebar`（339–559）→ `build_logo_block`(347–369)/`build_nav_buttons`(371–417)/`build_titlebar_right`(420–497)/`build_settings_menu`(499–556，菜单表提为常量)。
- `_init_tray`（136–188, C10）→ `resolve_tray_icon`(145–154)/`build_tray_menu`(159–173)。

**顺序（S0–S16，摘要）**：S0 结构测试（AST 断言 77 个包装方法 + 消息构建器 stub 测试）→ S1 消息构建器外移（**同 commit 改 `report_scheduler.py:497` 的 import**）→ S2 分解消息构建器 → S3 push_cycle → S4 update_flow → S5 分解 show_update_dialog → S6 model_activation → S7 training_callbacks → S8 video_ops → S9 refresh_cycle → S10 app_lifecycle/panel_callbacks → S11 删除空 events 文件 + 清理 F401 → S12 tray_control → S13 titlebar/window_layout → S14 tick 拆分 → S15（可选）main_gui_data 微拆 → S16 终检 + 手工冒烟。
**风险**：`report_scheduler.py:497` 是 events 之外唯一外部 import；`main_gui.py:760/884` 的函数内惰性 import 需同步改指向；`_pending_deletes`/`_delete_timers` 是 `hasattr` 软创建（首次删除语义不能"清理"）；`ui/invoker.py` 的 `invoke` 调用必须仍从 worker 线程发出；QTimer/QDialog/QShortcut 的 parent 传参不得改。

---

### 9.7 `ui/snapshot_tab.py` — 862 LOC，MI 5.81

**热点**：`SnapshotBarChart.paintEvent` **CC40**（L68–299，232 行）·`_apply_custom_range` **CC24**（L632–693）·`_collect_data` CC17（L799–841）。
**拆分**：`ui/snapshot_bar_chart.py`（`SnapshotBarChart` + 绘制 pass）、`ui/snapshot_data.py`（纯函数 `smart_sample`/`find_best_record`/`parse_range_entry`/`filter_ts_by_range`/`collect_metric_bars`）；`snapshot_tab.py` 保留 `SnapshotTab` 并 re-export `SnapshotBarChart`。
**`paintEvent` 分遍（单 QPainter：构造与 `end()` 只留 paintEvent，pass 只接收 painter）**：`_paint_bg_and_placeholder`(72–85)、`_compute_layout`(91–142，纯计算可单测)、`_paint_metric_frame`(179–210)、`_paint_bar_group`/`_paint_single_bar`(213–284，内层 227–280，配色系数 0.15→0.35 冻结)、`_paint_milestone_hint`(292–297)。目标 CC≤6。
**`_apply_custom_range` → 2 纯函数**：`parse_range_entry`(644–664，消除起止重复) → `filter_ts_by_range`(670–682)；方法体仅留校验/提示/写 listbox。
**调用方**：仅 `ui/data_comparison.py:150,159`（惰性 import）。**风险**：绘制等价需 PNG 对比；`int()` 舍入与钳位表达式逐行平移。

---

### 9.8 `ui/danmaku_analysis.py` — 987 LOC，MI 2.92（全仓最低）

**热点**：`_render_hour_sentiment` **CC27**（L448–539）·`_fetch_danmaku` C14（L304–331）·`_load_local_llm_result` C14（L777–815）·`_display_results` C11。
**拆分**：`ui/danmaku_charts.py`（`_PieWidget`/`_TimeHistogramWidget`）；`ui/danmaku_llm_mixin.py`（`DanmakuLLMMixin`，11 个 LLM 方法；Mixin **不定义 `__init__`**）；`danmaku_analysis.py` 保留窗口 + 抓取 + 分析编排。
**`_render_hour_sentiment` → 5 段**：`_hour_rows_data`(454–469)/`_bucket_by_hour`(471–478)/`_classify_hour_sentiment`(488–497，阈值 0.5/0.1 提常量)/`_compute_hour_rows`(481–499)/`_fill_hour_table`(502–527)/`_format_hour_summary`(529–535)。
**`_fetch_danmaku` → `_load_danmaku_from_local`**(306–317)，主方法仅留 API 三段（info→cid→danmaku）。
**调用方**：仅 `ui/dialogs.py:474`。**风险**：Mixin 化后 `_show_llm_summary` 等只读 `self` 字段，初始化时序不变；`QTimer.singleShot(100, lambda: self...)`(810) 原样平移。

---

### 9.9 `ui/detail_panel.py` — 976 LOC，MI 14.02

**热点**：`_fill_detail_text` **CC17**（L805–944，140 行）·`_rebuild_stat_bar` **CC16**（L578–656）·`_build` 204 行。
**拆分**：`ui/finetune_dialog.py`（`FinetuneDialog` 整类，`_open_finetune_dialog` 保持惰性 import）；`ui/detail_stat_bar.py`（`STAT_FIELDS` 合并双份字段表 + `stat_value_text` + `build_stat_bar` + `update_stat_labels`）；`ui/detail_text.py`（`render_detail_html` 等纯函数）。`DetailPanel` 方法名/签名不变（外部经 `gui.detail.update_stat_bar(video)` 访问）。
**`_fill_detail_text` →** `detail_fingerprint`(805–818)/`detail_main_lines`(820–871)/`score_block_rows`(888–924，周刊/年刊参数化合并)/`history_block_html`(926–941)/`render_detail_html`(873–886)。**`_rebuild_stat_bar`** 字段循环→`build_stat_bar`，QSS 提常量。
**调用方**：`ui/main_gui.py:30`；`main_gui_events.py:478,504,505,703`；`monitor/_service.py:344,354`。**风险**：`_rebuild_stat_bar({})` 以空 dict 触发重建，`build_stat_bar` 必须保留"已建且无数据即跳过"守卫；`_clear_header` 的"清 layout 保对象"模式不得破坏；`chart_mode`/`chart_canvas`/`current_tab` 属性必须留在 `DetailPanel`。

---

### 9.10 `ui/prediction_accuracy.py` — 375 LOC

**热点**：`_load_data` **CC38**（L124–316，193 行，全文件唯一巨兽）。
**拆分**：`ui/prediction_accuracy_data.py`（纯函数 `parse_record_index`/`parse_pred_ts`/`nearest_views_at`/`score_row`/`evaluate_rows`/`summary_text`）；`_load_data` 仅留"取控件→取记录→SQL→调 `evaluate_rows`→渲染"。SQL 参数化字符串原地保留。
**拆解**：`_current_filters`(125–140)、`_fetch_prediction_rows`(142–169)、`parse_record_index`(185–207)、`evaluate_rows`(219–291，含 `bisect_left` 三岔 244–263 + 聚合 280–288)、`summary_text`(299–316)。目标 CC≤8。
**调用方**：仅 `ui/dialogs.py:528`。**风险**：`bisect_left` 依赖 `_rec_timestamps` 升序（`get_all_records` 原序假设），纯函数化须保持输入不排序；`ranking_view and accuracy>0` 短路语义冻结。

---

### 9.11 `ui/settings_window.py` — 374 LOC

**热点**：`_persist_settings` **CC36**（L253–335，83 行）·`_apply_settings` C12·`_validate_settings` C10。
**拆分**：首选**类内提取**（9 个 Mixin 通过 `self` 交叉访问字段，不可新开继承层级/改 Mixin 顺序）；可选第二步再把纯函数下沉 `ui/settings_persist.py`。
**拆解**：`_widget_value(w)`（消除 ≥6 处 `w.text() if hasattr(w,'text') else w.value()`）、`_onebot_cfg`(261–268)、`_collect_webhooks`(269–279)、`_persist_core_numbers`(280–290，`hasattr` 守卫保留)、`_collect_thresholds`(292–304)、`_encrypt_secrets`(306–314)、`_restore_plaintext`(323–335)、`_apply_theme_preference`(356–371)。目标 CC≤8。
**不可变契约**：加密→`save_config`(321)→还原明文(323–335) 的**顺序**；验收为配置 JSON 字节级 diff。
**调用方**：`ui/dialogs.py:266`。

---

### 9.12 训练 UI：`training_panel.py` / `training_base.py` / `finetune_panel.py` / `settings_training.py`

**实测**：`training_panel.py` 1518 LOC/MI 0.00（`_on_stage_epoch` **CC23** L1158–1255、`_validate_train_params` C15 L848–915、`_on_stage_done`/`_on_stage_all_done` B10）；`training_base.py` 689 LOC/MI 17.35（`compute_lr_scale` **CC20** L226–283、`compute_weight_decay` C15 L324–357、`_update_chart` C15 L471–506、`_check_overfitting` C11）；`finetune_panel.py` 1070 LOC/MI 8.47（`_handle_finetune_progress` **CC25** L612–693、`_build_finetune_config` C19 L540–610）；`settings_training.py` 551 LOC/MI 23.76（`_build_training_tab` 187 行、`_handle_stage` C15 L481–542、`_refresh_algo_list` C12 L299–368）。
**架构**：`TrainingPanel(BaseTrainingPanel, VersionManagerMixin)`、`FinetunePanel(BaseTrainingPanel)`、`SettingsTrainingMixin(AsyncQueueRunner, VersionManagerMixin)`；三者共用 `ui/async_queue_runner.py` 的 `_launch_worker`/`_poll_progress`/`_handle_stage`/`_cleanup_training` 契约；跨线程经队列 + `QTimer` 轮询（部分直接 `invoke`）。
**拆分目标**：`ui/training_monitor.py`（把纯逻辑 `TrainingMonitor` 从 `training_base.py` 抽出，`training_base.py` re-export 以兼容 2 个 import 点）、`ui/training_dialogs.py`（批量微调/配置弹窗）、`ui/training_stage_handlers.py`（阶段消息处理 Mixin，压缩 `_on_stage_*` 与 `_handle_stage`）、`ui/training_widgets.py`（复用算法勾选行构建——修复 REFACTOR_REPORT U3 记录的 3 份重复：`training_panel.py:472-554`、`settings_training.py:295-363`、`finetune_panel.py:115-210`）。
**拆解要点**：`_on_stage_epoch`(1158–1255) → 提取 EMA-ETA 块(1186–1213) 为 `_update_epoch_eta`、状态格式化(1215–1219)；`compute_lr_scale`/`compute_weight_decay`/`_update_chart` 各提小 helper；`_handle_finetune_progress`(612–693) → 解析 `(algo,bvid)` 键、`TrainingMonitor` 查找、UI 分组更新；`_build_finetune_config`(540–610) → 解析层速率/per-mode 分支；`_build_training_tab`(35–221) → `_build_device_row`/`_build_algo_picker`/`_build_train_buttons`；`_handle_stage`(481–542) → 每 stage 子方法。
**调用方**：`TrainingPanel`/`FinetunePanel` ← 仅 `ui/main_gui.py:627-630,634-637`（惰性）；`SettingsTrainingMixin` ← 仅 `ui/settings_window.py:43,55`；`BaseTrainingPanel`/`TrainingMonitor` ← `training_panel.py:37`、`finetune_panel.py:34`；`VersionManagerMixin` ← `ui/training_version.py`。**风险**：信号/槽与 `AsyncQueueRunner` 契约、`_tr_progress` 进度条命名、`invoke` 回主线程不得改。（补全如下）

#### 9.12.1 `ui/training_base.py` — 689 LOC，MI B(17.35)

- **顶层**：`TrainingMonitor`(L39–357，纯 Python) · `BaseTrainingPanel(AsyncQueueRunner, QWidget)`(L365–689) · `logger`(L32)。
- **top-8 / CC**：`compute_lr_scale` L226–283（58，**C20**）·`__init__` L378–428（51）·`_build_log_widgets` L533–571（39）·`_build_chart_widgets` L434–469（36）·`_update_chart` L471–506（36，C15）·`compute_weight_decay` L324–357（34，C15）·`compute_grad_clip` L287–320（34，B9）·`_check_overfitting` L99–122 / `_evaluate` L188–211（24/24）。
- **聚类(4)**：纯训练质量推理 / 面板 chrome 构建 / 实时刷新管线 / AsyncQueueRunner 契约特化。
- **拆分**：新增 `ui/training_monitor.py` 原样移 `TrainingMonitor`(L39–357)；`training_base.py` 加 `from ui.training_monitor import TrainingMonitor` 与 `__all__ = ["BaseTrainingPanel","TrainingMonitor"]`（兼容 `training_panel.py:37`、`finetune_panel.py:34`）。**不再碎片化**（chart/log 构建器共享 `_fig/_canvas/_ax/_log_text`，留原地）。
- **步骤**：①抽 `TrainingMonitor`——验证 `flake8 ui/training_base.py ui/training_monitor.py` + `python -c "from ui.training_base import BaseTrainingPanel, TrainingMonitor; TrainingMonitor().get_status_display()"` + `radon mi -s`（期望 A）；回滚 `git checkout -- ui/training_base.py; git clean -f ui/training_monitor.py`。②分解 `compute_lr_scale`。
- **分解**：`compute_lr_scale`(226–283) 改 dispatch dict：`_lr_for_explosion`(240–249)/`_lr_for_oscillation`(251–261)/`_lr_for_overfit`(262–270)/`_lr_for_underfit`(272–282)，前缀(226–239)留调用者，返回同 `scale/reason` 结构。`compute_weight_decay`(324–357)→`_wd_signals(valids)`(335–352) 返回小 namedtuple，阈值阶梯留调用者。`_update_chart`(471–506)→`_series_arrays(pts)`(486–497) 纯函数，matplotlib 调用留 Qt 方法。
- **风险**：仅两处 import；`_cleanup_training` L679–689 为模板供子类 `super()`，签名不变；matplotlib `FigureCanvas` 主线程（`__init__` 内构造安全）；信号按属性名绑定，名字在 MRO 下须保留。

#### 9.12.2 `ui/training_panel.py` — 1518 LOC，MI C(0.00)

- **顶层**：`TrainingPanel(BaseTrainingPanel, VersionManagerMixin)` L51–1518 · `logger`/`_torch_available`。
- **top-8 / CC**：`_build_controls` L233–357（125）·`_build_batch_dialog` L674–796（123）·`_start_train_thread` L943–1062（120）·`_on_stage_epoch` L1158–1255（98，**D23**）·`_refresh_algo_list` L474–557（84，B9）·`_validate_train_params` L848–915（68，C15）·`_build_algo_section` L137–204（68）·`_build_ui` L78–133（56）。
- **聚类(5)**：①构建与设备/数据状态 ②算法清单 ③批量微调对话框 ④全局训练生命周期 ⑤阶段消息分发与运行簿记。
- **拆分**：新增 `ui/training_batch_dialog.py`（cluster③ L600–832 → `BatchFinetuneDialog(QDialog)`，把内联闭包 `_ft_log`/`_start_ft` 提为方法）、`ui/training_stage_mixin.py`（`TrainingStageMixin`：`STAGE_HANDLERS`/`_handle_stage`/`_on_stage_*`/`_fmt_duration`/`_compute_lr_suggestion`/`_on_monitor_changed` + log 文件管理）；`training_panel.py` 瘦身至 clusters①②④，类签名 `TrainingPanel(TrainingStageMixin, BaseTrainingPanel, VersionManagerMixin)`。
- **步骤**：①抽批量对话框——验证 flake8 + `python -c "import ui.training_batch_dialog, ui.training_panel"` + `radon raw`（≈1285 LOC）。②抽 stage mixin——验证 `hasattr(TrainingPanel,'_on_stage_epoch'/'STAGE_HANDLERS')` + `compileall ui/` + 手动 1-epoch 训练观察进度/ETA/取消。③分解 `_on_stage_epoch`/`_validate_train_params`。
- **分解**：`_on_stage_epoch`(1158–1255)→`_compute_eta`(1179–1213，读 `_epoch_times/_last_epoch_elapsed/_algo_durations/_total_algos`，返回 `(total_remaining, algo_eta)` EMA 块)、`_format_epoch_status`(1224–1246)，保留 L1160–1177(conf 取色·`pct/vtxt` 写入) 与尾部 `_update_chart/_refresh_monitor`。`_validate_train_params`(848–915)→`_gather_train_params`(856–870)、`_vram_parallel_guard`(873–888)、`_confirm_lr_choice`(889–914)。`_cleanup_training`(1379–1407) 可选提 `_report_training_outcome`(1397–1406)。
- **风险**：唯一外部调用方 `main_gui._switch_nav`(625–631，只需 模块路径+类名+`on_show()` 稳定)；MRO 顺序（mixin 无 `__init__`；`VersionManagerMixin._on_manage_versions` + `training_version.py:346` 调 `self._refresh_algo_list()` 名字不可改）；`_start_train_thread._worker`(1028–1062) 只 `put` 消息不碰控件；`_refresh_data_size._worker`(449–463) 用 `invoke`；`STAGE_HANDLERS`(1085) 经 `getattr(self, name)`(1100) 映射，表须随方法迁移；`_algo_row_refs`(64) 跨 cluster 耦合 → stage handler 以同对象 Mixin 承载。

#### 9.12.3 `ui/finetune_panel.py` — 1070 LOC，MI C(8.47)

- **顶层**：`FinetunePanel(BaseTrainingPanel)` L47–1070。
- **top-8 / CC**：`_start_finetune_worker` L695–805（111）·`_build_left` L115–206（92）·`_refresh_algos` L369–459（91，B10）·`_handle_finetune_progress` L612–693（82，**D25**）·`_build_controls` L250–325（76）·`_build_finetune_config` L540–610（71，**C19**）·`_on_stage_epoch` L868–920（53，B9）·`_on_monitor_changed` L1035–1058（24，B8）。
- **聚类(5)**：布局构建 / 数据刷新与选择 / 运行配置(纯) / 执行 / 阶段分发与监视 UI。
- **拆分**：新增 `ui/finetune_config.py`（`build_finetune_config(values, videos, algos) -> dict` 纯函数，最高价值）；`_start_finetune_worker`/`_handle_finetune_progress` 留面板但分解；**不复用** training_panel 的 stage mixin（per-(algo,video) key 差异）；`ui/algo_checklist.py` 三处行复用（REFACTOR_REPORT U3）列为后续独立项。
- **步骤**：①抽 `build_finetune_config`（纯函数 smoke 覆盖各 mode 分支，输出 dict 前后对比）。②分解 `_handle_finetune_progress`（脚本化 msg 序列断言 `_auto_monitors` 键与状态文本一致）。
- **分解**：`_handle_finetune_progress`(612–693)→`_progress_key(msg)`(612–632)、`_monitor_for(key)`(633±3，按 `_auto_monitors` 懒建)、`_format_finetune_status(msg, monitor)`（尾部状态/ETA，与 9.12.2 `_format_epoch_status` 对称）。`_build_finetune_config`(540–610)→`_base_config(values)`(540–565)、`_scoped_config(cfg,videos,algos)`(566–610)，校验(QMessageBox)留面板。`_refresh_algos`(369–459) 可选提 `_algo_row`(400–459)。
- **风险**：唯一调用方 `main_gui.py:634–637`；`_auto_monitors`(66) 被 `_on_monitor_changed`(1035–1058)/`_get_chart_series`(1065–1070) 读；`_handle_finetune_progress` 在 `_poll_progress` 主线程内执行 → 拆出的 helper 不得起线程/定时器，`invoke` 调用点不得移入纯 helper；stage 字面量须与 worker 同步（无枚举）。

#### 9.12.4 `ui/settings_training.py` — 551 LOC，MI A(23.76)

- **顶层**：`SettingsTrainingMixin(AsyncQueueRunner, VersionManagerMixin)` L32–550。
- **top-8 / CC**：`_build_training_tab` L35–221（187）·`_refresh_algo_list` L299–368（70，C12）·`_handle_stage` L481–542（62，C15）·`_on_train_start` L381–435（55，B6）·`_refresh_data_size` L264–296（33）·`_refresh_device_info` L224–251（28，B6）·`_on_export_checkpoints` L445–461（17）·`_on_import_checkpoints` L464–478（15）。
- **聚类(4)**：Tab 构建 / 设备与数据刷新 / 算法选择 / 训练生命周期与 checkpoint I/O。
- **拆分**：**不新建模块**（构建方法绑定 `_tr_*` 状态）；类内分解；`_refresh_algo_list` 未来接 `ui/algo_checklist.py`；`_handle_stage` 统一为 `STAGE_HANDLERS` 字典 + 每 stage 小方法（与 9.12.2/9.12.3 一致）。
- **步骤**：①分解 `_build_training_tab`——验证 flake8 + `python run.py` 打开设置→训练 tab 渲染一致。②重构 `_handle_stage` 为 handler-dict——脚本化 msg 驱动对比 `_tr_*` 状态。
- **分解**：`_build_training_tab`(35–221)→`_build_tr_device_row`/`_build_tr_data_row`/`_build_tr_algo_picker`/`_build_tr_controls`（**保持控件创建顺序**，布局顺序即可见行为）。`_handle_stage`(481–542)→`_TR_STAGE_HANDLERS` 字典 + `_tr_on_start/_tr_on_epoch/_tr_on_done/_tr_on_all_done/_tr_on_error` 等（各 ≤B5），入口保留终态 `return True` 语义供 `AsyncQueueRunner._poll_progress`。
- **风险**：调用方 `settings_window.py:43,55`；`AsyncQueueRunner` 依赖 `_tr_progress` 命名（改名的脉冲动画静默失效）；`VersionManagerMixin` 批量删除后调 `self._refresh_algo_list()`（`training_version.py:346`）名字不可改；`_handle_stage` 运行于 QTimer 轮询主线程；改后 `python -c "from ui.settings_training import SettingsTrainingMixin"` 须通过。

**跨文件执行顺序**：`training_base.py`(先做，解除两面板 import) → `settings_training.py`(最小，验证特征化手法) → `finetune_panel.py` → `training_panel.py`(最大，复用前两者模式)。预计收缩：`training_panel.py` 1518→~1050、`finetune_panel.py` 1070→~950；消除两个 D 级（`_on_stage_epoch` D23→≤C、`_handle_finetune_progress` D25→≤C、`compute_lr_scale` C20→≤B）。

---

### 9.13 跨文件建议执行顺序（按收益/风险）

1. **`registry.py` + `base.py` Mixin 化**（收益最大：MI 0.00、CC52/37；且调用方零改动）。
2. **`_torch_upgrade.py` 拆分**（第二收益：每轮预测影响面）。
3. **`training_base.py` 抽 `TrainingMonitor`**（纯逻辑、零 Qt，风险最低的起点）。
4. **`main_gui*` 模块化**（先 S0–S13，tick 的 CC21/16 随后）。
5. **复杂面板**：`settings_window` → `prediction_accuracy` → `danmaku_analysis` → `detail_panel` → `snapshot_tab`（绘制等价验证成本最高，压后）。
6. **共享件去重**：算法勾选行构建（3 份）、`open_*` 短路、主题色回归。

### 9.14 数据缺口（本次未完整取得）

- ~~`trainer.py` 步骤 2+ 与 `trainer_io.py` 的完整章节~~ → **已补全至 9.5.1 / 9.5.2**。
- ~~训练 UI 最终排版的完整 7 段~~ → **已补全至 9.12.1–9.12.4**。
- 缺口已全部补齐；第 10.1/10.3 中对应行现均为可直接开工状态。

---

## 10. 待改动方法清单（可直接执行）

> 用法：本清单把全部计划拆成**可独立开工的最小单元**。每行给出：位置（文件:行）· 符号/方法 · 关联项 · 改动方法 · 验证。任何 agent 取一行即可照做；完成后按"验证"列执行，失败按通用回滚（`git restore <文件>` / 删新建文件）。详细设计见对应 M# 与第 9 章。
> **前置强制**：① 先 `conda activate bili`（唯一允许的环境，见 §1.8）；② 每行改动**单独一个 commit、只做一件事**（见 §1.7）；③ 每行改动完成后先跑该行"验证"再提交。

### 10.1 预测引擎（algorithms/）

| 位置 | 符号/方法 | 关联 | 改动方法 | 验证 |
|---|---|---|---|---|
| `models/deep_learning/_torch_upgrade.py:1986` | `try_torch_predict` | M1.1 | 入口先判 `_cached_torch_model`+`_cached_bvid`，命中即跳过 `load_best_checkpoint`；缓存加 `(active.json mtime, *.pt mtime/size)` 签名 | 单测：二次调用 `load_best_checkpoint` 调用数=0 |
| `training/checkpoint_manager.py:430-448,253` | `_try_load_checkpoint` / `load` | M1.1 | 抽 `_get_or_load_model(algo,algo_id,bvid,build_fn)` 统一缓存读写 | 同上 |
| `_torch_upgrade.py:1890-1920` | `release_cached_models` | M1.2 | 改按内存压力 + LRU，保留活跃 bvid 模型 | 长跑 RSS 峰值 + 重载次数 |
| `ui/monitor/_prediction.py:440-455` | `_maybe_release_memory` | M1.2 | 去掉固定计数器，改真实内存判定 | 同上 |
| `algorithms/weight_manager.py:173-193` | `update_accuracy` | M1.3 | 新增 `update_accuracy_batch(records)`：一次锁写入→重算一次→标 dirty | 单测重算/落盘 120→1 |
| `algorithms/weight_manager.py:195-237` | `_recalculate_ml_weights` | M1.3 | 保留，由 batch 每周期调用一次 | 数值与旧实现一致 |
| `algorithms/weight_manager.py`（保存） | `_save_weights_sync` | M1.3 | 改 flush 去抖（5–10s / 周期末） | 单测计时 |
| `ui/monitor/_prediction.py:481-492` | 权重反馈循环 | M1.3 | 改调 `update_accuracy_batch` | 单测 |
| `algorithms/online_learner.py:266-283` | `get_algorithm_stats` | M1.4 | 先 `w = get_weights()` 一次，循环用 `w.get(name)` | T=2000 计时线性 |
| `algorithms/online_learner.py:502-512` | `_quick_weight` | M1.4 | 支持传入预计算 weights 快照 | — |
| `algorithms/online_learner.py:217-218,399-423` | `_adjust_eta` | M1.5 | `recent_errors` 维护增量 sum/sumsq；触发改"每周期一次" | 计时 + 数值一致 |
| `algorithms/base.py:436-448` | `get_video_age_hours` | M2.7 | `_sorted` 时用 `history[0]`/预算 `history_age_hours`，不再重排 | pytest |
| `algorithms/base.py:209-227` | `_normalize_history` | M2.7 | 在 `_prepare_video_data` 预算一次并共享（只读） | pytest |
| `models/simple/short_term_hotness.py:70` | `detect_surge` 调用 | M2.7 | 改用 `video_data` 缓存的 surge | pytest |
| `models/advanced/change_point_detection.py:341,345` | `detect_surge`/`get_surge_decay_factor` | M2.7 | 同上，避免重复计算 | pytest |
| `models/statistical/random_forest_simple.py:147` | `predict` 拟合 | M2.6 | 加 `(algo_id,content_digest,n)` 缓存 + 失效 | 历史未变不重训 |
| `models/ensemble/xgboost_simple.py:170` | 同上 | M2.6 | 同上（warm_start 可用则用） | 同上 |
| `models/ensemble/gradient_boost_simple.py:141` | 同上 | M2.6 | 同上 | 同上 |
| `models/ensemble/extra_trees_simple.py:329` | 同上 | M2.6 | 同上 | 同上 |
| `models/ensemble/bagging_simple.py:297,396` | 同上 | M2.6 | 同上 | 同上 |
| `models/statistical/gaussian_process.py:123` | 同上 | M2.6 | 同上 | 同上 |
| `models/ensemble/tabnet_simple.py:158` | 同上 | M2.6 | 同上 | 同上 |
| `models/ensemble/stacking_ensemble.py:170` | 同上 | M2.6 | 同上 | 同上 |
| `models/ensemble/blending_ensemble.py:169` | 同上 | M2.6 | 同上 | 同上 |
| `models/ensemble/residual_correction.py:167` | 同上 | M2.6 | 同上 | 同上 |
| `models/ensemble/quantile_ensemble.py:178` | 同上 | M2.6 | 同上 | 同上 |
| `models/ensemble/ngboost_simple.py:126` | 同上 | M2.6 | 同上 | 同上 |
| `models/statistical/tsfc_classification.py:199` | 同上 | M2.6 | 同上 | 同上 |
| `models/time_series/narx_simple.py:166` | 同上 | M2.6 | 同上 | 同上 |
| `models/growth/logistic_growth.py:209` | `curve_fit` | M2.6 | 缓存 popt + seed p0 | 同内容不重拟合 |
| `models/growth/gompertz_growth.py:213` | 同上 | M2.6 | 同上 | 同上 |
| `models/growth/richards_curve.py:218` | 同上 | M2.6 | 同上 | 同上 |
| `models/growth/weibull_growth.py:216` | 同上 | M2.6 | 同上 | 同上 |
| `models/deep_learning/tabnet_simple.py:240` | `np.random.seed(42)` | M2.10 | 改局部 `np.random.default_rng(42)` | 单测全局 RNG 不受污染 |
| `models/deep_learning/time_moe_simple.py:121` | 同上 | M2.10 | 同上 | 同上 |
| `models/deep_learning/timesfm_simple.py:123` | 同上 | M2.10 | 同上 | 同上 |
| `models/deep_learning/deepar_simple.py:111` | 同上 | M2.10 | 同上 | 同上 |
| `models/deep_learning/diffusion_ts.py:342` | 同上 | M2.10 | 同上 | 同上 |
| `models/deep_learning/diffusion_ts.py:191-207` | 反向扩散 | M2.10 | 100 步改少步采样（DDIM） | 计时 + 结果容差 |
| `models/ensemble/bagging_simple.py:107` | `Optional` 注解 | M1.8 | 补 `from typing import Optional` | `flake8 --select F821` =0 |
| `models/time_series/tbats_simple.py:143` | `forecast` 未定义 | M1.8 | 修/删该死分支（当前被 except 吞） | pytest 命中该分支 |
| `models/*`（4 个 DL 入口） | `try_torch_predict` 输入 | M2.7 | 在 registry 预算 `_torch_input` 一次并共享 | 遍历次数 40×→1× |
| `registry.py:243-449` | `_prepare_video_data` | 9.1 | 拆 9 段（见 9.1） | pytest + radon |
| `registry.py:835-998` | `predict_all` | 9.1 | 拆 10 阶段 | pytest + `scripts/characterize_algorithms.py` |
| `registry.py:550-632` | `_run_parallel_predictions` | 9.1 | 拆 4 段，保留真实 ThreadPoolExecutor | pytest |
| `registry.py:777-832` | `_compute_log_eta` | 9.1 | 拆 4 段，排除规则冻结 | pytest |
| `registry.py:145-188` | `_load_model_algorithms` | 9.1 | 提 discovery mixin | 实例化数量断言 |
| `registry.py:158-182` | 算法实例化 | 9.1 | 惰性实例化重算法 | 启动耗时 |
| `base.py:539-703` | `detect_surge` | 9.2 | 拆 10 段，阈值/系数冻结 | pytest |
| `base.py:333-392` | `calculate_velocity` | 9.2 | 拆 4 段，优先级冻结 | pytest（velocity 单测） |
| `_torch_upgrade.py`（整文件） | 58 符号 | 9.3 | 拆 8 模型族 + 6 基建 + 兼容门面 | 导入冒烟 + pytest |
| `checkpoint_manager.py`（整文件） | 7 符号 | 9.4 | 3 mixin + catalog + 门面 | pytest |
| `trainer.py` / `trainer_io.py` | 见 9.5 | 9.5 | 见 9.5 补全 | pytest |

### 10.2 数据层（core/database、config）

| 位置 | 符号/方法 | 关联 | 改动方法 | 验证 |
|---|---|---|---|---|
| `core/database/connection.py:33-64` | `_ConnectionCtx` | M1.12 | 新增 `open_conn(path, ro=False)`：WAL + `synchronous=NORMAL` + `busy_timeout=5000` + `foreign_keys=ON` | 并发压测无 `SQLITE_BUSY` |
| `core/database/video_db.py:44-48` | 主连接 | M1.12 | 改用 `open_conn` | 同上 |
| `core/database/central_db.py:115-119` | 中央连接 | M1.12 | 改用 `open_conn` | 同上 |
| `core/database/central_backup.py:41,92,129` | 备份/临时连接 | M1.12/M2.8 | `open_conn` + `contextlib.closing` | 句柄数稳定 |
| `core/database/central_crud.py:28` | `_query_backup` | M1.12/M2.8 | `open_conn(ro=True)` + `try/finally`，LIMIT 下推 | 句柄稳定 |
| `core/up_database.py:30` | 每次新连接 | M1.12 | 改 WAL + `busy_timeout` + 长连接 | — |
| `algorithms/training/dataset.py:190,571` | 训练读库 | M1.12/M2.8 | `open_conn` + `finally close` | — |
| `core/database/video_db.py:50-57,77-89,91-106,421-433,508-512` | 镜像写入 | M1.10 | 加配置 `db.mirror_enabled`（默认 false），关闭镜像 | 写文件/提交次数减半 |
| `core/database/central_db.py:339` | `get_video_db` | M1.10 | 同上 | — |
| `ui/monitor/_service.py:280-309` | 6 次提交 | M1.11 | 新增 `VideoDatabase.write_snapshot(record)` 单事务 | 提交 6→1 |
| `core/database/video_db.py:509-511` | 重复 commit | M1.11 | 去掉 `_ConnectionCtx` 内重复 `conn.commit()` | — |
| `core/database/central_crud.py:201,240` | 中央写 | M1.11 | 新增 `sync_snapshot(...)` 批量写 | 单事务 |
| `ui/main_gui_data.py:71-100` | `save_weekly_score`/`save_yearly_score` | M1.11/M2.11 | 不再每抓取调用；改惰性物化 | 单抓取不写分数表 |
| `ui/monitor/_service.py:281-282` | 每抓取写分数 | M1.11 | 移除调用 | 同上 |
| `core/database/central_backup.py:18-69,142-252` | `sync_*_to_central` | M2.5 | 高水位增量 `INSERT..SELECT`，锁外执行 | 耗时 O(增量) |
| `core/database/central_crud.py:118-127,246-256` | `sync_from_video_db` | M2.5 | 轻量只读读取器 + 实例缓存 | 不再重建整库 |
| `core/database/central_backup.py:92-95,129-132` | `with sqlite3.connect` | M2.8 | 改 `closing`（当前不 close） | 长跑句柄稳定 |
| `core/database/central_db.py:64-65` | `_migrate_old_data` | M2.8 | 删死代码/`closing` | — |
| `config/__init__.py:44-46` | `history_days` | M2.9 | 让配置生效；`do_periodic_sync` 内按 cutoff `DELETE` | 库大小进入稳态 |
| `ui/main_gui_tick.py:119-152` | `do_periodic_sync` | M2.9 | 接入保留清理 | — |
| `video_db.py:156-173,227-254,628-630` | 索引 | M2.9 | 补 `created_at`/`video_ts` 等索引 | `EXPLAIN QUERY PLAN` |
| `central_db.py:142-165,207-215,236-262` | 索引 | M2.9 | 补 `owner_id`/`algorithm` 等索引 | 同上 |
| `up_database.py:64-67,169-187` | 索引 | M2.9 | 补 `(uid,timestamp)` | 同上 |
| `ui/monitor/_service.py:268,291` + `ui/main_gui_data.py:133,143` | 时间戳写入 | M2.9 | 统一 UTC ISO/epoch + 一次性迁移 | 跨格式范围查询测试 |
| `core/database/video_db.py:210,226` | 分数表索引 | M2.11 | 加 `UNIQUE(timestamp)`（幂等 upsert 前提） | 重复计算不产生重复行 |
| `core/database/central_crud.py:471-474` | 每次建唯一索引 | 质量 | DDL 移到迁移；循环改 `executemany` | 单测 |
| `core/database/central_crud.py:475-490,529-533` | 逐行 INSERT | 质量 | 改 `executemany` | 单测 |
| `core/database/central_query.py:19-28` | `_run_query` | M1.9 | 不再吞成 `[]`，返回带 `error` 结果 | 注入失败可见 |
| `core/database/central_query.py:77-84` | `get_summary_stats` | 质量 | 三次 COUNT 合并为一次 | 单测 |
| `algorithms/training/dataset.py:196,200,203` | `features` 列名插值 | 质量 | 加固定白名单断言 | 单测 |

### 10.3 UI / 监控层（ui/）

| 位置 | 符号/方法 | 关联 | 改动方法 | 验证 |
|---|---|---|---|---|
| `ui/monitor/_service.py:206-215` | `_save_up_data` 在 `_data_lock` 内 | M1.6 | 锁内只取 `owner_id`，网络调用移出锁 | 批次计时下降 |
| `ui/monitor/_service.py:225-229` | `_viewers_lock` 包住网络 | M1.6 | 出锁调用 `get_video_viewers`，锁内只写字段 | 并发压测 |
| `ui/monitor/_service.py:360-366` | `_update_status_bar` | M1.7 | `invoke(...)` 移入 `if now-last>0.2` 分支 | invoke 次数 N→≤5/s |
| `ui/monitor/_service.py:389-409,431-435` | `_batch_fetch_all` | M2.4 | 有界 `ThreadPoolExecutor` + `as_completed`；`Event.wait` 替代 sleep | 线程数受限、时长不随 N 爆炸 |
| `ui/monitor/_prediction.py:135,143-144` | `_merge_history` | M2.10 | 仅 DB 合并后排序；缓存 epoch/解析结果 | 计时 |
| `ui/monitor/_prediction.py:431,444-455` | 保存线程 + GC | M1.2/M2.10 | 单 writer 队列；提高 GC 间隔/空闲执行 | — |
| `ui/monitor/_prediction.py:343,453,491` | 静默 except | M1.9 | 记录 warning + 收窄异常 | 注入失败可见 |
| `ui/chart.py:76,225-234,113-129` | `ChartWidget` 重绘 | M2.1 | 单自定义 item 批量绘制；静态网格缓存层；`QGraphicsSimpleTextItem` | offscreen PNG + 帧耗时 |
| `ui/chart.py:49-50` | 全局抗锯齿 | M2.1 | 静态内容关闭抗锯齿/分层 | 视觉对比 |
| `ui/dashboard_mode.py:508-513` | `_build_health` | M2.2 | 后台线程算 + 缓存，`invoke` 回主线程 | 主线程无 DB |
| `ui/dashboard_mode.py:682-683,691,54-56` | 预测页重建/ranking 重绘 | M2.10 | 增量 `setText`；指纹不变跳过 `update()` | — |
| `ui/detail_panel.py:928,935` | 主线程查分数 | M2.2 | 移后台 + 缓存 | 主线程无 DB |
| `ui/detail_panel.py:681,683` | 重复算分 | M2.2 | 缓存一次，避免双算 | — |
| `ui/detail_tabs.py:104-127` | 弹幕 `setHtml` | M2.2 | 后台查询；计数变化才重渲 | — |
| `ui/online_viewers_panel.py:340,276` | 主线程逐视频查库 | M2.2 | 后台取值经 `invoke` | — |
| `ui/video_list_panel.py:352-379` | `update_card` | M2.3 | 维护 `bvid→QListWidgetItem` 索引（去 O(N²)） | 刷新近线性 |
| `ui/video_list_panel.py:370` + `utils/cover_manager.py:111-118` | 封面读取+MD5 | M2.3 | 有效性缓存（路径+mtime），MD5 移加载线程 | 主线程不读封面 |
| `ui/video_list_panel.py:60-68` | `CoverLoader` | M2.10 | worker 用 `QImage`，主线程转 `QPixmap`；有界池 | 稳定性 |
| `ui/video_list_panel.py:286-296` | `_on_search` | M2.10 | 去抖 150ms 或 `QSortFilterProxyModel` | — |
| `ui/video_list_panel.py:117,140,155` | delegate paint | M2.10 | 缓存 path/metrics/阈值结果 | — |
| `ui/main_gui_tick.py:48,113-114` | `tracemalloc` 主线程 | M2.10 | 移 `fire_and_forget` | 主线程不卡 |
| `ui/main_gui_tick.py:64-116` | `global_tick` | 9.6 | 拆 5 段，保留去重缓存与线程名 | radon CC≤4 |
| `ui/main_gui_tick.py:207-303` | `scan_alerts_background` | 9.6 | 拆 5 段 | radon CC≤5 |
| `ui/invoker.py:28-31` | `invoke` | M2.10 | 按 key 合并 + 背压；异常走 logger | — |
| `ui/log_panel.py:248,157,173-174` | `_sync_empty_state`/pending | M2.10 | 计数替代 `toPlainText()`；`_pending_logs` 加锁 | — |
| `ui/settings_notification.py:189` | lambda 闭包 `e` | M1.8 | 先 `err=str(e)` 再用 | pytest 错误路径 |
| `ui/settings_window.py:329,334` | 静默 except | M1.9 | 记录 warning | — |
| `ui/settings_window.py:253-335` | `_persist_settings` | 9.11 | 类内提取（见 9.11），加密往返顺序冻结 | 配置字节 diff |
| `ui/detail_panel.py:805-944` | `_fill_detail_text` | 9.9 | 拆纯函数（见 9.9） | HTML 快照 |
| `ui/detail_panel.py:578-656` | `_rebuild_stat_bar` | 9.9 | 字段表合并 + `stat_value_text` | radon |
| `ui/snapshot_tab.py:68-299` | `paintEvent` | 9.7 | 分 5 遍（单 QPainter） | PNG diff |
| `ui/snapshot_tab.py:632-693` | `_apply_custom_range` | 9.7 | 提 2 纯函数 | pytest |
| `ui/prediction_accuracy.py:124-316` | `_load_data` | 9.10 | 拆纯函数（见 9.10） | pytest |
| `ui/danmaku_analysis.py:448-539` | `_render_hour_sentiment` | 9.8 | 拆 5 段 | radon |
| `ui/danmaku_analysis.py:304-331` | `_fetch_danmaku` | 9.8 | 提 `_load_danmaku_from_local` | — |
| `ui/danmaku_analysis.py:872-987` | 两个绘图组件 | 9.8 | Move Class → `ui/danmaku_charts.py` | 目视 |
| `ui/main_gui_events.py` 全文件 | 47 函数 | 9.6 | 拆 9 个模块（S1–S11） | `python -c "import ui.main_gui"` |
| `ui/main_gui.py:339-559` | `_build_titlebar` | 9.6 | 拆 4 段 + 菜单表提常量 | — |
| `ui/main_gui.py:136-188` | `_init_tray` | 9.6 | 拆 3 段 | — |
| `ui/report_scheduler.py:497` | `build_push_msg` import | 9.6 | 迁到 `ui.push_formatters` | 导入冒烟 |
| `ui/monitor/_service.py:357` / `ui/dialogs.py:122` | `_register_video_timer` | 9.6 | 包装方法不变（无需改） | — |

### 10.4 工具 / 门禁 / 测试（utils、CI、仓库）

| 位置 | 符号/方法 | 关联 | 改动方法 | 验证 |
|---|---|---|---|---|
| `.flake8` / `.github/workflows/code-quality.yml` | flake8/复杂度门禁 | M3.1 | 冻结历史项；去掉复杂度检查 `exit 0` 与 mypy `|| true` | CI 对新问题失败 |
| 全仓 `F401/F841` | 未用导入/变量 | M3.2 | `autoflake`/`ruff --select F401,F841 --fix` | flake8 项数下降 |
| `ui/monitor/_prediction.py:3,8,9,10,22,23` | import 混乱 | M3.2 | 提到模块级，删未用 | flake8 |
| `models/advanced/bass_diffusion.py` vs `models/growth/bass_diffusion.py` | 同 `algorithm_id` | M3.5 | 合并或改唯一 id | M0.2 唯一性测试 |
| `growth/gompertz.py` vs `gompertz_growth.py`、`time_series/theta_forecast.py` vs `theta_method.py` | 重复实现 | M3.5 | 合并/改 id + 注册断言 | 同上 |
| `ui/dashboard_mode.py:21-29,302` | 硬编码调色板 | M3.6 | 改引用 `ui/theme.py:C` | 截图 |
| `ui/chart.py:22-24,252,268,416,425` | 硬编码 hex | M3.6 | 同上 | 截图 |
| `ui/health_probe.py:103,109,198` | 硬编码 hex | M3.6 | 同上 | 截图 |
| `ui/data_comparison.py:22-44` | 硬编码 hex | M3.6 | 同上 | 截图 |
| `ui/crossover_analysis.py:29-33,332` | 硬编码 hex | M3.6 | 同上 | 截图 |
| `ui/bottom_bar.py:51` / `ui/entry_tab.py:277,523,590` | 硬编码 hex | M3.6 | 同上 | 截图 |
| `utils/crypto.py:105-139` | XOR 回退 | M3.7 | 失败关闭或显式标记明文 | 加密单测 |
| `utils/crypto.py:36-86,65,86` | 导入时 PowerShell + 硬编码 salt | M3.7 | 惰性/可缓存 key；salt 入配置 | 导入耗时 |
| `utils/crypto.py:171-176` | `is_encrypted` 启发式 | M3.7 | 加显式版本头 | 单测 |
| `ui/settings_*.py` | 重复样板 | M3 | 迁移到 `settings_common` helpers | 目视 |
| `.omo/`(19) + `data/*.json` | 运行产物入库 | M3.10 | `git rm --cached` + 完善 `.gitignore` | `git status` |
| `tests/` | 缺测试 | M0.2/M3.9 | 补 5 个最小回归 + 高风险测试 | `pytest` |
| `mypy.ini` | `|| true` | M3.8 | 去掉并逐包收紧 | mypy |

### 10.5 新增文件一览

| 新文件 | 来源 | 关联 |
|---|---|---|
| `utils/score_materializer.py` | 新增（`ensure_scores`/`current_scores`） | M2.11 |
| `ui/score_center.py` | 新增（周/年分数中心窗口） | M2.11 |
| `algorithms/registry_cache.py` / `registry_discovery.py` / `video_data.py` / `prediction_execution.py` / `ensemble.py` / `prediction_pipeline.py` / `registry_feedback.py` / `registry_training.py` | 从 `registry.py` 拆 | 9.1 |
| `algorithms/prediction_result.py` / `base_results.py` / `history_features.py` / `model_metrics.py` / `surge_detection.py` / `npu_adapter.py` | 从 `base.py` 拆 | 9.2 |
| `_torch_models_{recurrent,attention,segmented,decomposition,mixing,frequency,convolutional,specialized}.py` / `_torch_layers.py` / `_torch_features.py` / `_torch_checkpoint.py` / `_torch_cache.py` / `_torch_backends.py` / `_torch_result.py` / `_torch_inference.py` | 从 `_torch_upgrade.py` 拆 | 9.3 |
| `algorithms/training/checkpoint_{storage,queries,mutations,catalog}.py` | 从 `checkpoint_manager.py` 拆 | 9.4 |
| `algorithms/training/trainer_{entrypoints,workflow,data,setup,epoch,progress}.py` | 从 `trainer.py` 拆 | 9.5 |
| `ui/{push_formatters,push_cycle,update_flow,app_lifecycle,model_activation,refresh_cycle,video_ops,training_callbacks,panel_callbacks,maintenance_tasks,tray_control,titlebar,window_layout}.py` | 从 main_gui* 拆 | 9.6 |
| `ui/snapshot_bar_chart.py` / `ui/snapshot_data.py` | 从 `snapshot_tab.py` 拆 | 9.7 |
| `ui/danmaku_charts.py` / `ui/danmaku_llm_mixin.py` | 从 `danmaku_analysis.py` 拆 | 9.8 |
| `ui/finetune_dialog.py` / `ui/detail_stat_bar.py` / `ui/detail_text.py` | 从 `detail_panel.py` 拆 | 9.9 |
| `ui/prediction_accuracy_data.py` | 从 `prediction_accuracy.py` 拆 | 9.10 |
| `ui/training_monitor.py` / `ui/training_dialogs.py` / `ui/training_stage_handlers.py` / `ui/training_widgets.py` | 从训练 UI 拆 | 9.12 |

### 10.6 重构类改动（第 9 章交叉引用）

大型文件与高复杂度函数的分步重构方法见 **第 9 章**（`registry.py`/`base.py`/`_torch_upgrade.py`/`checkpoint_manager.py`/`trainer.py`/main_gui 四件套/5 个复杂面板/训练 UI 四件套）。其缺口（`trainer.py` 步骤 2+、`trainer_io.py`、训练 UI 完整版）现已补入第 **9.5.1 / 9.5.2** 与 **9.12.1–9.12.4** 节，10.1/10.3 对应行可直接开工。
