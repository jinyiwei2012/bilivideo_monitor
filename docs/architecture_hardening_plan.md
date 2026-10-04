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

1. **预测正确性包**（本分支先行）：P0-1 + P0-2 + 过期预测护栏（observation 版本检查，`ui/monitor/_prediction.py:442-447`）。
2. **学习状态可靠性包**：P0-5。
3. **算法缓存并发保护包**：P0-3。
4. **退出与共享容器安全包**：P0-4。
5. **core bootstrap 最小切口**：`import core` 不再开库；先加「无副作用导入」测试，再迁移调用点。

每包收尾统一执行：`black --check --line-length=120 .`、`python scripts/lint_gate.py`、`python scripts/type_gate.py`、`bandit -r . -c pyproject.toml -ll`、`python -m pytest tests/ -q`。

## 六、不建议做（YAGNI）

- 不重写 QML；不微服务化；不换 PostgreSQL；不引入 Redux / 全局字符串事件总线。
- 不把 137 算法进程隔离；不继续以「拆文件」冒充解耦；不同时改 GUI + 线程 + 数据库格式。
- 不加高覆盖率硬门槛；不删疑似重复算法；不动数据库结构——除非先有特征测试作保。
- 不急于持久化全部运行缓存（bias / conformal / schedule）；先明确产品语义。

## 三阶段路线图

1. **正确性与边界（2–4 周）**：第一批五包落地。
2. **渐进解耦（4–8 周）**：AppState/AppActions、Repository、TaskSupervisor、算法执行策略。
3. **数据与界面**：迁移统一 → 数据所有权 → Feature registry → UI 视觉重排。
