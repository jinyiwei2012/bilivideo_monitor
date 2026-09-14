# 更新日志

## Release 2026-09-14 (v3.0.0)

> 预发布（beta 通道）

> 变更区间：`v3.0.0-pre.20260914-173232..HEAD`

### 省流

- 🚀 发版时生成变更日志(省流版进 Release 正文供客户端展示, 完整版写回 CHANGELOG.md)
- 🚀 dialog_host 增加 present_modal 模态分支 + 保活引用随窗口销毁自动回收(RLock 防同线程死锁)
- 🚀 密文版本前缀 f1:/x1: + 完整 HMAC 标签；is_encrypted 改为前缀精确判定（兼容旧格式）(M3.8)
- 🚀 分数中心接入工具菜单 (M2.11e)
- 🚀 新增周/年分数中心窗口（按需物化+范围查询+趋势） (M2.11d)
- 🚀 分数物化器 ensure_scores/current_scores（小时桶+水位线幂等） (M2.11b)
- 🚀 分数表 timestamp 唯一索引 + v4 迁移，upsert 幂等 (M2.11a)
- 🚀 时间戳格式单点定义 TS_FMT/now_ts/format_ts (M2.9c-1)
- 其余 54 项见下方完整分类

### 🚀 新功能

- 发版时生成变更日志(省流版进 Release 正文供客户端展示, 完整版写回 CHANGELOG.md) (`af6a341`)
- dialog_host 增加 present_modal 模态分支 + 保活引用随窗口销毁自动回收(RLock 防同线程死锁) (`c329d6c`)
- 密文版本前缀 f1:/x1: + 完整 HMAC 标签；is_encrypted 改为前缀精确判定（兼容旧格式）(M3.8) (`3660d89`)
- 分数中心接入工具菜单 (M2.11e) (`f22f00d`)
- 新增周/年分数中心窗口（按需物化+范围查询+趋势） (M2.11d) (`10410dd`)
- 分数物化器 ensure_scores/current_scores（小时桶+水位线幂等） (M2.11b) (`7c4c6e9`)
- 分数表 timestamp 唯一索引 + v4 迁移，upsert 幂等 (M2.11a) (`ac5c6d4`)
- 时间戳格式单点定义 TS_FMT/now_ts/format_ts (M2.9c-1) (`ea3c65a`)
- 按 history_days 定期清理旧监控记录 (M2.9a) (`1018e1a`)

### 🐛 修复

- checkout 取全量历史(fetch-depth=0) + tag 指向构建提交，修空变更日志与 tag 错指 (`fe3c171`)
- 哈希行尾归一(CRLF/LF 无关) + CI 强制 UTF-8，修内嵌哈希跨平台漂移 (`3140f53`)
- 里程碑统计弹窗 setId 改用指标下标, 修 hash() 超 int32 导致的构造崩溃 (`a025f6f`)
- 修 F2 复审残留(geometry 非二元回退/关闭后替换单例保活泄漏) + 文档化 GUI 线程要求 (`c9bfaa3`)
- 修复 F 波审计缺陷(保活按身份回收/geometry 越界/模态异常透传/构造函数副作用) (`2258a45`)
- DialogBase.section(parent=) 挂到 parent 自己的布局，修 health_probe 分段归属与顺序 (`89b1e42`)
- present_modal 对非 QDialog 目标做 isinstance 收窄并降级为非模态显示 (`747e951`)
- 弹窗统一呈现层 present()——修复 20 个弹窗构造后从不显示 + 修 DialogBase 关闭时栈溢出崩溃 (`0f6ac77`)
- 权重预热移到首轮预测之后(消除首轮权重的线程时序依赖) + 启动预加载改为有视频时跳过预热 (`fbd144e`)
- _batch_fetch_all 状态栏改经 invoke 回主线程 + invoker 宿主 QObject 销毁后自愈 (P1) (`1e25e21`)
- dataset 特征列白名单校验 + get_summary_stats 单次 UNION ALL (M3.10b) (`21a9cc1`)
- 消除 bass_diffusion 重复 id + 补 4 个缺失 algorithm_id，加唯一/完备门禁 (M3.5) (`5195be4`)
- 修复 _parse_dt 截断导致时间筛选全部失效；拆分 _apply_custom_range，C901 32→31 (M3.4g) (`bab31b0`)
- 恢复 blending_ensemble 基学习器列表，修复 F821 (M2.6b-4) (`177f6e6`)
- 确保备份/迁移/只读连接使用后关闭 (M2.8) (`81d0183`)
- 修复 3 处 NameError/闭包失效并补回归测试 (M1.8) (`738ec37`)

### ⚡ 性能优化

