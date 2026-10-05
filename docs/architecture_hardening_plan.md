# 架构加强终排与施工计划

> 来源：2026-10 四路代码勘察（UI 结构 / 后台分层解耦 / 算法子系统 / 工程化面）＋架构顾问交叉调律。
> 其中 P0-1、P0-2 两条由会话主管直接复核（含全仓旁路检索），证据链已闭合。
> 施工约定：先写特征测试、再改实现；小步提交、每步可回退；不新增 `# type: ignore` / `# noqa`；算法注册数保持 137；
> 不触碰完整性保护文件（`core/bilibili_api.py`、`algorithms/registry.py`、`algorithms/base.py`、`core/notification.py`；
> 如确需修改，须同步刷新嵌入哈希并单独评审）。每包收尾统一通过既有门禁：black / lint_gate / type_gate / bandit / pytest。

## 总判断

- 仓库底子良好：137 算法、质量门禁零容忍、主题令牌集中（202 处色值中 200 处在 `ui/theme.py`）、弹窗唯一入口、巨型模块均已门面化拆分。
- 剩余加强点按优先级三层：**① 正确性缺陷 → ② 边界（状态 / 任务 / 数据）→ ③ 界面与工程化**。
- GUI 整体重构：**该做，但不该推倒重写**。锁住重构的不是三栏布局，而是面板握着整个主窗口（`self.gui.` 117 处）。
- 后台解耦路线：composition root → services → repositories → TaskSupervisor → AppState/AppActions → UI，可逐层迁移。

## 一、先行修复：正确性缺陷（P0）

### P0-1 集成偏差校准空转

- 现象：B3 集成偏差校准从未积累样本。
- 证据：`algorithms/registry.py:57-76` 每轮把状态写成 `(本轮观测, 本轮观测)`；全仓检索 `_prev_ensemble_pred` 无任何一处写回真实预测 → `pred_growth` 恒为 0 → `bias_corrector.record()` 永不触发。
- 修法：在 `predict_all` 算出 `_weighted` 后回填 `(weighted_prediction, current_value)` 至 per-bvid 状态（落点 `algorithms/registry_parts/_ensemble.py`，不触碰签名保护的 `registry.py`）；回填须只对真实观测周期生效，warmup 不得污染。
- 验收：连续三帧模拟产生非零 `pred_growth` 样本；新增单测。

### P0-2 集成明细从未落库

- 现象：`prediction_ensemble` / `algorithm_coherence` 两表建了、线接了、数据永远到不了。
- 证据：`ui/monitor/_prediction.py:61-103` 恒返回 `ensemble_data=None`、`coherence_rows=[]`；全仓检索确认 `_sync_predictions_to_central`（:38）唯一调用点为 :409，输入恒为空。数据已在 `_build_prediction_result`（:352-392）构造，只是未接线。
- 修法：`_save_predictions_to_db` 从 `results["_weighted"]` 与各算法 `coherence` 构造真实载荷，对齐 `central_crud.sync_prediction_ensemble / sync_algorithm_coherence` 的字段形状；`_weighted` 缺失时保持 None 的向后兼容。
- 验收：单元测试断言非空载荷返回与同步调用；`_weighted` 缺失时仍为 None。

### P0-3 深度学习模型缓存竞态

- 现象：多视频并发共用同一算法实例，`_cached_model/_cached_bvid` 原地切换。
- 证据：`cnn_image.py:131,170-182`、`diffusion_ts.py:288-345`、`mar_bilstm.py:137-198`、`knf.py:161`、`lag_llama.py:61-114`、`torch_upgrade/prediction.py:205-206`、`torch_upgrade/runtime.py:179-187`；并行入口 `ui/monitor/_service.py:105-165`、`registry_parts/_ensemble.py:280-289`。
- 修法（包 3）：声明执行策略 `STATELESS_SHARED / LOCKED_SHARED / PER_VIDEO`；未知按保守处理；warmup 与实时预测不得并发使用有状态实例。
- 验收：A/B 双视频并行 20 次与串行结果一致；记录锁等待时间。

### P0-4 共享状态与退出次序

- 现象：风险不在「线程多」，在共享状态与关停次序。
- 证据：`video_dbs` 后台读 / 主线程删无锁（`_service.py:523`、`_prediction.py:63,114` vs `main_gui_events_monitor.py:231,290`）；`monitored_videos` 改 / 遍历无锁（`_service.py:453-484`）；关库先于守护线程收敛（`_service.py:597-618`、`main_gui_events_runtime.py:55-66`）；保存与预热线程未登记（`_prediction.py:307-321,452-455`）。
- 修法（包 4）：RUNNING/STOPPING/STOPPED 状态机；DB handle 统一锁；登记全部后台任务；关库前 drain/cancel。
- 验收：反复「抓取 + 预测 + 退出」无 closed database / 残留进程；增删视频并发压测。

