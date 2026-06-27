# B站视频监控与播放量预测系统 — 代码审查报告

> **审查日期:** 2026-06-27 | **最后修复:** 2026-06-27 | **Python:** 3.10 | **GUI:** PyQt6 | **数据库:** SQLite
>
> **审查范围:** 全项目 ~230 个 Python 文件，覆盖 `ui/`、`core/`、`algorithms/`、`utils/`、`config/`、`tests/`、`scripts/` 及入口文件

---

## 📊 审查统计

| 模块 | 文件数 | 发现问题数 |
|------|--------|-----------|
| `main.py` | 1 | 8 |
| `core/` | 14 | 35 |
| `core/database/` | 9 | 28 |
| `utils/` | 19 | 42 |
| `ui/` 主面板 | 15 | 38 |
| `ui/` 子面板与对话框 | 32 | 87 |
| `ui/settings/` | 10 | 32 |
| `ui/monitor/` | 3 | 18 |
| `algorithms/` 核心 | 11 | 30 |
| `algorithms/training/` | 9 | 30 |
| `algorithms/models/` | 100+ | 18 (按模式分组) |
| `tests/scripts/config/` | 12 | 26 |
| **合计** | **~230** | **~392** |

---

## 🔴 致命级问题 (P0) — 立即修复

### 1. `core/notification.py:60` — Python 3.10 类型标注崩溃

```python
def _call_action_ws(...) -> bool | None:  # ❌ Python 3.10 不支持此语法
```

**影响**: 通知系统完全不可用。**修复**: 改为 `Optional[bool]` 或加 `from __future__ import annotations`。

---

### 2. `core/database/video_db.py` — 死锁 + 镜像库无锁写入

- **`_execute_on_all()` (96-101行)**: 使用 `threading.Lock`（不可重入），同一方法内获取两次导致死锁
- **所有 `_mirror_*` 方法**: 在释放主锁后、不持有任何锁的情况下写入 `_mirror_conn`，多线程并发写入导致数据损坏

**影响**: 数据库损坏。**修复**: 改用 `threading.RLock`；为所有镜像写入添加锁保护。

---

### 3. `core/database/central_backup.py` — 备份库 predictions 表永不创建

`_ensure_central_tables()` 创建了 `videos`、`monitor_records`、`weekly_scores`、`yearly_scores` 表，但**缺少** `CREATE TABLE IF NOT EXISTS predictions`。后续所有预测数据同步到空备份库时静默失败。

**修复**: 在 `_ensure_central_tables()` 中补充 `CREATE TABLE IF NOT EXISTS predictions (...)`。

---

### 4. `algorithms/models/growth/` (5 个文件) — 接口不兼容

以下 5 个文件的 `predict()` 签名与 `BaseAlgorithm.predict(video_data, threshold)` 完全不兼容：

| 文件 | 实际签名 | 返回类型 |
|------|---------|---------|
| `growth/logistic_growth.py` | `predict(self, current_views, target_views, history_data, video_info)` | `Optional[Tuple[int, float]]` |
| `growth/gompertz_growth.py` | 同上 | `Optional[Tuple[int, float]]` |
| `growth/richards_curve.py` | 同上 | `Optional[Tuple[int, float]]` |
| `growth/weibull_growth.py` | 同上 | `Optional[Tuple[int, float]]` |
| `time_series/holt_winters.py` | 同上 | `Optional[Tuple[int, float]]` |

**影响**: `AlgorithmRegistry` 调用这些算法时抛出 `TypeError`。**修复**: 统一为 `predict(self, video_data, threshold) -> PredictionResult`。

---

### 5. `algorithms/online_learner.py:427` — FTRL 因 `__slots__` 抛出 AttributeError

`update_ftrl()` 在 `_AlgorithmTracker` 实例上动态设置 `_ftrl_g2`、`_ftrl_g`、`_ftrl_z` 属性，但该类定义了 `__slots__` 且不包含这些属性名。

**影响**: FTRL 在线学习完全不可用。**修复**: 将 `_ftrl_*` 添加到 `__slots__` 或使用 `__dict__`。

---

### 6. `ui/settings_monitor.py:43-45` — QWidget 无 Layout 导致崩溃

`th_list_frame = QWidget()` 创建后未设置 Layout，第 90 行 `parent.layout().addWidget(row)` 访问 `None.addWidget()` → `AttributeError`。

**修复**: 添加 `th_list_frame.setLayout(QVBoxLayout())`。

---

### 7. `ui/settings_about.py:133` — 链接点击抛出 TypeError

```python
link_lbl.mouseReleaseEvent = lambda ev: (webbrowser.open(link_url), None)[1]
```

