# 重构可行性报告

> 项目:B站视频监控与播放量预测系统(pyqt6 分支)
> 日期:2026-08-11
> 范围:全代码库臃肿度诊断 + 重构机会评估 + 分阶段实施方案
> 行数说明:本报告行号为本地 `Measure-Object` 实测,含 CRLF 差异(±10%),与 IDE 显示可能略有出入。

---

## 1. 执行摘要

| 维度 | 结论 |
|---|---|
| 架构方向 | **健康** — 分层清晰(ui→algorithms/core/utils/config),无反向依赖,仅 1 处小瑕疵 |
| 臃肿类型 | 不是"架构烂",而是**体量失控 + 局部重复 + 少量上帝文件/上帝函数** |
| 总规模 | 294 个 .py 文件,**73,198 行** |
| 最高优先级 | 数据库层 SQL 重复(4 份同款 INSERT)、UI 训练面板双套实现、`_torch_upgrade.py` 上帝文件 |
| 已完成的依赖治理 | uni2ts 2.0.0 硬约束解锁 + GPU torch 2.13 恢复(见 commit 8496481) |
| 总体建议 | **渐进式重构,不做重写**。P0 清理 3-4 天,P1 结构重构 1-2 周,P2 深度重构可选 |

核心判断:**73K 行中约 15-20%(1.1-1.5 万行)是可安全消除的重复/冗余**,重构风险集中在算法数值行为与 UI 布局回归,均可通过回测 + 冒烟测试兜底。

---

## 2. 现状基线(客观指标)

### 2.1 模块规模分布

| 模块 | 文件数 | 行数 | 占比 | 判定 |
|---|---:|---:|---:|---|
| algorithms/ | 169 | 37,442 | 51% | 算法工厂 + 136 算法,体量最大 |
| ui/ | 66 | 23,466 | 32% | 60+ 面板,PyQt6 |
| core/ | 24 | 7,146 | 10% | B站 API + 数据库 |
| utils/ | 19 | 2,993 | 4% | 工具函数 |
| config/ + scripts/ + 入口 | 6 | 649 | 1% | 配置与启动 |

### 2.2 巨型文件 Top 10

| 文件 | 行数 | 问题 |
|---|---:|---|
| `algorithms/models/deep_learning/_torch_upgrade.py` | **2146** | 上帝文件:33 个模型类 + VRAM 管理 + 推理编排 + 预处理 4 个子系统 |
| `ui/training_panel.py` | **1513** | 训练面板 + 批量训练对话框(240 行)+ 配置弹窗 |
| `ui/main_gui_events.py` | **1134** | 30+ 模块级事件函数平铺,无类组织 |
| `ui/finetune_panel.py` | **1068** | 微调面板,共享基类后仍 1000+ 行 |
| `core/database/video_db.py` | **1028** | 镜像双写 SQL 重复 + schema 双份 |
| `ui/detail_panel.py` | **952** | 4 个 Tab 构建+刷新全在类内 |
| `algorithms/training/trainer.py` | **865** | 训练编排 + 数据集构建 + checkpoint 逻辑未拆净 |
| `ui/snapshot_tab.py` | **862** | 自带 QPainter 柱状图组件 |
| `ui/danmaku_analysis.py` | **858** | 自带 `_sty` 重复公共组件 + 自定义绘图 |
| `ui/database_query.py` | **827** | 查询 UI + 参数页 + 导出 |

### 2.3 圈复杂度热点(radon)

| 函数 | 文件:行 | 复杂度 | 评级 |
|---|---:|---:|---|
| `try_torch_predict` | `_torch_upgrade.py:1928` | **61** | F(极差) |
| `BaseAlgorithm.detect_surge` | `base.py:438` | **37** | E |
| `_rank_backends` | `_torch_upgrade.py:2177` | **36** | E |
| `_prepare_video_data` | `registry.py:160` | **29** | D |
| `_train_one` | `trainer.py:296` | **31** | E |
| `_parse_result` | `model_adapter.py:163` | **21** | D |
| `detect_paid_promotion` | `smart_alert.py:277` | 高 | — |
| `login_with_password` | `bilibili_auth.py:111` | 高(210 行) | — |

### 2.4 可维护性指数(MI)

多数模块为 A(radon 认为整体可维护);异常项:`ui/training_panel.py`(C)、`ui/detail_panel.py`(B)。

### 2.5 依赖结构

```
ui → algorithms / core / utils / config
algorithms → utils
core → utils / config
utils → config
```
✅ 无反向依赖(core/algorithms 不 import ui)。唯一瑕疵:`utils/ai_qa.py:254 → core.smart_alert`(工具层反向依赖核心层)。