### P0-5 学习状态不可靠

- 现象：权重 JSON 全量非原子重写；OnlineLearner 写而不读。
- 证据：`weight_manager.py:106-140,197-217`（`open(fpath,"w")` 无临时文件 + rename）；生产每轮批量写 `_prediction.py:515-517`；`online_learner.py:354-407` 的 `load()` 全仓零调用。
- 修法（包 2）：单写者 + debounce + 临时文件 / fsync / `os.replace`；启动时加载 OnlineLearner；状态带 schema version。
- 验收：20–50 线程并发更新后 JSON 恒可解析；保存 → 重启加载一致；故障注入中断写文件旧文件仍有效。

## 二、后台解耦（B）

- **B1 TaskSupervisor**：统一 I/O / 预测 / 持久化 executor；per-bvid single-flight + latest-wins pending；统一取消与异常收集。风险 M / 工作量 L / P1。
- **B2 core 去副作用**：`core/__init__.py:6-12` 导入即开库、构造 API；实例化收进 `app/bootstrap.py`；断掉 core→ui 环（`core/threshold_escalation.py:123,255` 反向 import `ui.helpers`）。风险 M / 工作量 M / P1。
- **B3 AppState/AppActions**：主窗卸下「状态仓库 + 控制器 + 服务定位器」三职；面板只收只读快照与 typed signals。风险 M / 工作量 L / P1。
- **B4 Repository 层**：UI 禁止直连 SQLite（`ui/database_query.py:419,491,560,613,879`、`ui/online_viewers_panel.py:39-71`、`ui/monitor/_service.py:677-682`）；查询工具改只读连接工厂。风险 S/M / 工作量 M / P1。
- **B5 数据所有权**：每视频库 = 权威明细；中央库 = 可重建投影；备份改一致性快照；取消在线多路径双写（`video_db.py:593-635,824-903`、`main_gui_tick.py:321-356`）。风险 L / 工作量 L / P1（分阶段）。
- **B6 迁移统一**：中央 / 视频 / 备份三套 schema → 顺序迁移 + version 表；备份恢复复用同一迁移器。风险 M / 工作量 M / P1。

## 三、GUI 演进（C）

- **C1 渐进重构**：先切三个核心面板（VideoList / Detail / Prediction）到 AppState/AppActions；再引入 Feature registry 收拢导航与 Dialogs（`dialogs.py` 30 处 `self.gui.`）；最后再动布局。风险 M / 工作量 L / P1-P2。
- **C2 样式与组件收口**：911 处局部 setStyleSheet 组件化；补字号 / 间距令牌；抽 BarTrend / Pie / Radar 公共图表（现 9 套自绘、3 技术栈并存）；统一 `clear_layout`（21 处散乱 deleteLater）。风险 S / 工作量 M / P2。
- **C3 性能预算**：先测首帧 / 列表可用 / 首次预测 / P50、P95 / 队列长度 / RSS；再定扩展降频与加载分层（约 130/137 算法每轮全跑；首次扫描实例化 137 对象）。风险 S / 工作量 S/M / P1-P2。

## 四、工程化与分发（D）

- **D1 打包单轨**：`BiliMonitor.spec`（onedir、「97 模块」陈旧清单）vs `release.yml:146-160`（--onefile）→ 只留一条权威路径 + 打包冒烟（算法数 / 开库 / 离线预测 / 建窗）。风险 S/M / 工作量 S/M / P1。
- **D2 更新链信任根**：签名 manifest（Ed25519 + SHA-256）+ `.bak` 自动回滚；私钥移出工作树（`scripts/.signing_key`）。风险 M / 工作量 M / P1。
- **D3 CI 对齐**：本地 / CI flake8 规则一致化；Windows 轻量矩阵；`sign --verify`；覆盖率先观测、不设硬门槛。风险 S/M / 工作量 S/M / P2。

## 五、第一批动工包（2–4 周；先测试、后实现；逐包可回退）