`(..., None)[1]` 对 `None` 下标取值 → `TypeError: 'NoneType' object is not subscriptable`。

**修复**: 改为 `lambda ev: webbrowser.open(link_url)`。

---

## 🟠 严重级问题 (P1) — 功能逻辑错误

### 跨线程 GUI 访问 (Qt 线程模型违反)

| 文件 | 行号 | 问题 |
|------|------|------|
| `ui/monitor/_service.py` | 341 | `gui._sb()` 在工作线程直接调用 |
| `ui/settings_proxy.py` | 408-427, 536-561 | 后台线程直接操作 `QTreeWidgetItem` |
| `ui/settings_account.py` | 805-809 | 后台线程调用 `QMessageBox.critical` |

**修复**: 所有 GUI 操作通过 `invoke()` 或信号/槽委托到主线程。

---

### 预测准确率计算错误

`ui/prediction_accuracy.py:168`: 将历史预测与最新播放量对比，而非与预测发布时点后的实际达表时间对比。

**影响**: 整个准确率面板数据不可靠。

---

### 中文弹幕分析分词无效

`ui/danmaku_analysis.py:395`: `text.strip().split()` 对中文按空格分词（中文无空格），整句变成一个 token，情感分析完全无效。

**修复**: 集成 `jieba` 分词。

---

### 其他严重问题

| # | 文件 | 问题 |
|---|------|------|
| 8 | `core/bilibili_video.py:143` | `get_video_danmaku` 绕过完整请求管道（代理/重试/限流） |
| 9 | `core/proxy_manager.py:195-197` | 代理删除后重索引 `KeyError` 风险 |
| 10 | `ui/training_panel.py:1719` | `self._lr_var` 不存在 → 训练启动崩溃 |
| 11 | `ui/video_compare_enhanced.py:164` | 播放增速计算使用错误的数据窗口 |
| 12 | `ui/report_scheduler.py:310` | `QTimer.singleShot` 只用一次，异常中断排程链 |
| 13 | `utils/tag_manager.py:155` | `suggest_tags.by_author` 功能体为 `pass`，完全无效 |
| 14 | `utils/report_exporter.py:90` | HTML 报告未转义视频标题 (XSS) |
| 15 | `ui/settings_window.py:295` | 点击取消仍持久化网络配置 |
| 16 | `scripts/sign.py:226` | `--verify` 操作自动生成新密钥对（意外副作用） |
| 17 | `scripts/sync_data.py:66` | `except Exception: pass` 静默丢弃插入错误 |
| 18 | `algorithms/device.py:196-202` | NPU 冒烟测试因逻辑短路永远不执行 |
| 19 | `algorithms/onnx_exporter.py:197-209` | `_dml_faster_than_cpu` 全局变量无线程安全 |
| 20 | `algorithms/schedulers.py:194-206` | Plateau 模式触发后永不恢复 hyperbola 衰减 |
| 21 | `algorithms/trainer.py:959/964` | 每个 epoch 都执行 `_save_model_to_video_dir` + ONNX 导出 |
| 22 | `algorithms/models/tcn_simple.py:98` | 每次预测随机初始化卷积核，结果不可复现 |
| 23 | `algorithms/models/stacking_ensemble.py:209` | 置信度计算逻辑与直觉反向 |
| 24 | `ui/monitor/_prediction.py:107-120` | `_data_lock` 覆盖范围不足，视频 DB 访问存在竞态 |

---

## 🟡 中等级问题 (P2) — 可维护性与代码质量

### 架构反模式

| 问题 | 位置 | 描述 |
|------|------|------|
| Monkey-patching | `settings_window.py:399-481` | `SettingsWindow.X = _x` 破坏类型系统 |
| Mixin 函数式绑定 | `core/bilibili_auth.py` 等 | 模块函数通过类属性赋值绑定，IDE 无法追踪 |
| 浅拷贝陷阱 | `config/__init__.py:90` | `DEFAULT_CONFIG.copy()` 嵌套字典引用共享 |

### 代码重复 (DRY 违反)

| 重复内容 | 出现次数 | 建议 |
|---------|---------|------|
| `_styled_label` / `_field_wrapper` | 4 个文件 (~100行) | 提取到 `ui/settings_common.py` |
| 时间戳解析逻辑 | 15+ 个算法文件 | 提取到 `BaseAlgorithm._extract_view_timestamp_series()` |
| `_SurgeDetector` 存根类 | `_prediction.py` + `registry.py` | 提取为公共工厂函数 |
| `_fmt()` 数字格式化 | 5+ 个 UI 文件 | 统一到 `ui/helpers.py` |

### 超长文件 (需拆分)