---

## 3. 臃肿热点诊断

### 3.1 算法层(algorithms/,37K 行)

**A1. predict() 样板骨架双轨并存** ⚠️ 最大重复源
- 手写兜底块 `predicted_hours = remaining / velocity if velocity > 0 else float("inf")` 出现 **79 次 / 52 文件**;`confidence=0.3, current_views=..., current_velocity=...` 兜底 **45 次 / 33 文件**;`PredictionResult(...)` 构造 **88 次 / 36 文件**。
- 而 `BaseAlgorithm._fallback()`(base.py:96-130)**已存在同样功能的通用兜底**,仅 49 次/20 文件被使用 → **两套约定并存,新算法无所适从**。
- 单文件极端案例:`svr_predictor.py` 内同一段 `predicted_hours=-1, confidence=0.0` 无效结果块重复 **4 次**(L79-90 / L96-108 / L140-151 / L168-180)。
- 证据:`content/virality_score.py:119-127`、`event/hot_trend.py:115-123`、`frequency/spectral_residual.py:102-110` 三个文件兜底块逐行相同,仅 N 阈值与 method 名不同。
- 另 5 个文件(logistic_growth / gompertz_growth / weibull_growth / richards_curve / holt_winters)用 `_predict_legacy + predict()` 薄包装模式,结构逐字相同。

**A2. registry.py 职责过载**(约 700 行 / 21 个 classmethod)
单类横跨:注册生命周期、特征工程(`_prepare_video_data` D/29)、历史合并、线程池并行、3 套加权机制(窗口/一致性/集成)、异常检测、集成预测、准确率回馈、权重管理门面、训练接口、生命周期管理。直接 import weight_manager / conformal / checkpoint_manager 三个子系统。

**A3. `_torch_upgrade.py` 上帝文件(2146 行,4 个子系统)**
1. 33 个 nn.Module 模型类(L57-1710)——LSTM/GRU/BiLSTM 三个类 99% 相同(仅层类型与 head 维度差);
2. VRAM/LRU 缓存管理(L1785-1926)——完整子系统;
3. 推理编排 `try_torch_predict`(F/61)+ 后端排序 `_rank_backends`(E/36)(L1928-2353);
4. 预处理/结果构造(L2356-2518)。
→ 全部 39 个 `deep_learning/*.py` 都 import 它,耦合面极大。

**A4. 训练管线边界未拆净**
- `trainer.py:865` 行:`_train_one` E/31;checkpoint 的**读取/清理/元数据逻辑仍在 trainer 内**(`trainer_io.py` 只抽走了保存),`_instantiate_algorithm` 也在 trainer。
- `dataset.py:429` 行:直接读 SQLite(L158-197)+ 扫描文件系统,数据集模块混入 DB I/O。
- `registry.py` 的 `get_trainable_info` 直接 new `CheckpointManager`,训练查询与注册表耦合。

### 3.2 UI 层(ui/,23K 行)

**U1. 训练相关代码三处并存** ⚠️ 最高优先
- `training_base.py:676-735` 已有权威的线程+队列+QTimer 轮询实现;
- `settings_training.py:376-558` 因无法继承 BaseTrainingPanel(它是 SettingsWindow 的 Mixin),**整体重抄了约 180 行轮询逻辑**;
- `settings_training.py:568-701` 又重抄了 `training_version.py:50-310` 的 checkpoint 版本管理(约 130 行)。
→ 合并复用可删 **~310 行**。

**U2. 双胞胎文件**:`ui/algorithm_compare.py`(493 行)与 `ui/algorithm_comparison.py`(468 行),同名"算法对比"功能、QPainter 柱状图 + 排名/误差/预测 Tab 高度重叠。

**U3. 算法勾选列表行构建 3 份**:`training_panel.py:472-554`、`settings_training.py:295-363`、`finetune_panel.py:115-210` 逐行相同(清空布局→QCheckBox→name→mono 字体 id→状态→stretch)。

**U4. 弹窗按屏幕缩放样板 20 处/17 文件**:`screen.geometry()` 三段式 resize 反复出现(dialog_base.py 其实已支持 `geometry=` 元组)。