**状态（2026-10-05 更新）**：包 1 已交付（`80ab97f` / `24cecd8` / `d84233a`）；包 2 已交付（`743fafa`，524 passed）；包 3 已提交（`3dc6f1e`）；包 4–5 经合流门禁与独立风险复核后提交为 `70a2690`（退出路径与工厂迁移存在共享文件）。**第二批已完成**：B6-a（`842f858`）、B3 骨架与三面板迁移（`ca798d0` / `b1ca3a4` / `d4ac2b7` / `1612732`）、B1 五包（`84bf354` / `f8bdd29` / `955e891` / `349244a` / `2716264`），另含两轮质量门禁收口（`56f6016` / `4a5feb5`）。

**第二批追加（已交付）**：第三批（B5-a1 / B4 / B6-b / B5-a2）、第四批（B5-b 全序 4.1–4.4-F、算法执行策略 4.5、B2 前置护栏 4.6）、第五批 5.1（D1 单轨打包）均已交付并通过 CI。第四批全序 commit：

- **4.1** `764b49c`：契约冻结；`xfail(strict=True)` 反证「仅凭中央不可重建」。
- **4.2** `b922114`：权威表 + durable outbox；视频 schema v6、中央 schema v4。
- **4.3** `372a372`：projector + 影子校验（七 stream `apply_projection_batch`、`CentralProjector`、`audit_projection_entities`）。
- **4.4-A** `9b639c9`：切流前提（预测周期→`save_prediction_cycle`、里程碑权威写、payload 等价、single-flight）。
- **4.4-B** `18151cf`：原子切流；默认 `mode="projector"`；`config/runtime_mode.py`；七 stream legacy 守卫。
- **4.4-C** `ada98aa`：`core/database/snapshot.py` 一致性快照基建（`Connection.backup()` → `quick_check` → `os.replace`）。
- **4.4-D** `acca068`：删在线镜像（`video_db`/`video_db_scores`），备份委托快照，读路由切活跃库；净减 236 行。
- **4.4-E** `051546a`：周期与退出快照接管（`main_gui_tick` snapshot QTimer + `on_exit` finalizer）。
- **4.4-F** `2f27964`：删旧收口——移除覆盖式旧同步 API（`sync_from_video_db`/`sync_all_video_dbs`），**保守保留 legacy 生产回退通道**。
- **4.5** `610e336`：算法执行策略声明与审计（`execution_policy.py` + 137 项 manifest + 审计测试 + 文档）；**只声明不改并发**。
- **4.6** `cbf726e`：B2 前置——`tests/test_core_import_purity.py` 冻住 `import core` 无副作用（`core/__init__` 本已纯再导出）。
- **5.1** `3e21190`：D1 打包单轨 onefile（`BiliMonitor.spec` + `release.yml` + 打包冒烟）。

全量 **645 collected / 644 passed**（deselect 既存 Windows `test_shutdown_qt` 超时），算法注册数 **137**，完整性保护文件未修改。以下工程要点保留作为验收依据。

#### 包 3–5 本轮交付与验证记录

- **包 3**：CNN / Diffusion / MAR-BiLSTM / KNF 缓存换载持实例锁，推理使用局部模型引用；Lag-Llama / Moirai 懒加载状态受锁保护；通用 torch 路径整体实例串行。GPU LRU 驱逐采用非阻塞模型使用锁，跳过在途推理；CUDA OOM 最多重试一次，再进入既有降级链。新增 `tests/test_algo_concurrency.py`。
- **包 4**：引入 `ui/monitor/_lifecycle.py`，统一 RUNNING / STOPPING / STOPPED、任务登记与 DB 租约；收拢监控、保存、预热、tick 维护、添加视频及面板后台资源使用。预测器、adhoc、PrecisionWatch 超时后保留所有权，重复轮询直到退出；STOPPING 与任务创建原子互斥；依赖关闭延迟至任务收敛之后。新增 `tests/test_shutdown_safety.py`、`tests/test_panel_db_lifecycle.py`、`tests/test_shutdown_qt.py`（真实 Qt 事件循环、隔离子进程验证延迟清理）。
- **包 5**：移除 `core` 导入时 DB / API 实例别名与通知实例再导出，调用方显式获取工厂；共享 HTTP Session / Adapter 延迟创建。新增 `tests/test_core_import_purity.py`，子进程护栏验证无 DB 文件、线程、网络及 Session / Adapter 构造增量。
- **B6-a 验证**：在 conda `bili` 环境中，Black（392 文件）、lint_gate、type_gate（0 errors）、Bandit（Medium / High = 0）、pytest（549 passed，4 个既有第三方收敛警告）、`git diff --check` 全部通过；AST 护栏确认 `core/` 不导入 `ui`，算法数独立断言为 137。
- **独立复核**：已闭合 GPU 驱逐竞态、OOM 无界递归、重复退出轮询丢失线程所有权、STOPPING 后启动及面板未登记资源使用等具体阻塞项。最终限定复核 PASS。
- **保留限制**：第三方网络调用若永久不返回，将延迟退出而非提前关闭依赖；历史弹幕抓取为保证写入句柄存活会持有较长 DB 租约；无空闲 GPU 模型可驱逐时保守降级。同一算法实例的多训练任务隔离、声明式执行策略仍属后续任务，不视为本轮交付。
- **下一施工入口**：按第二批推进 B6-a 断环及 B3 / B1 状态与任务骨架；本轮仅完成首批包 3–5，不代表第二至第六批已经交付。