- 新增 prewarm_algorithms 首触预热 + 回测预热改批量写权重(40 次重算/落盘 → 1 次) (`b0ebdb8`)
- Bagging 内部并行改串行(消嵌套过度订阅) + LightGBM 接入内容缓存拟合 (`e15394f`)
- 重算法降频调度(固定时间/推流/anchor/跳变强制刷新 + 重投影复用) (M4) (`9dfd262`)
- viewers 表加 timestamp 索引，最新一条查询 96.6ms→0.1ms(17万行) (P3) (`adcd768`)
- chart.py 缓存 QPolygonF/QPen/QBrush/QFont + 重绘策略(MinimalViewportUpdate/DontSavePainterState/CacheBackground) (P2) (`30ee4f6`)
- database_query 逐行新建连接改复用 + predictions 预载一次，逐行成本降 3.6~5x (P2) (`99e9ed2`)
- 交叉分析的全库读取+137算法集成移出主线程，消除点击冻结 (P1) (`cbd5f58`)
- 封面解码结果按文件签名缓存 + 下载在途去重，消除每轮主线程重解码 (P1) (`db9229d`)
- 推送通知(push_single/manual_push/训练完成)移出主线程，避免阻塞网络 IO 冻结 UI (P1) (`2f6bcdb`)
- 机器密钥派生改惰性并移除 PowerShell 子进程（每进程省约 3s，派生与历史一致）(M3.7) (`a6a3c66`)
- 图表折线+点合并为单图元，图元数 -58~85%、重绘 -39~44% (M2.1) (`695851a`)
- 模型内容缓存接入 TabNet/Stacking/Blending (M2.6b-3) (`ad976a1`)
- 模型内容缓存接入 ET/NGB/残差/TSFC/NARX/Bagging/Quantile + 源码编译门禁 (M2.6b-2) (`40dd96d`)
- 已拟合估计器内容缓存助手 + 接入 RF/XGB/GBR/GP (M2.6b-1) (`9243340`)
- _build_torch_input 按历史内容缓存 (M2.7b) (`7ba6518`)
- curve_fit 结果按内容缓存（LRU+并发安全） (M2.6a) (`15d74c9`)
- 中央同步改用高水位线，只处理增量 (M2.5b) (`62787c4`)
- 同步改用轻量只读读取 video_info，免建表迁移 (M2.5a) (`357551b`)
- get_video_age_hours 排序结果按 video_data 缓存 (M2.7a) (`f82bc2e`)
- diffusion_ts 反向扩散改为少步采样 (M2.10h) (`e5cf51d`)
- 搜索输入去抖后再过滤列表 (M2.10g) (`c8ce60f`)
- 封面加载改用 QImage + 有界线程池 (M2.10f) (`60bdec3`)
- invoker 增加按 key 合并与背压，异常走 logger (M2.10e) (`dc9efbd`)
- 弹幕显示改为后台读取+计数变化才重渲 (M2.2c) (`1a6b320`)
- 详细数据历史分数改为后台缓存读取 (M2.2b) (`3e4a4cf`)
- 在线人数面板改为后台读缓存后再刷新 (M2.2d) (`814d706`)
- 补充 predictions.created_at / danmaku.video_ts / videos.owner_id 索引 (M2.9b) (`5a5035f`)
- 健康页预警收集移出主线程 (M2.2a) (`74e8dfe`)
- 日志面板改用行计数空状态 + pending 加锁 (M2.10c) (`0d868b5`)
- tracemalloc 内存体检移出主线程 (M2.10a) (`45d664c`)
- 视频卡片索引化 + 封面有效性缓存 (M2.3) (`fddccca`)
- 集中抓取改有界线程池 + 可中断等待 (M2.4) (`2285e4d`)
- _adjust_eta 增量化，消除 O(T*10) 全量扫描 (M1.5) (`276a6d1`)
- get_algorithm_stats O(T^2)->O(T) 一次性算权重 (M1.4) (`d237d7c`)
- 权重反馈批量更新，重算/落盘 120→1 (M1.3) (`cd1ea81`)
- 模型缓存改为内存压力驱动释放并保留活跃视频 (M1.2) (`92cca68`)
- try_torch_predict 缓存优先跳过 checkpoint 重读 (M1.1) (`fa0910f`)

### 🧩 重构

- score_center 与 report_scheduler 接入单一显示漏斗 (`474c98d`)
- 13 处显式 exec() 统一走 dialog_host.present_modal()（模态与返回码语义不变） (`4d374d7`)
- DialogBase 加固(geometry 校验/字号缓存/windowIcon) 并删除 0 调用者的 field_row (`cee856e`)
- finetune_panel.py 953->548 行, 拆出 jobs/progress 模块 (M3.3e) (`18a99b4`)
- training_panel.py 1375->53 行, 拆为 8 个 training_* 模块 (M3.3d) (`4df9c17`)
- main_gui_events.py 1262->98 行, 按域拆 3 个 mixin, 41 个对外名字门面保持 (M3.3b) (`34f3a36`)
- _torch_upgrade.py 3051->126 行, 拆为 torch_upgrade 子包, 41 个对外名字门面保持 (M3.3c) (`f38d036`)
- registry.py 拆为 registry_parts 混入包, 门面保留 AlgorithmRegistry/_LRUDict (M3.3a) (`d4bee22`)
- 清零剩余 20 个超标函数(CC>=16), 复杂度基线 20->0 (M3.4b) (`9d0b393`)
- 降 10 个超标函数复杂度(torch_upgrade/registry/trainer/prediction_accuracy/snapshot_tab) 并收紧基线 30->21 (M3.4a) (`d9d2049`)
- _prediction.py 函数内 import 提升到模块级, 保留 3 处必要惰性 (M3.2) (`5c85588`)
- 抽出 _load_one_monitor/_attach_viewers/_attach_history，C901 31→30 (M3.4h) (`56c1aef`)
- 拆分 _persist_settings；修复 OneBot token 保存后内存残留密文，C901 33→32 (M3.4f) (`93782ca`)
- _parse_danmaku_elem 改分派表并补 16 字段行为测试，C901 基线 34→33 (M3.4e) (`b089692`)
- 拆分 _source_a_up_stat 分页/兜底助手，C901 基线 35→34 (M3.4d) (`348ed05`)
- 拆分 suggest_tags / _parse_proxy_list 降低复杂度，C901 基线 37→35 (M3.4b) (`93b3bc7`)
- 删除不可达的 Database._migrate_old_data 死代码，C901 基线 38→37 (M3.4a) (`927dd4d`)
- 清理未用局部绑定与死代码，F841 清零 (M3.1c) (`e066c6b`)
- 移除每抓取写分，详情面板后台先物化再读 (M2.11c) (`41ba3d1`)
- 清理条件改用纯字典序比较（可命中索引）(M2.9c-3) (`90a3f14`)
- 写库时间戳统一走 now_ts/format_ts，修复 accuracy cutoff 比较 (M2.9c-2) (`5502bca`)
- 算法模块改用局部 RandomState(42)，不污染全局 RNG (M2.10b) (`56963d8`)