**U5. 主题令牌缺失 + 硬编码色 117 处/18 文件**
- `theme.py` **从未定义 `accent_hover` 键**,导致 `detail_panel.py:123`、`main_gui_events.py:564` 等只能 `C.get('accent_hover', '#357ABD')` 永远走硬编码回退;
- `dashboard_mode.py` 自带 9 色 `_DASH_COLORS` 整体复制 THEME_DARK;`data_comparison.py` 自带 20 色 PALETTE;`milestone_stats.py`/`prediction_panel.py`/`health_probe.py` 各自为政。
- 卡片分段 4 种实现,其中 settings_general/settings_proxy 内联 QFrame 绕过公共 `make_section_widget`。

**U6. 12+ 个 QDialog 绕过 DialogBase**,手写 header/card/button_row(公共类已具备全部能力)。

**U7. 超大文件横向拆分需求**:training_panel(1513)、main_gui_events(1134)、detail_panel(952,4 个 Tab 可各自成类)。

### 3.3 核心层(core/,7K 行)

**C1. 数据库层 SQL 重复最严重** ⚠️ 最高优先
- **schema 定义 3 份**:`video_db.py:108-298`(主库)、`video_db.py:308-422`(镜像库,注释自认"相同 CREATE TABLE")、`central_backup.py:443-510`(第 3 份);
- **`videos` 表 20 列 `INSERT OR REPLACE` 出现 4 次**:`central_crud.py:62-101`(add_video)、`118-164`(sync_from_video_db)、`166-205`(sync_video_info)、`central_backup.py:160-189`;
- **镜像双写**:`save_video_info`(531-575)vs `_mirror_save_video_info`(577-623)、`add_monitor_record`(625-665)vs `_mirror_add_monitor_record`(667-705),同一 SQL 机械复制;
- **`add_prediction` 一条记录写 3 次**(video_db.py:780-846:主库+镜像+中央 sync),`add_predictions_batch`(863-947)又第 4 次;
- `cleanup_duplicate_predictions` 在 video_db.py:951 与 central_crud.py:587 双份;`_clamp_int`/`_SQLITE_INT_MAX` 双份(video_db.py:880 / central_crud.py:464);
- `models.py` 数据类字段与 SQL 列**双维护**(加列要改 4+ 处)。

**C2. `up_database.py` 绕过中央库**:直接 `sqlite3.connect(data/bilibili_monitor.db)`(L25)打开**与 CentralDB 同一个文件**,无 WAL、无锁、无连接上下文 → 并发写风险 + 第二套连接管理。

**C3. B站 API 存在 4 套并行 HTTP 路径**:
`_request`(完整管道)/ `_request_public`(简化)/ 直连 `session.get/post`(bilibili_video.py:143-179 弹幕、bilibili_auth.py:150-258 密码登录,手工拼 headers 绕过 412 重试)/ 独立 `_qr_session`。
→ `login_with_password`(bilibili_auth.py:111-320)210 行上帝函数,4 次登录尝试各嵌一段 session.post。

**C4. 弹幕双轨**:`bilibili_video.py:get_video_danmaku`(XML 旧版)与 `bilibili_danmaku.py:DanmakuMonitor`(Protobuf 新版)并存,UI 两侧各用一条路径。

**C5. 循环 import 风险**:`up_fetcher.py:17` import `core.bilibili_api`,而 `bilibili_up.py` 反向把自身传给 up_fetcher。

**C6. 其他**:`notification.py` 三职责(Windows toast + OneBot WS/HTTP + 测试)混合,硬编码默认值重复 config;`connection.py` 里躺着给封面下载用的全局 HTTP session(DB 层混网络)。

### 3.4 工具层(utils/,3K 行)

- **数字格式化 6 处**:`smart_alert._fmt_count`(29)、`report_exporter._fmt`(18)、ui/data_comparison:64、ui/dashboard_mode:33、ui/up_tracker:458、ui/trending_discovery:279;
- **`weekly_score.py` 与 `yearly_score.py` 约 90% 结构相同**(dataclass + calculate + from_dict + format);
- **`update_checker.py` 混三职责**:更新检查 + devmode 门控 + 训练开关,私有名 `_s/_hard/_train/_confirm_risky` 被 15 个 UI 文件 import;
- **重复常量**:`USER_AGENTS` 双份(bilibili_api.py:81 / proxy_manager.py:22)、`PROJECT_ROOT` 双份(utils/__init__.py:12 / config/__init__.py:16)、BV 正则 3 处(models.py:77 / cover_manager.py:28 / ui/helpers.py:234);
- **UI 越权访问私有成员**:`ui/danmaku_analysis.py` import `sentiment_analyzer._tokenize/_POSITIVE_WORDS` 等。

### 3.5 配置层被绕用(config/)