### 包 2：学习状态可靠性包（对应 P0-5）

- **目标**：持久化由「全量非原子、写而不读」改为「单写者、原子替换、可节流、启动可恢复」。
- **现状与证据**：快照在锁内生成、文件写在锁外（`algorithms/weight_manager.py:106-140`），`open(fpath,"w")` 直接覆盖 `default_weights.json`；生产每视频每轮触发一次全量重写（`_prediction.py` 的 `_online_learning_feedback` → `update_accuracy_batch`，`weight_manager.py:195-217`，137 算法 × 100 条）；`online_learner.py` 有 `save()`（:354-379）、`load()`（:381-407）全仓零调用；per-bvid 权重分支（`weight_manager.py:73-87、:132-133`）无调用方。
- **工程要点**：
  1. **原子写**：同目录临时文件 → `flush` + `os.fsync` → `os.replace()`；失败保留旧文件并记日志。
  2. **单写者 + 版本护栏**：写盘串行化；快照带单调版本号，旧版本不得覆盖新版本。
  3. **节流**：更新只置 `dirty`，周期落盘（5–30s 或每 N 次更新）；`on_exit` 强制 flush，不丢最后一轮。
  4. **启动加载 OnlineLearner**：让 `load()` 容忍「文件中存在未注册 tracker」（按文件恢复，而非只认已注册）；状态文件加 `schema_version` + 算法集合指纹，不匹配时安全降级并记日志。
  5. **清理死分支**：移除（或显式标注保留）per-bvid 权重分支。
- **验收**：20–50 线程并发 `update_accuracy` 后 JSON 恒可解析且不回退到旧快照；写入中断后旧文件仍有效；save → 重启 load 后 tracker 数 / 样本数 / 权重一致；新增 `tests/test_learning_state_reliability.py`；全量门禁通过。
- **风险/工作量**：风险 S / 工作量 S–M；文件格式向后兼容（新增字段缺省视为 v1）；独立提交、可回退。

### 包 3：算法缓存并发保护包（对应 P0-3）

- **目标**：消除多视频并发下共享算法实例的缓存竞态与串模型风险。
- **现状与证据**：算法每类仅实例化一次、全局共享（`algorithms/registry_parts/_models.py:64-77`），多视频 predictor 并发进入共享线程池（`ui/monitor/_service.py:105-165`、`_ensemble.py:280-289`）；有状态缓存家族：`cnn_image.py:131/170-182`、`diffusion_ts.py:288-345`、`mar_bilstm.py:137-198`、`knf.py:161+`、`lag_llama.py:61-114`、`torch_upgrade/prediction.py:205-206`、`runtime.py:179-187`；warmup（`_schedule_weight_warmup`）与实时预测并行共用同批实例（`_warmup.py:110-117`）。
- **工程要点**：
  1. **盘点**：扫描所有在 `predict` / 懒加载路径写实例字段的算法，形成「有状态清单」。
  2. **保护临界区**：缓存「检查 → 换载 → 使用」收进实例级锁；推理在锁外用局部引用执行；确认不可重入的模型再升级为整体串行。
  3. **warmup 互斥**：warmup 与实时预测不得并发使用有状态实例（同一把实例锁天然互斥；必要时跳过或排队）。
  4. **（后置可选）执行策略声明**：`STATELESS_SHARED / LOCKED_SHARED / PER_VIDEO`；审计后为无状态算法免除锁开销，不一步到位。
- **验收**：A/B 双视频并发 × 20 与串行结果一致、`_cached_bvid` 不串；锁等待时间可接受；注册表保持 137；新增 `tests/test_algo_concurrency.py`（无 torch 环境优雅 skip）；全量门禁通过。
- **风险/工作量**：风险 M / 工作量 M–L；不改算法数值行为；独立提交、可回退。

### 包 4：退出与共享容器安全包（对应 P0-4）