### 🧪 测试

- _font 缓存补显式「独立副本」断言，对齐修订后的验收 (`87f6d45`)
- 弹窗统一层防线用例(模态透传/回收/section/geometry/防误删/关闭不崩) (`7207fae`)
- 调度判定/重投影/权重隔离回归测试(18 项) + 影子回放漂移验证脚本 (`201f856`)
- 补 _fetch_one_video 锁作用域不变量测试(网络I/O不在锁内) (M3.9c) (`a36fe97`)
- 补 Hedge 在线学习器/派生特征缓存键/单测 9 项 (M3.9b) (`b0d5c1e`)
- 补 A+B 训练目标/稳健增量/告警检测器契约测试 19 项 (M3.9a) (`9e1eadd`)
- 用例改用 machine_key()（随惰性化移除 _MACHINE_KEY） (`0f8b04b`)
- 补齐 M0.2 回归测试（crypto round-trip + registry algorithm_id 唯一性 xfail） (`5f8ff39`)

### 🔧 CI / 构建

- 拆为两条发版线(dev->预发布/beta 通道, main->稳定版) + 发版前内嵌哈希门禁 (`834a8d1`)
- 新增发版流水线(质量门禁前置 -> 编译打包 exe -> 冒烟 -> 发布 Release) (`40e082d`)
- mypy.ini 钉住 platform=win32，修 CI(Linux) 上 6 条平台桩假阳性 (`1853aae`)
- 安装 Qt 系统依赖并让 pytest 走 offscreen，修 libEGL.so.1 导致的 CI 测试全挂 (`6bccc10`)
- 接入 mypy 棘轮门禁(scripts/type_gate.py + 738 条历史错误基线), 移除 || true (M3.8) (`28c028c`)
- 恢复质量门禁（black/flake8棘轮/bandit/pytest 全为真实门禁）+ bandit 5 项修复 (M3.1f) (`e38135f`)

### 📝 文档

- 记录 v3.0.0-pre.20260914-173232 [skip ci] (`a62b558`)
- 记录 v3.0.0-pre.20260914-173232 [skip ci] (`4f410fc`)
- 固化「弹窗必须经 ui.dialog_host 显示」约定 (`480a0c1`)
- 补齐缺失的 2 个算法条目(短期热度感知/季节性分解) + 补充 STL/Hawkes/HIP 参考文献 + 更新页脚 (137/137) (`a2d7ba5`)
- 同步更新文档(AGENTS/CLAUDE/README/CHANGELOG/REFACTOR_BASELINE/ALGORITHMS + 6 份历史报告状态横幅) (`b652bf6`)
- 勾选 7 项验收标准 + 记录 M3 完成情况与已知观察 (`e9c0575`)

### 🧰 维护

- 刷新 main.py 内嵌哈希(registry.py 等 4 项，其中 3 项此前已过期) (`305c355`)
- 清理可消除 noqa(F401/F811) 并等价修复(__all__ 显式再导出/断言消费探测导入), 修 helpers+device 类型 (M3.11) (`e0f5c2b`)
- 取消跟踪运行产物(.omo/ 与 data/ 生成文件) + 补 .gitignore + 刷新内嵌完整性哈希 (M3.10a) (`85b8157`)
- 移除本分支的 GitHub Actions CI 配置 (`a02764d`)
- 记录重构前基线（pytest 115 passed / flake8 959 / CC>15 共 30 个） (`0ef93a3`)

### 🎨 代码风格

- UI 硬编码色值回归 C 令牌(17 文件) + 主题令牌守卫测试 (M3.6) (`e477504`)
- black 复格式新增回归测试 (M3.4c) (`032be3a`)
- black 复格式 install_uni2ts.py (M3.1g) (`11351a3`)
- E402 导入前移清零 + black 复格式 (M3.1e) (`c9925f3`)
- 清理 F824/E303/E741/E731/F401/F541/F811/E401/E702 (M3.1d) (`830f4a1`)
- black --line-length=120 全仓格式化 (M3.1b) (`a21c90d`)
- 清理 528 处未用导入/空白/分号（ruff 安全修复）(M3.1a) (`e65a199`)
- _service 导入前移，消除 16 处 E402 (`e6d7f71`)

### • 其他

- mypy 全仓清零(1513->0) + 消除全部 type: ignore + 类型门禁转零容忍 (M3.12b) (`6ca6627`)
- 修复 core/algorithms/models/ui(training,finetune,settings) 的 mypy 错误, 1513->216 (M3.12a) (`6f49b00`)

## Release 2026-09-14 (v3.0.0)

> 预发布（beta 通道）

> 变更区间：`3140f53b9ff06fe60d309c6fc5a518b47569a112..HEAD`

### 省流

- 以内部维护与稳定性改进为主

## 重构/优化里程碑 M0–M3（`refactor/optimization`）