- 硬编码路径 5+ 处:`bilibili_api.py:199`(相对 `__file__` 拼 network_config.json)、`up_database.py:25`、`npu_inference.py:39`(**cwd 相对路径**)、`device.py:429`、`checkpoint_io.py:15/31`;
- `network_config.json` 被 4 种机制读写(bilibili_api / bilibili_auth / settings_window / settings_proxy);
- `helpers.py:62-66` 硬编码阈值 `[100_000, 1_000_000, 10_000_000]` 重复 config 默认值;
- `notification.py:34-39` 硬编码 OneBot 默认地址重复 config;
- `central_db._get_backup_dir`(94-104)方法内懒 import config 且 try/except 吞错。

---

## 4. 重构机会清单(优先级矩阵)

### P0 — 低风险高收益(3-4 天)

| # | 机会 | 位置 | 收益 | 风险 |
|---|---|---|---|---|
| P0-1 | **DB schema 单点化 + 镜像双写收敛** | video_db.py 全镜像方法、central_backup schema | 删 ~500 行重复;加列改 1 处 | 低(纯内部重构,SQL 语义不变) |
| P0-2 | **settings_training 复用训练循环 + 版本管理** | settings_training.py:376-701 → 抽 AsyncQueueRunner mixin | 删 ~310 行 | 低(有 training_base 权威实现可对照) |
| P0-3 | **合并双胞胎 algorithm_compare / algorithm_comparison** | ui/ 两文件 | 删 ~490 行 | 低 |
| P0-4 | **收敛 4 套 HTTP 路径** | bilibili_video.py:143、bilibili_auth.py:150 | 统一 412 重试/代理逻辑 | 中(登录/弹幕路径需回归) |
| P0-5 | 重复常量收敛 | USER_AGENTS / PROJECT_ROOT / BV 正则 / 阈值 | 4 类常量单点化 | 低 |

### P1 — 结构性重构(1-2 周,需测试保障)

| # | 机会 | 位置 | 收益 | 风险 |
|---|---|---|---|---|
| P1-1 | **`_torch_upgrade.py` 拆 4 子系统** | models/ + runtime.py + gpu_cache.py + preprocessing.py | 2146→每文件 <500 | 高(全部 39 个 DL 算法引用) |
| P1-2 | **registry.py 拆分** | 特征工程 / 并行调度 / 加权 / 训练接口 各成类 | 21 职责→5 类 | 中 |
| P1-3 | **detect_surge 拆分**(E/37) | base.py:438 → `_compute_windows` + `_classify_surge` + `_adjust_decay` | 37→3×~10 | 中(需回测数值一致) |
| P1-4 | **`_parse_result` 拆分**(D/21) | model_adapter.py:163 → 按输入格式分派 | 21→6×~5 | 中 |
| P1-5 | **theme.py 令牌补全 + 硬编码色清扫** | accent_hover 补键 + 117 处 hex 收敛 | 主题一致性 | 低-中(视觉回归) |
| P1-6 | **UI 公共组件抽取** | SettingsBaseMixin / ChecklistRowBuilder / StatusLabel / resize_ratio | 删 3 份列表构建 + 20 处样板 | 低 |
| P1-7 | **up_database 并入中央库层** | up_database.py → CentralCRUD | 消除并发双连接 | 中(数据文件同库) |

### P2 — 深度重构(2-4 周,可选)

| # | 机会 | 位置 | 收益 | 风险 |
|---|---|---|---|---|
| P2-1 | 超大 UI 面板横向拆分 | training_panel(1513)/ main_gui_events(1134)/ detail_panel(952) | 每文件 <600 | 中(布局回归) |
| P2-2 | 算法样板骨架收敛 | 52 文件手写兜底 → BaseAlgorithm 模板方法 + 装饰器 | 消 79 处重复 | **高**(136 算法行为回归) |
| P2-3 | utils 合并 | weekly/yearly_score 合并、update_checker 拆 3 职责 | 精简 | 低 |
| P2-4 | 全库路径统一走 config | 5+ 处硬编码路径 → project_path | 消除 cwd 依赖 bug | 低 |

### ❌ 不建议做

- **整体重写算法引擎** — 136 算法行为回归风险远大于收益(算法是产品核心价值);
- **换 UI 框架**(如 PySide6)— 66 个文件无收益迁移;
- **删算法** — algorithms-simplify 分支的历史教训(删 DL 与产品目标相悖)。

---

## 5. 可行性评估

### 5.1 风险清单