- **目标**：运行时不取到已关闭 / 已删除的资源；退出时先收敛全部线程，再关库。
- **现状与证据**：`video_dbs` 后台读（`_service.py:523`、`_prediction.py:63,114`）vs 主线程增删（`main_gui_events_monitor.py:231,290`），无统一锁；`monitored_videos` 改 / 遍历无锁（`_service.py:453-461`）；退出路径 `main_gui_events_runtime.py:43-95`、`_service.py:597-618`（有界 join，超时转守护）；未登记线程：预测保存（`_save_prediction_outputs`）与 warmup（`_schedule_weight_warmup`）。
- **工程要点**：
  1. **应用状态机**：`RUNNING / STOPPING / STOPPED`；STOPPING 后拒绝新任务（fetch / predict / save / warmup）。
  2. **统一访问器**：`video_dbs` 收敛为持锁访问器（取用 / 删除），固定与 `_data_lock` 的锁层级顺序并注释。
  3. **线程登记**：保存与 warmup 线程纳入统一登记（可 join、可取消），向 TaskSupervisor 长线靠拢。
  4. **drain 顺序**：停 tick → 拒新 → 有界收敛 → flush 学习状态（包 2 接口）→ 关视频库 → 关中央库 → 关 api/session；关库后访问视为缺陷（防御断言 + 日志）。
- **验收**：在途任务中反复退出：无 closed-database、无残留进程；增删视频并发压测无崩溃；新增 `tests/test_shutdown_safety.py`（fake 组件，不依赖 offscreen 窗口）；全量门禁通过。
- **风险/工作量**：风险 M / 工作量 M；稳定性收益高；独立提交、可回退。

### 包 5：core bootstrap 最小切口（对应 B2）

- **目标**：`import core` 不再开库、建 API；以「无副作用导入」护栏开路，分批迁移调用点，为 composition root 铺路。
- **现状与证据**：`core/__init__.py:11-12` 导入即 `get_db()`、`get_bilibili_api()`；`core/database/connection.py:14-25` 导入即建 session；`core/notification.py:44/439` 导入即建线程池与单例（**保护文件——本包不触碰，单独立项**）；调用方依赖便利别名（`ui/monitor/_service.py:20`、`_prediction.py:15`；`ui/main_gui.py:49` 仅因通知管理器而导入整个 core）。
- **工程要点**：
  1. **护栏先行**：子进程断言 `python -c "import core"` 不新增 DB 文件、不起新线程、不发网络请求（`tests/test_core_import_purity.py`）。
  2. **去实例化**：`core/__init__` 仅再导出类型 / 工厂；移除 `db` / `bilibili_api` 模块级别名。
  3. **迁移调用点**：统计 `from core import db|bilibili_api` 的实际使用面，分批改为显式获取；`ui/main_gui.py` 等改为直连 `core.notification`。
  4. **（方向性）** 新代码经显式引导创建 / 注入依赖；完整 DI 留给阶段 2。
- **验收**：`import core` 纯净；主程序行为不变；测试可注入临时 DB / API 替身；全量门禁通过。
- **风险/工作量**：风险 M / 工作量 M；不与数据库所有权迁移并行；不触碰完整性保护文件。

每包收尾统一执行：`black --check --line-length=120 .`、`python scripts/lint_gate.py`、`python scripts/type_gate.py`、`bandit -r . -c pyproject.toml -ll`、`python -m pytest tests/ -q`。

## 六、不建议做（YAGNI）

- 不重写 QML；不微服务化；不换 PostgreSQL；不引入 Redux / 全局字符串事件总线。
- 不把 137 算法进程隔离；不继续以「拆文件」冒充解耦；不同时改 GUI + 线程 + 数据库格式。
- 不加高覆盖率硬门槛；不删疑似重复算法；不动数据库结构——除非先有特征测试作保。
- 不急于持久化全部运行缓存（bias / conformal / schedule）；先明确产品语义。

## 七、后续批次规划（首批未覆盖）

> 首批五包（第五节）覆盖 P0-1～P0-5 与 B2 最小切口；本节规划其余任务——B1、B3、B4、B5、B6、C1、C2、C3、D1、D2、D3 及尾巴项——的批次、顺序与验收。各任务的「问题 / 证据 / 风险」详见第二、三、四节，不再重复。

### 批次总览