### ✅ 质量门禁（全部硬性，已移除 `|| true` / `exit 0`）
- `flake8` **959 → 0**；复杂度基线 30 → **0**（无 CC>=16 函数）
- `mypy` **1513 → 0**（739 条历史错误全部真修，基线清空 = 零容忍）；`# type: ignore` 全部消除
- `black --check` 340 文件通过；`bandit -ll` Medium/High = 0
- `pytest` **115 → 258 passed**
- 新增 `scripts/lint_gate.py`（复杂度棘轮）与 `scripts/type_gate.py`（类型棘轮）并接入 CI

### 🧩 结构拆分（对外导入面零变）
- `registry.py` 1333→126（+`registry_parts/`）；`_torch_upgrade.py` 3051→126（+`torch_upgrade/`，41 个名字保持）
- `main_gui_events.py` 1262→96（+3 个域 mixin，41 个名字保持）
- `training_panel.py` 1375→43（+9 个模块）；`finetune_panel.py` 953→472（+2 个模块）
- 注册表算法数 **137**，id 唯一且完备（修正 `bass_diffusion_growth` 冲突，补 4 个缺失 id）

### 📉 复杂度
- 30 个 CC>=16 函数全部降至 ≤15（`try_torch_predict` 42→14、`_prepare_video_data` 35→5、`predict_all` 27→5 等）

### 🎨 主题令牌化
- `ui/theme.py` 集中 **78 个令牌**（`series`/`series_light`/`dash_*`/`pred_*`/`grade_colors`/`sentiment_*`/`period_colors`/`heatmap`/`warn_*` 等）
- `ui/` 内硬编码色值 125 处 → 2 处（仅文档描述性提及）；两主题键集合同构（守卫测试）

### 🔐 加密加固
- 密文版本前缀 `f1:`/`x1:`；XOR 回退 HMAC 标签 32bit → 完整 64 hex；`is_encrypted` 前缀精确判定
- 机器密钥改惰性 + 进程内缓存，移除从未生效的 PowerShell CPU 探测（冷启动约省 3s）

### 🧹 仓库与 DB 卫生
- 取消跟踪 `.omo/run-continuation/*.json`、`data/*.json`、`data/**/*.csv` 运行产物并补全 `.gitignore`
- 刷新 `main.py` 内嵌完整性哈希；`dataset.py` 监控记录列名白名单校验（防拼接注入）
- `central_query.get_summary_stats` 三次 COUNT 合并为单次 UNION ALL

### 🧪 测试
- 新增契约/回归测试覆盖：A+B 双尺度训练目标、稳健增量、告警检测器、Hedge 在线学习器、
  `_fetch_one_video` 锁作用域（网络 I/O 不在锁内）、主题令牌守卫、加密加固、注册表 id 唯一/完备、
  算法源码可编译、索引、后台缓存、时间戳规范格式等

### ⚠️ 已知观察（未改行为，已用测试锁定）
- `algorithms/training/dataset.py` 的长期目标 `long_rate[N-1]` 补 0 会被末端样本均值纳入，
  轻微稀释靠近序列尾部的长期监督（`test_tail_zero_pad_dilutes_long_target`）。


## Release 2026-09-03 (v3.2.0)

### 🎯 预测精度提升体系
- **稳健增量速率**: median+MAD 剪除 + API 冻结/补量恢复（抗整数量化/延迟/一次性补量），分场景断言通过
- **log-ETA 集成**: 各算法 predicted_hours 在 log 空间加权取中位 → `_weighted.eta`，结合 anchor 阈值
- **生命周期自适应**: early/steady/declining 阶段特征调制置信度，全历史数据自适应
- **权重闭环修复**: `update_accuracy` 签名修复 + online_learner 全局聚合回流 + 回测预热冷启动
- **保形预测 log 域校准**: 乘法区间回解，覆盖率显著提升
- **短期热度感知算法**: viewers 在线人数/时段信号融合 + 自激励动量
- **返回值统一重构**: 120+ 算法收敛到 `_std_result` 统一构造 PredictionResult

### 🧠 A+B 双尺度模型训练
- **双尺度训练目标**: `dataset.py` 目标重构为 `[H 步稳健增量 ⊕ 1 维长期平均速率]`
  - 短期段 = 未来 horizon 步稳健增量（MAD 剪除），与推理端增量口径一致
  - 长期段 = 未来 long_window(≈1h) 步真实平均速率，与 velocity 共用同一 z-score 缩放器
- **head 自动扩维**: `expand_final_projection()` 将唯一投影 Linear 从 H 扩至 H+1（零初始化），forward 零改动；25+ 可扩展模型输出 [B, H+1]
- **checkpoint 双向兼容**: `load_checkpoint_model()` 自动识别 H / H+1 宽 head，旧模型无缝续训与推理
- **推理双消费**: 短期 `y[0:H]` 驱动当前速度/短期增量，长期 `y[horizon]` 作为 ETA 平均速率；不可扩展模型（N-BEATS/DeepAR 等）自动回退单头
- **全链路适配**: trainer / trainer_io / onnx_exporter（head 宽推断）/ 独立推理端（cnn_image）同步更新

### 🚨 智能告警 v2 + 阈值扩档
- **确定度分级**: AlertHit confidence 体系（high/medium/low），high 全渠道推送、low 仅状态栏+日志，避免告警疲劳
- **修复 P0 冷却反转 / P1 样本窗口不足 / P2 单点基线抖动**
- **A1 阈值自动扩档**: 突破通知后自动追加下一阶梯阈值，进度持久化防重复
- **A2 异动复盘卡**: `reports/alerts/alert_review_*.html`（明细 + 置信 + 近 12 点迷你趋势）
- **A3 弹幕情绪侧写**: 弹幕即分析 + 告警附带情绪摘要