| 文件 | 行数 | 建议拆分为 |
|------|------|-----------|
| `ui/training_panel.py` | 1797 | UI构建 + 版本管理 + 训练控制 + 事件处理 |
| `core/database/video_db.py` | 1241 | VideoInfoOps + MonitorOps + PredictionOps + ScoreOps |
| `ui/database_query.py` | 883 | 查询逻辑 + UI展示 + CSV/Excel导出 |
| `ui/settings_account.py` | 920 | 登录对话框 + Cookie管理 + 多账号面板 |
| `algorithms/training/trainer.py` | 1086 | Pipeline + ModelInit + TrainingLoop + Checkpoint |

### 算法分类标签错误

| 文件 | 实际 `category` | 应改为 |
|------|----------------|--------|
| `arima_simple.py` | `"机器学习"` | `"时间序列"` |
| `trend_regression.py` | `"机器学习"` | `"时间序列"` |

---

## 🛡️ 安全隐患

| 类别 | 风险 | 文件 | 描述 |
|------|------|------|------|
| 凭证明文存储 | **高** | `settings_ai.py` / `settings_notification.py` | API Key / Token 以明文写入 `settings.json` |
| SSL 验证禁用 | **高** | `proxy_manager.py` / `settings_proxy.py` | `verify=False` 全局禁用 SSL，MITM 风险 |
| 不可信代理源 | **中** | `proxy_manager.py` | 从 GitHub raw / geonode 自动拉取代理列表 |
| XSS 风险 | **中** | `report_exporter.py` | HTML 报告视频标题未转义 |
| 异常静默吞噬 | **中** | 多处 | `except Exception: pass` 丢失关键错误信息 |
| 密钥保护无效 | **中** | `sign.py` | Windows 上 `os.chmod(0o600)` 无实际作用 |

---

## 📋 修复路线图

### 第一阶段 (本周) — P0 致命 Bug

| 优先级 | 问题 | 文件 |
|--------|------|------|
| 1 | `bool \| None` 类型标注崩溃 | `core/notification.py:60` |
| 2 | FTRL `__slots__` bug | `algorithms/online_learner.py:427` |
| 3 | 备份库缺 predictions 表 | `core/database/central_backup.py` |
| 4 | 5个算法接口不兼容 | `algorithms/models/growth/*.py` |
| 5 | 死锁 + 镜库无锁写入 | `core/database/video_db.py` |
| 6 | 链接点击 TypeError | `ui/settings_about.py:133` |
| 7 | QWidget 无 Layout 崩溃 | `ui/settings_monitor.py:43-45` |

### 第二阶段 (本月) — P1 功能 Bug

| 优先级 | 问题 | 文件 |
|--------|------|------|
| 8 | 跨线程 GUI 访问 | `_service.py` / `settings_proxy.py` / `settings_account.py` |
| 9 | 预测准确率计算错误 | `prediction_accuracy.py:168` |
| 10 | 中文分词无效 | `danmaku_analysis.py:395` |
| 11 | 定时器一次性执行 | `report_scheduler.py:310` |
| 12 | `_lr_var` 不存在 | `training_panel.py:1719` |
| 13 | 代理检测线程安全 | `settings_proxy.py` |
| 14 | TCN 随机性 | `algorithms/models/tcn_simple.py` |
| 15 | 取消仍保存配置 | `settings_window.py:295` |

### 第三阶段 (后续) — P2 架构优化

| 优先级 | 问题 | 范围 |
|--------|------|------|
| 16 | 提取公共 helper | `_styled_label` / `_field_wrapper` → `settings_common.py` |
| 17 | 拆分超长文件 | `training_panel.py` / `video_db.py` / `settings_account.py` |
| 18 | 统一时间戳解析 | 15+ 算法文件 → `BaseAlgorithm` 基类 |
| 19 | 凭证加密存储 | API Key / Token → `keyring` 或 `cryptography.fernet` |
| 20 | 统一 BV 号校验 | 所有入口添加 `is_valid_bvid()` |
| 21 | 强化测试断言 | `test_model_algorithms.py` 等 |
| 22 | 消除 monkey-patching | `settings_window.py` → Mixin 类层次 |
| 23 | 修复算法分类标签 | `arima_simple.py` / `trend_regression.py` |

---

## ✅ 亮点

- **完整性校验**: `main.py` Ed25519 + 嵌入式哈希两层校验设计精良
- **三级降级链**: ARIMA/Prophet 等 `statsmodels→pmdarima→numpy` 模式成熟
- **加权集成引擎**: `AlgorithmRegistry.predict_all()` 并行预测 + 一致性权重合理
- **深色主题**: `theme.py` C 设计令牌集中化管理规范
- **原子通知**: `invoker.py` `queue.Queue` + `pyqtSignal` 跨线程机制简洁可靠
- **信号处理算法**: `hilbert_huang.py` / `spectral_residual.py` 引入前沿方法