| 批次 | 主题 | 覆盖 | 依赖 / 并行性 |
|---|---|---|---|
| 第二批 | 状态与任务骨架 | B3、B1、B6-a、C3（观测） | 依赖首批包 4 的状态机雏形；B6-b 可另行并行 |
| 第三批 | 数据访问与迁移底座 | B5-a1 → B4 → B6-b → B5-a2 | B5-a1 已交付（commit 待填）；B4 建议在第二批 AppState 迁移后启动 |
| 第四批 | 数据所有权与组合根 | B5-b、算法执行策略、B2 完整化 | 依赖第三批的 Repository 与迁移器 |
| 第五批 | 工程化与分发 | D1、D2、D3、尾巴项 | 完全独立，可与任一批并行 |
| 第六批 | 界面演进 | C1、C2、（视觉重排可选） | 必须等第二～四批边界稳定后 |

### 第二批：状态与任务骨架（建议最先启动）

1. **B3 AppState/AppActions（逐个面板迁移）**〔核心；骨架与三个核心面板已完成机械迁移〕
   - `ui/app_state.py` 已提供 `AppState(QObject)`：覆盖主窗 `monitored_videos`、`history_data`、`prediction_results`、`video_dbs`、`selected_bvid`、`_video_index` 的只读快照，以及 typed signals（`video_updated` / `selection_changed` / `prediction_updated`）。普通 dict/list/tuple/set 数据递归冻结，并在存在时持有既有 `_data_lock` 复制；`video_dbs` 仅是按 `_data_lock` → `_video_db_lock` 顺序取得的兼容性成员快照，值仍为不应由未来面板使用的可变 DB 资源句柄。`ui/app_actions.py` 已提供注入式增删 / 刷新 / 选择 / 推送委派入口。
    - VideoListPanel 已完成首个机械迁移：构造时接收 `AppState` / `AppActions`，不再持有主窗引用；`selection_changed` 仅同步列表高亮且阻断列表信号回流，用户选择和“全部推送”经 actions 委派。卡片的增量 `make_card` / `update_card` / `remove_card` 调用仍由主窗既有流程维护，避免每次状态更新重建列表。
    - DetailPanel 已完成同一机械迁移：选择、视频/历史/预测快照、DB 成员兼容性检查和陈旧回调守卫改从 `AppState` 读取；复制 BV 号与微调状态经 `AppActions` 委派，微调工作线程保持通过 `invoke()` 回到主线程。分数/弹幕后台读取仍明确接收独立 lifecycle owner，仅用于 `use_video_db` 租约和 `start_registered_task`，绝不把 DB 资源放入 AppState。
    - PredictionPanel 已完成最后一个核心面板迁移：算法信息刷新从 `AppState` 取选中 BVID、历史和预测冻结快照，并经 `AppActions.get_video()` 保留既有视频查询路径。保留既有 `show_video_detail` / `prediction_done` 的命令式刷新，刻意不订阅 `selection_changed`，避免一次选择双重渲染；英雄卡、信息区和缓存指纹均未重建或改变。三个核心面板不再直持主窗；其余 `self.gui.` 出现在非核心面板，仍属 B3 后续范围。
   - VideoListPanel 验证：新增 5 项真实 offscreen QWidget 边界测试，覆盖单次选择、push 布尔参数隔离、状态高亮无重入、搜索与增量卡片操作及冻结快照适配。
   - **B3 已交付**（`ca798d0` 骨架 / `b1ca3a4` VideoList / `d4ac2b7` Detail / `1612732` Prediction）：新增 `tests/test_app_state_skeleton.py`、`tests/test_video_list_state_boundary.py`、`tests/test_detail_state_boundary.py`、`tests/test_prediction_state_boundary.py`；三核心面板不再直持主窗，全量门禁通过，算法注册数保持 137。DetailPanel 保留独立 lifecycle owner 供 `use_video_db` / `start_registered_task`，DB 资源不入 AppState；PredictionPanel 刻意不订阅 `selection_changed` 以避免双重渲染。
   - 迁移顺序：VideoListPanel → DetailPanel → PredictionPanel；逐面板可回退。**尾部未清**：非核心面板仍直持主窗（`self.gui.` 约 89 处，最密为 `dialogs.py` 30 处），归后续范围。
   - 验收：三个核心面板不直持主窗（已达成）；面板相关回归 + 全量门禁通过。