### 🖥️ 界面与驻留
- **B1 系统托盘**: 关闭窗口最小化至托盘继续监控（close_to_tray / tray_notify 配置）
- **C3 AI 周报解读**: report_exporter 支持 AI 解读段落 + 定时导出异步生成

### 🔧 前置重构（本分支基线）
- 算法接口统一（去 ModelAlgorithmAdapter、`_predict_inner` 收敛）、镜像双写/常量/schema 单点化
- 洛天依主题体系 + emoji 换装 + 口吻文案库

## Release 2026-06-01 (v2.8.0)

### 🔧 重构
- **大文件模块级拆分**：4 个超 1000 行文件拆分为 20 个小模块
  - `bilibili_api.py` (1414行) → 5 文件：bilibili_api / request / auth / video / up
  - `central_db.py` (1342行) → 4 文件：central_db / crud / query / backup
  - `main_gui.py` (1467行) → 4 文件：main_gui / events / tick / data
  - `settings_window.py` (2653行) → 7 文件：settings_window / general / monitor / notification / proxy / account / advanced
- **猴子补丁 → Mixin 多继承**：`BilibiliAPI` 的方法从运行时动态绑定改为 `_RequestMixin, _AuthMixin, _VideoMixin, _UpMixin` 类继承，IDE 可跳转/补全
- **GCN → PyTorch 双引擎**：`graph_neural.py` 优先使用 2 层 PyTorch GCN 训练（100 epochs 自监督图重构），无 torch 时 fallback 到 numpy 拉普拉斯特征映射
- **完整性校验重写**：`main.py` 的 `chr()` 混淆校验替换为 SHA-256 文件哈希；`run.py` 消除 DRY 重复直接复用 main.py
- **11 处 `# noqa: C901` 全部移除**：`training_panel.py` (3)、`settings_account.py`、`database_query.py`、`up_fetcher.py` 等函数的圈复杂度通过拆分子方法降低

### 🐛 修复
- **6 轮代码审查，100+ 问题清零**：
  - `smart_alert`: 缺 `import threading`、S6 累积值改用增量
  - `up_fetcher`: `_get_api()` 实例方法调用修正、循环导入缓解
  - `bilibili_api`: `_switch_account` 方法名、UA 永久移除、单例双检锁
  - `notification`: `asyncio.run` 兼容已有事件循环、`ThreadPoolExecutor` 复用
  - `database_query`: `int(0) or 10000` bug、URI 编码、死代码
  - `entry_tab`: `dt_str/bvids/periods` 未定义、重复行清理
  - `tag_manager`: `pack_forget` 隐藏、filter 索引错位、`all` 遮蔽内置
  - `weight_manager`: 加权平均分母 `sum(w_i)` 修复、`get_weight` 加读锁
  - `graph_neural`: GCN 矩阵计算、RLock 死锁、孤立节点零度
  - `model_adapter`: `__bases__` → `__mro__`、速度计算时间差
  - `checkpoint_io`: 路径穿越 + zip bomb 防护
  - `geetest_solver`: AES 密钥 `digest`、FIPS `usedforsecurity`
  - `sentiment_analyzer`: 否定词权重 -1.0、扩展 2-token 检测
  - `downloader`: aria2 超时 + 哈希校验基础设施
  - 算法签名修复: `svr_predictor` / `kalman_filter` / `holt_winters` 键名兼容
  - `ai_qa`: `fromisoformat` Python 3.10 兼容
  - `settings_account`: 多个登录路径补充 `add_account` 调用
  - `backtest_panel`: `video_db.get_predictions` 方法缺失 → 新增
  - 注释添加过程引入的 12 处 SyntaxError（重复行）全部修复

### 📝 文档
- **205 个 Python 文件添加中文注释**：模块级 docstring + 类/方法/函数 docstring + 复杂逻辑行内注释
- 新增 `scripts/update_hashes.py`：一键更新 main.py 完整性校验哈希

## Release 2026-05-26 (v2.7.1)

### 🐛 修复
- **`ModelAlgorithmAdapter` 未转发 `build_model`**: `registry.get_trainable_info()` 检测不到任何有底模的算法（始终返回空列表），因为 `ModelAlgorithmAdapter.__init__` 未将底层算法的 `build_model` 暴露给注册器。新增 `build_model` property 委托到底层 `self.algo`，27 个深度学习算法恢复可训练识别。

### ✨ 新功能
- **`build_model` 属性转发**: `ModelAlgorithmAdapter` 新增 `build_model` property，自动将底层算法的 `build_model` 方法暴露给注册器，无需为每个算法单独适配。

## Release 2026-05-26 (v2.7.0)

### ✨ 新功能
- **双更新通道**: 支持稳定版/测试版切换，测试版从 `pre-release` 分支拉取，稳定版从 `releases` 分支
- **pre-release 分支**: 新功能先推送 `pre-release` 分支测试，稳定后合并到 `releases`
- **Git 拉取自动匹配分支**: 测试版 `git pull origin pre-release`，稳定版 `git pull origin releases`

### 🧹 优化
- **测试版暂不提供 EXE**: 测试通道仅提供 Git/ZIP 更新方式

## Release 2026-05-26 (v2.6.1)

### 🧹 优化
- **模型加载/推理日志格式化**: `[算法] 视频(BV),使用'微调模型(v3)'预测成功 预测结果: xxx`
- **日志格式统一**: FileLogger 和 stderr 输出使用相同 ISO 时间格式
- **启动日志显示 checkpoint 状态**: 显示每个算法的模型来源（视频微调/底模/numpy）