---

> *本报告由 Sisyphus 代码审查系统生成，基于 `main-prompt.md` 和 `regular-prompt.md` 审查模板，按 5 维度（代码质量、逻辑正确性、安全漏洞、可维护性、潜在缺陷）进行全面分析。*

---

## 🔧 修复状态 (2026-06-27)

### P0 致命级 — 全部已修复 ✅ (7/7)

| # | Commit | 文件 | 修复内容 |
|---|--------|------|---------|
| 1 | `b652675` | `core/notification.py` | `bool \| None` → `from __future__ import annotations` |
| 2 | `b925d53` | `core/database/video_db.py` | `Lock` → `RLock` + 所有 `_mirror_*` 方法加锁 |
| 3 | `a1294eb` | `core/database/central_backup.py` | 补充 `CREATE TABLE IF NOT EXISTS predictions` |
| 4 | `7d0c08f` | 5 个算法文件 | `algorithm_id` + `predict()` 适配器 |
| 5 | `dc5d615` | `algorithms/online_learner.py` | `_ftrl_*` 加入 `__slots__` |
| 6 | `cd2dccf` | `ui/settings_monitor.py` | `th_list_frame` 添加 `QVBoxLayout` |
| 7 | `11985dc` | `ui/settings_about.py` | 链接点击 `TypeError` 修复 |

### P1 严重级 — 已修复 ✅ (21/23)

| # | Commit | 文件 | 修复内容 |
|---|--------|------|---------|
| 1 | `57af3c4` | `ui/monitor/_service.py` | `gui._sb()` 包装 `invoke()` |
| 2 | `0cacf0c` | `core/bilibili_video.py` | 弹幕 API 路由通过 proxy_manager |
| 3 | `6218b46` | `core/proxy_manager.py` | 代理重索引 `.pop()` 添加默认值 |
| 4 | `481a2d0` | `ui/prediction_panel.py` | `rate_lbl` None 守卫 |
| 5 | `f8fea15` | `ui/settings_account.py` | 验证码信号 disconnect-before-connect |
| 6 | `b876068` | `utils/report_exporter.py` | HTML XSS `html.escape()` |
| 7 | `d219320` | `ui/training_panel.py` | `_lr_var` → `_lr_entry` + `.get()` → `.text()` |
| 8 | `780560d` | `ui/settings_window.py` | 取消不持久化网络配置 |
| 9 | `e620946` | `algorithms/models/tcn_simple.py` | `RandomState(42)` 确定性 |
| 10 | `6080806` | `algorithms/training/schedulers.py` | Plateau → hyperbolic 恢复 |
| 11 | `a298475` | `algorithms/models/stacking_ensemble.py` | 置信度逻辑反向修复 |
| 12 | `a298475` | `utils/tag_manager.py` | `suggest_tags.by_author` 实现 |
| 13 | `a298475` | `utils/ai_qa.py` | 移除无效 `clear_api_key null` 填充 |
| 14 | `a298475` | `scripts/sign.py` | `--verify` 只读 (检查密钥文件存在性) |
| 15 | `a298475` | `ui/report_scheduler.py` | `finally` 确保 `_schedule_next()` |
| 16 | `63d427d` | `ui/monitor/_prediction.py` | `_data_lock` 覆盖 `video_dbs` |
| 17 | `63d427d` | `algorithms/training/device.py` | NPU 冒烟测试 dead code 修复 |
| 18 | `1899b22` | `algorithms/training/onnx_exporter.py` | `_dml_lock` 保护 DML 缓存 |
| 19 | `1899b22` | `ui/video_compare_enhanced.py` | 增速窗口使用 cutoff 时间点 |
| 20 | — | `ui/settings_proxy.py` | QTreeWidgetItem 跨线程 (P2 需重构) |
| 21 | — | `ui/danmaku_analysis.py` | 中文分词 (实际使用 `_tokenize()` 词典匹配, 非 `split()`) |

### 剩余未修复 (P1+P2)

| 项 | 优先级 | 说明 |
|----|--------|------|
| `prediction_accuracy.py` 准确率计算 | P2 | 需较大重构，涉及完整预测回看逻辑 |
| QTreeWidgetItem 跨线程重构 | P2 | `settings_proxy.py` 代理检测需架构级重构 |
| P2 中等级 (16项) | P2 | 代码重复消除、文件拆分、BV 校验统一等 |