2. **B1 TaskSupervisor（五包已交付）**：`ui/monitor/_supervisor.py` 统一预测与 fetch 任务秩序，`MonitorRuntime` 管物理生命周期。per-bvid single-flight 分两式：预测为 latest-wins（在途不可取消，pending 覆盖写入 `video.copy()` 快照，完成后至多再跑一次），fetch 为 active 合并（重复请求共享当前 completion，不补跑）。架构顾问裁决的施工序与落点如下——
   - **B1.1（`84bf354`）**：修正 `MonitorRuntime.start_thread` 准入竞态（已 RUNNING 原子准入的任务必执行，STOPPING 只拒后续并 drain）；新建 dormant `TaskSupervisor` 内核（lane/pending/token/retire/shutdown）；`tests/test_task_supervisor.py`（7 项 Event/Barrier 并发测试）。
   - **B1.2（`f8bdd29`）**：三处预测入口（`_notify_predictor` / `auto_predict_all` / `run_post_training_predict`）原子收拢经 `submit_prediction`；移除训练后预测的 ad-hoc `ThreadPoolExecutor`；`tests/test_prediction_entry_single_flight.py`。
   - **B1.3（`955e891`）**：删除 `VideoPredictor` 第三套线程所有权（`VideoPredictor` / `_predictors` / `_ensure_predictor` / `_stop_all_predictors` / `_stop_predictor`）；`_predict_single` token 化（结果/反馈/持久化调度前校验 token）；新增 token 守卫的 `_schedule_prediction_ui`；删除/重加经 `retire_bvid` 永久失效隔离；`tests/test_prediction_freshness.py`。
   - **B1.4（`349244a`）**：删除架空的 `_adhoc_threads` / `_track_thread` / `_untrack_thread` / `_start_tracked_thread`；`_stop_all_workers` 收敛，shutdown 时序不变。
   - **B1.5（`2716264`）**：`TaskSupervisor.coalesce_fetch` per-bvid fetch 合并；手动单个/全部/周期批量统一经它，保留跨 bvid 有界并发与 `get_safe_workers()` 上限；异常释放 lane；`tests/test_fetch_single_flight.py`。
   - 验收：手动 + 定时 + warmup 并发触发的「预测风暴」不重复排队（已达成）；退出收敛口径与包 4 一致（已达成）。
   - **细粒度边界（如实标注）**：prediction save 未引入严格 FIFO（`use_video_db` 租约已足，如需顺序须独立 persistence 包）；手动单个 fetch 若 worker 真抛异常，其 Future 无人取结果（生产中 `_fetch_one_video` 内部已吞异常，低危过渡）。
3. **B6-a 断环（小件，已完成）**：`core/threshold_escalation.py:123,255` 的反向 `ui.helpers` 依赖已移入 `config.thresholds`；`ui.helpers` 显式再导出原有阈值对象与重载入口，core 对 ui 零依赖。
   - 验收：`core/` 内 import `ui` 零命中（grep）；相关测试通过。
4. **C3 性能预算（先观测；尚未动工）**：采集启动→首帧 / 列表可用 / 首次数据 / 首次预测 / 单视频 P50·P95 / 队列长度 / RSS；依数据再决策重算法降频扩展、批量取权重、首屏轻量算法、模型延迟加载。
   - 验收：可复现的基线数字 + 实测结论（写回本文档）。

### 第三批：数据访问与迁移底座（**已全数交付**）

**施工顺序**：B5-a1 → B4 → B6-b → B5-a2；B5-a1 / B4 / B6-b / B5-a2 均已完成并 CI 验证（视频 schema v1–v6、中央 schema v1–v5）。

1. **B5-a1 数据角色与所有权基线（已交付，commit 待填）**：新增 `core/database/data_layout.py` 的只解析路径角色 API、`core/database/consistency_audit.py` 的只读差异报告和 `docs/data_ownership.md` 表级矩阵；不迁移物理路径、不改变现有读取目标、不调整双写或 schema 版本来源。
   - 验收：临时库差异/水位/缺表可报告，审计前后文件 hash 与 mtime 不变；中央自有三表不标为可重建投影。
2. **B4 Repository 层**：`Monitor / Prediction / Viewer / ReadModel` 四仓库；UI 禁直连 SQLite（database_query、online_viewers_panel、monitor 现存越界点）；查询工具改注入只读连接工厂（`mode=ro`）。
    - 验收：`ui/` 直连 sqlite3 零命中；相关功能回归通过。
3. **B6-b 版本化迁移统一**：中央 / 视频 / 备份三套 schema 收敛为顺序迁移 + `schema_version` 表；备份恢复复用同一迁移器；失败中止并给出可恢复提示。
    - 验收：新库 = 迁移序列产物；旧库升级路径（含 precision µs 字段）有测试。
4. **B5-a2 数据所有权续包**：在 B4 / B6-b 的只读连接与版本化迁移基础上，扩展同步游标与审计范围；冻结已证明可重建部分的语义，不再新增双写路径。
    - 验收：同步差异可量化报告；游标 / 版本表落地。