## Release 2026-05-26 (v2.6.0)

### ✨ 新功能
- **aria2 下载器集成**: `utils/downloader.py` — 首次使用自动下载 aria2c.exe，支持多线程断点续传 + 实时进度回调
- **自适应更新弹窗**: 检测运行模式（源码/PyInstaller），源码提供 Git Pull / aria2 下载 ZIP，打包版提供 aria2 下载 EXE + 重启脚本
- **窗口标题显示版本号**: `B站视频监控与播放量预测系统 v2.6.0`
- **备份差异检测+弹窗询问**: 退出时比较 `core/data/` 与 `data/` 差异，弹窗让用户选择是否同步
- **双写机制**: `VideoDatabase` 运行时同时写入 `core/data/<BV>` 和 `data/<BV>`，退出同步中央库
- **预测日志格式化**: `[BV号] [算法名] 预测: xxx` (DEBUG)，`[BV号] 综合预测: xxx` (INFO)

### 🐛 修复
- **import 崩溃修复**: `core.__init__` 导出 `db` 别名、`bilibili_api` 添加模块级 wrapper（`get_video_info`、`proxy_manager`、`close` 等 7 个）
- **数据路径修复**: `_ACTIVE_DIR` 从 `core/data` 改回 `core/data`，退出时同步到 `data/`；新增 `_migrate_old_data()` 自动迁移已有数据
- **预测结果 ValueError**: `success_list` 缺 `predicted_hours` 导致 4-tuple→5-tuple 解包失败
- **watch_list 空配置**: 配置文件 `watch_list` 为空时从数据库兜底加载已有 17 个视频
- **LightGBM UserWarning**: 抑制 `X does not have valid feature names` 警告
- **Lag-Llama 循环导入**: 安装 `lightning>=2.1.0` 修复 `Callback` 循环导入

### 🧹 代码质量
- **flake8 0 error**: 修复 557 个 lint 错误（F401×43、F841×26、F821×23、E226×29、E402×17、C901×12 等）
- **全库复杂度降至 C 级**: 消除全部 D/E/F 级函数（12 个），最高 CC 仅 C(19)
- **black 格式化 80 文件**: 统一风格
- **`hf_loader` 日志降级**: WARNING→DEBUG，成功时 INFO 显示 torch 推理

### 📦 打包
- **BiliMonitor.spec 全面重写**: 97 个算法 hiddenimports、Tcl/Tk 运行时、torch/scipy/sklearn 子包、UPX 压缩
- **`hook-bilibili_api.py`**: 按官方 issue #39 收集 59 个数据文件

## Release 2026-05-25 (v2.5.0)

### ✨ 新功能
- **20 种新预测算法** (83 → 103):
  - 时间序列: NARX外生自回归、MSTL多重季节分解、TBATS季节分解、GARCH波动率
  - 深度学习: TIDE稠密编码器、TSMixer MLP混合器、DeepAR概率自回归、Chronos零样本、Mamba S6状态空间、iTransformer倒置、SCINet卷积交互、TimesFM谷歌、Time-MoE专家混合
  - 统计模型: DTW-kNN类比预测
  - 集成模型: NGBoost自然梯度提升、TabNet注意力特征网络
  - 高级分析: 频域分解、SIRD传染病传播模型、CausalImpact因果推断、层级贝叶斯
- **9 个新 Torch 模型**: 全部新深度学习算法实现 PyTorch 模型，接入 `try_torch_predict` 降级链
- **DirectML 推理加速**: 支持 Intel NPU (AI Boost) / GPU 通过 DirectML 运行 PyTorch 推理
- **CUDA 冒烟测试**: `get_device()` 自动验证 GPU 实际可用，失败降级 CPU
- **自动更新检查**: 启动时异步检测 GitHub Release，弹窗展示 changelog
- **CSV/JSON 定时导出**: 支持按小时/天/周自动导出数据报告至 reports/ 目录
- **模型批量导出/导入**: 一键打包/解包 algorithms/checkpoints/ 为 zip，zip合并/覆盖两种模式

### 🐛 修复
- `change_point_detection.py`: 斜率计算改用 `np.polyfit` 避免大数溢出
- `hf_loader.py`: transformers 元数据异常时正确降级
- `main_gui.py`: 移除不存在的 `open_algorithm_comparison` 调用

### 📚 文档
- README 更新至 103 种算法，新增 DirectML/XPU/NPU 安装指南
- ALGORITHMS.md 新增 20 种算法详细说明 + 14 篇参考论文

## Release 2026-05-20 (v2.4.0)

### ✨ 新功能
- **PyTorch 训练基础设施**: 新增 `algorithms/training/` 模块
  - `device.py`: GPU 自动检测（CUDA > MPS > CPU），支持 `force_cpu()` 全局开关
  - `checkpoint_manager.py`: 多版本 checkpoint 管理，支持 `list_versions / save / load / activate / delete`，目录结构 `algorithms/checkpoints/<algo_id>/v<N>_<时间戳>.pt`
  - `dataset.py`: `VideoTimeSeriesDataset` 从每视频 SQLite DB 滑动窗口加载，支持全局训练 + 指定视频微调两种模式
  - `trainer.py`: 通用训练管线 `ModelTrainer.train_global / finetune_for_video / estimate_data_size`，z-score 归一化 + 单步速度差分作为训练目标
  - `hf_loader.py`: HuggingFace Foundation 模型懒加载（MOIRAI / Lag-Llama），首次自动下载缓存