| 风险 | 等级 | 缓解措施 |
|---|---|---|
| 算法预测数值变化(重构引入行为差异) | **高** | 现有 `rollout_backtest.py` 回测框架锁基线,重构前后预测结果 diff |
| PyQt6 布局/样式回归 | 中 | 每面板改完跑 `ui.main_gui` 冒烟 + 截图对比 |
| SQL 变更导致数据损坏 | 中 | schema 单点化只改定义位置不改列结构;DB 文件先备份 |
| 训练管线线程行为变化 | 中 | AsyncQueueRunner 抽取后对照 training_base 原实现逐行验证 |
| 登录/弹幕请求路径回归(412) | 中 | P0-4 收敛后用真实账号冒烟 |
| 依赖再次被元数据拖垮 | 低(已治理) | `pip check` 监控 + install_uni2ts.py 文档化流程 |

### 5.2 工作量估算(单人)

| 阶段 | 内容 | 估算 |
|---|---|---|
| 阶段 0 | 依赖治理(uni2ts 解锁 + GPU torch) | ✅ 已完成 |
| 阶段 1 | P0 五项(DB/训练面板/双胞胎/HTTP/常量) | 3-4 人日 |
| 阶段 2 | P1 七项(上帝文件/registry/surge/theme/组件) | 8-12 人日 |
| 阶段 3 | P2 四项(面板拆分/算法骨架/utils/路径) | 10-15 人日 |
| 全程 | 回测 + 冒烟 + 回归 | +30% 缓冲 |

### 5.3 预期收益

- 代码量:**73K → 58-62K 行**(-15-20%),重复消除;
- 圈复杂度热点:E/F 级函数从 4 个降至 0;
- 加字段/加算法/加面板的开发成本显著下降(schema 单点 + 骨架模板);
- 消除 2 个真实 bug 隐患:up_database 同库双连接并发写、npu_inference 相对路径 cwd 依赖。

### 5.4 依赖关系

```
阶段 1(DB schema 单点) → 阶段 2 的 registry/训练重构的地基
阶段 1(AsyncQueueRunner) → 阶段 3 训练面板拆分的前提
阶段 2(theme 令牌补全) → 阶段 3 UI 硬编码清扫的前提
阶段 1(HTTP 路径收敛) → 与登录功能改动冲突,需串行
```

---

## 6. 分阶段实施路线图

```
阶段 0: 依赖治理                    [✅ 已完成, commit 8496481]
   ├─ uni2ts 2.0.0 解锁(--no-deps)      ├─ GPU torch 2.13 恢复
   └─ requirements 重写 + 双安装脚本

阶段 1: P0 快速清理(3-4 天)
   ├─ P0-1  DB schema 单点 + 镜像双写收敛
   ├─ P0-2  AsyncQueueRunner 抽取, settings_training 复用
   ├─ P0-3  合并 algorithm_compare 双胞胎
   ├─ P0-4  HTTP 请求路径收敛
   └─ P0-5  常量单点化
   ✔ 验收: pip check 干净 + 算法注册数不变 + ui.main_gui 冒烟

阶段 2: P1 结构重构(1-2 周)
   ├─ P1-1  _torch_upgrade.py 拆 4 子系统      ├─ P1-2  registry 拆分
   ├─ P1-3  detect_surge 拆分                   ├─ P1-4  _parse_result 拆分
   ├─ P1-5  theme 令牌补全 + 硬编码色清扫        ├─ P1-6  UI 公共组件
   └─ P1-7  up_database 并入中央库
   ✔ 验收: radon E/F 归零 + 回测数值 diff = 0 + 全面板截图

阶段 3: P2 深度重构(2-4 周, 可选)
   ├─ P2-1  超大面板横向拆分    ├─ P2-2  算法骨架模板化
   ├─ P2-3  utils 合并          └─ P2-4  路径统一走 config
   ✔ 验收: 同上 + 全量 136 算法回测
```

---

## 7. 结论

1. **值得重构,且应当重构**:15-20% 的重复体量 + 4 个 E/F 级复杂度函数 + 上帝文件已经拖慢开发速度(加字段改 4 处、新增算法照抄样板)。
2. **不要重写**:架构分层健康,重写的唯一收获是"代码变干净",代价是 136 算法的行为回归风险。
3. **按 P0→P1→P2 渐进推进**,每个阶段有明确验收标准;P0 阶段 3-4 天即可见效,适合作为下一次迭代的首批任务。
4. **风险可控**:核心风险(算法数值、UI 布局)都有现有工具兜底(rollout_backtest / 冒烟测试)。