### 第四批：数据所有权收口与组合根（**已全数交付**）

1. **B5-b 取消在线多路径双写（已交付，4.1–4.4-F）**：监控 / 预测写入只做一次本地事务；中央投影走 outbox / 增量；备份改 SQLite 一致性快照；取消逐条镜像 commit。逐包 commit 见第五节状态记录。
   - 验收：故障注入后可重建中央库；不依赖跨库原子性。✅（4.1 以 `xfail(strict=True)` 反证并闭合）
   - 4.4-F 边界（经架构顾问裁决）：**保守收口**——仅删确证死代码（覆盖式旧同步 API），完整保留 `legacy` 生产回退通道（`_central_db` / `set_central_db` / `legacy_central_sync` / 各模块 legacy 守卫 / `legacy_central_writes_enabled`）。
2. **算法执行策略正式化（已交付，4.5）**：声明式 `STATELESS_SHARED / LOCKED_SHARED / PER_VIDEO` + 137 项审计清单（`algorithms/execution_policy.py` + `execution_policy_manifest.py` + `docs/algorithm_execution_policy.md`）。**只声明、不改并发**；`PER_VIDEO` 仅声明未生效。
   - 验收：137 全覆盖、无幽灵项、已知有状态模型不得标 `STATELESS_SHARED`、未知默认 `LOCKED_SHARED`。✅
3. **B2 完整化（已交付前置，4.6）**：`core.__init__` 收敛为纯再导出（本已达成）；以 `tests/test_core_import_purity.py` 冻住「无副作用导入」。
   - 验收：无副作用导入保持；替身可注入测试。✅
   - 保留：`core/notification.py` / `core/bilibili_api.py` 为完整性保护文件，未触碰；完整 DI 注入留待阶段 2（`app/bootstrap.py` 显式引导）。

### 第五批：工程化与分发（独立线，可随时并行）

1. **D1 打包单轨（已交付，5.1）**：spec 与 CI 收敛为 onefile 单轨（`BiliMonitor.spec` 为准）；打包冒烟（`tests/test_packaging_smoke.py`）；spec 模块清单同步。
   - 验收：onefile 单轨产物可构建、冒烟通过。✅
2. **D2 更新链信任根（待启，5.3）**：签名 manifest（Ed25519 + SHA-256）+ `.bak` 自动回滚；私钥迁出工作树（CI secret / protected env）；**签实际 EXE manifest（非源文件清单）**；`sign --verify` 纳入发布流程。
3. **D3 CI 对齐（待启，5.2）**：本地 / CI flake8 规则一致；Windows 轻量矩阵；工具版本钉死；覆盖率与依赖扫描先观测、不设硬门槛。
4. **尾巴项（机会性清理，待启，5.4 / 5.5）**：`data/` 假 BV 测试残留（约 5.3MB）；日志保留 / 压缩策略；**ONNX 全局 broken 标志改按模型降级**；死代码评审（`data_cleaner.py` 等）；`scripts/sync_data.py` 一次性脚本处置。

### 第六批：界面演进（最后）

1. **C1 Feature registry**：`FeatureDescriptor`（id / title / icon / category / factory / placement）收拢导航、齿轮菜单与 Dialogs（dialogs.py 现 30 处 `self.gui.`）。
2. **C2 样式与组件收口**：911 处局部 setStyleSheet 组件化（Card / ToolbarButton / MetricLabel + dynamic property）；补字号 / 间距令牌；统一 `clear_layout`（21 处散落 deleteLater）；抽 BarTrend / Pie / Radar 公共图表。
3. **视觉重排（可选项）**：侧导航 + 中央工作区 + 可折叠 inspector——建议前两步稳定后再评估。

### 阶段映射与护栏

- **映射**：第二批 ≈ 状态先行；第三 / 四批 ≈ 数据与组合根（对应原路线「渐进解耦」与「迁移统一」）；第五批 ≈ 并行工程化；第六批 ≈ 界面演进（原路线第 3 阶段的 UI 部分）。
- **护栏**：先特征测试、后实现；小步提交、可回退；不与数据库结构迁移并行；不触碰完整性保护文件；每批收尾五道门禁（black / lint_gate / type_gate / bandit / pytest）。
- **独立并行线**：风控 §13 余项（buvid_fp / w_webid 注入 / 完整性清单更新 / |jordan 求证）以 `docs/risk_control_playbook.md` 为准；测试盲区（utils、core/up_database、training 面板等）随批次顺带补齐，不单立项。