- **8 个 2026 前沿预测算法**:
  - `moirai`: Salesforce MOIRAI-1.1-R-small，HF 通用时序基座
  - `lag_llama`: time-series-foundation-models/Lag-Llama，lag-feature 加权预测
  - `knf`: Koopman Neural Forecaster（全局算子 + 局部低秩修正 + meta 网络）
  - `diffusion_ts`: 简化 DDPM + UNet1D，100 步反向扩散采样
  - `mar_bilstm`: BiLSTM + 可学习 Markov 转移矩阵，5 状态混合输出
  - `cnn_image`: 时序数据展平成 2D 图像，双分支 Conv2d（kernel=3 dilation=1/2）
  - `tsfc_classification`（统计模型）: sklearn `RandomForestClassifier`，弱标签 5 桶（decay/slow/steady/growing/viral）
  - `distdf_align`（高级分析）: scipy `wasserstein_distance` 度量分布漂移，自适应 α 加权
- **14 个既有深度学习算法升级为真实 PyTorch 实现**:
  - 升级文件: `attention_mechanism`, `bilstm_simple`, `cnn_lstm_hybrid`, `dlinear_simple`, `gru_simple`, `informer_simple`, `lstm_simple`, `mlp_predictor`, `n_beats_simple`, `neural_network_simple`, `patch_tst_simple`, `tcn_simple`, `tft_simple`, `timess_net_simple`
  - 新增统一辅助模块 `algorithms/models/deep_learning/_torch_upgrade.py`，包含 13 个 torch 模型类 + `try_torch_predict()` 调度
  - **三级优雅降级链**: torch checkpoint 推理 → numpy 简化版 → 速度估算兜底
  - 保留原 numpy 简化实现作为 `_numpy_predict`，无 checkpoint 或推理失败时无缝降级，行为完全向后兼容
- **设置窗口新增「模型训练」分页** (`ui/settings_window.py`):
  - **训练设备**: 实时显示 CUDA/MPS/CPU 设备名 + 显存容量 + "强制使用 CPU" 开关
  - **数据规模**: 后台估算视频总数 / 训练样本数 / 预计单算法训练时间
  - **可训练算法列表**: 自动发现 18 个 torch 算法（14 升级 + 4 新增本地训练），显示算法名/ID/checkpoint 状态/版本数，支持 全选 / 全不选 / 仅选未训练
  - **训练控制**: Epoch/Batch 可调，实时进度条 + 每 epoch loss + ETA，支持取消（算法间隙生效）
  - **版本管理弹窗**: 每个算法独立 Treeview 显示所有版本，支持 激活 / 删除 / 导出 .pt
  - 后台 `threading.Thread` + `queue.Queue` 异步训练，主线程 `window.after` 轮询，不阻塞 UI

### 🔧 优化
- **新依赖** (`requirements.txt`): torch>=2.1.0、transformers>=4.40.0、huggingface-hub>=0.20.0、safetensors>=0.4.0；CPU/GPU 安装方式见 README
- **.gitignore**: 排除 `algorithms/checkpoints/*/`（保留 `README.md`）、`*.pt`、`*.pkl` 避免大文件入库
- **算法总数 75 → 83**: 8 个 2026 新算法增量加入，自动发现机制无需修改注册器

### 🐛 修复
- **U+0001 控制字符污染**: Phase 3 批量升级脚本中 regex backreference `\1` 误写入文件，导致 11 个 deep_learning 算法 import 失败，算法总数从 83 跌至 72；已用清理脚本去除控制字符并恢复

### 📐 架构
- **`BaseAlgorithm` 接口兼容**: `mlp_predictor` / `attention_mechanism` 保持原 full_params 签名 `predict(current_views, target_views, history_data, video_info) -> Optional[Tuple[int, float]]`，通过内部 `_try_torch_predict` 包装为统一调度路径
- **Foundation 模型懒加载**: MOIRAI / Lag-Llama 首次预测时自动从 HuggingFace 下载（`~/.cache/huggingface/`），不阻塞应用启动

## Release 2026-05-19 (v2.3.0)

### ✨ 新功能
- **图表"新增"模式（默认）**: 新增第三种图表模式 `step`，绘制每两次刷新之间的播放量增量（`v[i] - v[i-1]`）折线图，0 基线，正增量绿点 / 负增量红点；右上角实时统计「N 点 | 总+X | 均+Y」
- **新增模式自动刷新 + 其他模式手动渲染**: 默认进入「新增」模式自动跟随数据刷新；切到「增量」/「全量」需点击「渲染」按钮才绘制，避免重数据下的卡顿
- **渲染门控防绕过**: 新增 `_rendered_modes` 集合追踪已手动渲染过的模式；窗口 resize 不会绕过"手动点击"门控自动重绘 delta/full

### 🔧 优化
- **图表代码拆分**: `_draw_step_chart` 拆为 `_step_compute_scale` / `_step_draw_grid` / `_step_draw_series` 三个职责单一的子函数，圈复杂度从 16 降至 15 以下，符合 flake8 `max-complexity=15` 约束
- **切换 tab/视频自动清图**: 切回趋势 tab 或切换视频时，若当前为非自动模式（增量/全量）则清除旧图显示占位提示（"点击「渲染XX」查看…"），避免显示其他视频的残留数据

## Release 2026-05-11 (v2.2.0)

### ✨ 新功能
- **图表增量/全量模式**: 新增增量模式（以起始播放量为基准归零，仅显示增长量）和全量模式（显示绝对值），图表明细中可切换
- **图表显示点数可配置**: 新增"显示 X 点"输入框，默认 20 点，固定间隔均匀取点（替代原来固定 8 点的硬编码）
- **全量模式手动渲染**: 全量模式下不自动重绘，点击「渲染全量」按钮后手动触发，避免密集数据时卡顿

### 🔧 优化
- **UI自适应缩放**: 主界面改为 grid 比例布局（22/58/20），所有对话框窗口使用屏幕百分比尺寸，标题/封面自适应折行
- **拉取后 UI 卡死修复**: 移除旧 `_on_single_fetch_done` 回调（与 Worker 的 `_on_fetch_done` 重复调用，导致每次拉取做两次预测 + 两次图表绘制）；Worker 新增 `_fetching` 并发锁防止同一视频重复拉取；`_predict_single` 新增 `_prediction_semaphore(2)` 限制并发预测数量，防止 GIL 饥饿

### 🐛 修复
- **预测时间缺少年份**: ETA 显示从 `%m-%d %H:%M` 改为 `%Y-%m-%d %H:%M`，避免跨年混淆
- **图表时间标签缺月份**: 时间轴从 `%H:%M` 改为 `%m-%d %H:%M`，跨天数据可识别日期

## Release 2026-05-11 (v2.1.0)

### 🔧 优化
- **sync_to_central 性能**: 从 4.5-5s 降至 0.5s（后续同步），预测同步改用 COUNT(DISTINCT)快速检查 + GROUP BY 去重避免全表扫描
- **拉取数据后 UI 卡顿修复**: 中央库同步 `sync_from_video_db` 从主线程回调移入工作线程，消除 UI 阻塞；图表重绘添加 100ms 防抖
- **索引优化**: 新增 `idx_predictions_bvid` 索引加速 predictions 表按 bvid 查询

### 🐛 修复
- **predictions 未同步 created_at**: INSERT 时携带 created_at 确保后续 MAX(created_at) 比较正确
- **多 Worker 同时完成时的 UI 卡顿**: `_on_fetch_done` 图表重绘防抖合并，避免重复 Canvas 操作


## Release 2026-05-10

### ✨ 新功能
- **UP主追踪多源获取**: 新增 `core/up_fetcher.py`，整合 bilibili-api-python / curl_cffi / 自有 API 三层独立数据源，避免单一接口 412 限制导致完全不可用
- **设置窗口 - 关于作者**: 新增"关于作者"标签页，包含项目信息、版本号、GitHub 仓库链接、B站主页链接（点击浏览器跳转）
- **封面管理器**: 封面图片自动本地缓存（data/cover/），MD5 完整性校验，损坏自动重下载，文件命名格式 `{bvid}_{title}.jpg`

### 🔧 优化
- **README 全面更新**: 项目结构补充缺失文件（cover_manager.py、proxy_manager.py、smart_alert.py 等）、算法计数修正、数据路径修正
- **算法计数修正**: `__init__.py` 元数据 40+ → 75 种算法
- **PyInstaller 打包**: 从 onefile 改为 onedir 模式，运行时文件（data/、config/）暴露在 exe 同级目录

### 🐛 修复
- **UP主追踪 412 限制**: `get_up_info`/`get_up_stat`/`search_up_users` 改为多源轮询，任意源成功即返回
- **公共请求代理支持**: `_request_public` 增加代理绑定，使无 Cookie 请求也能走代理轮换
- **资源泄露修复**: 数据库连接池正确释放
- **代理 SSL 验证**: SOCKS5 代理关闭 SSL 验证避免自签名证书报错
- **代理批量导入**: 支持多行代理粘贴导入


## Release 2026-05-05

### ✨ 新功能
- **代理模块化**: 提取独立 `ProxyManager` 类，支持代理轮询、UA 绑定、可用性检测、失败自动剔除
- **代理测试 UI**: 测试代理时显示出口 IP 并记录日志
- **AI 多配置管理**: 支持 OpenAI / DeepSeek / Claude / SiliconFlow 等多配置切换

### 🔧 优化
- **配置统一**: 所有配置文件迁移至 `data/` 目录（settings.json、network_config.json）
- **设置窗口合并**: 网络设置（代理/Cookie/扫码登录）合并至统一设置窗口
- **日志系统**: 网络请求输出 DEBUG 级别日志
- **代码合规**: Black 格式化、Flake8/MyPy/Bandit/Radon 全量合规修复
- **主题精简**: 移除昼夜切换功能，固定亮色主题

### 🐛 修复
- **412 错误重试**: 指数退避 + 抖动，自动切换代理和 UA
- **代理日志**: `core.proxy_manager` 日志接入系统日志面板
- **代理测试**: 超时处理、ASN 解析异常、失败原因高亮显示
- **Cookie 登录**: 支持自动识别格式并同步登录状态
- **资源泄露**: 数据库 WAL 模式定时检查


## Release 2026-04-30

### ✨ 新功能
- **75 种预测算法**: 基础速度、增长模型、时间序列、深度学习、统计模型、集成学习、高级分析等
- **算法权重管理**: ML 权重自动调整（含 Hedge 在线学习算法）
- **LLM 集成**: 弹幕智能分析（情感/关键词）、历史问答
- **看板模式**: 多视频关键指标一览面板
- **里程碑统计**: 多视频多周期柱状对比
- **数据对比**: 趋势折线图 + 快照柱状图
- **交叉计算**: 多视频播放量交会预测

### 🔧 优化
- 算法自动发现机制：放在 `models/` 下即可自动注册
- 每视频独立线程 + 独立数据库
- CustomTkinter 现代化 UI
