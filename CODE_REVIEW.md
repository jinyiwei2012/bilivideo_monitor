# 代码审查报告

> 审查日期：2026-05-07
> 扫描范围：23,544 行 Python 代码（core/、ui/、algorithms/）
> 审查工具：flake8, bandit, radon, 人工审查

---

## 目录

- [严重 Bug](#严重-bug)
- [性能瓶颈](#性能瓶颈)
- [线程安全问题](#线程安全问题)
- [资源泄漏](#资源泄漏)
- [数据库膨胀](#数据库膨胀)
- [代码复杂度](#代码复杂度)
- [综合建议](#综合建议)

---

## 严重 Bug

### B1. `video_db.py:408` — 异常处理引用未定义变量

```python
# core/database/video_db.py
def add_prediction(self, prediction: PredictionRecord) -> bool:
    try:
        ...
    except Exception as e:
        logger.warning("添加预测记录失败 %s: %s", record.bvid, e)  # ← record 未定义
        return False
```

方法参数是 `prediction`，但 exception handler 里引用了 `record.bvid`。写入失败时抛出 `NameError: name 'record' is not defined`，掩盖真实错误。已有 `# noqa: F821` 注释但未修复。

**影响**：预测记录写入失败时无法正确记录日志，排查问题困难。

---

### B2. `bilibili_api.py:645` — 调用了不存在的方法

```python
# core/bilibili_api.py
def get_video_comments(self, ...):
    ...
    self._apply_request_interval()  # ← 该方法从未定义
```

调用 `get_video_comments` 会引发 `AttributeError`，导致评论拉取功能完全不可用。预期应调用的是 `_ensure_min_interval()`。

**影响**：获取视频评论功能必定报错。

---

### B3. `monitor_service.py:161-162` — 在线学习反馈使用错误数据

```python
def _online_learning_feedback(gui, bvid, results, actual_view):
    prev = gui.prediction_results.get(bvid)
    if prev and actual_view > 0:
        learner = get_online_learner()
        learner.update(bvid + "/_weighted", predicted=prev["prediction"], actual=actual_view)
```

用 **前一次** 刷新周期的预测值与 **当前值** 比较。如果两次刷新间播放量无变化，学习器会记录 100% 准确率，人为抬高高频算法权重，使系统对真实变化响应变慢。

---

### B4. `registry.py:198-202` — `weight_manager` 未做 None 检查

```python
class AlgorithmRegistry:
    @classmethod
    def update_accuracy(cls, ...):
        ...
        weight_manager.update_accuracy(algorithm_name, accuracy)  # ← weight_manager 可能为 None
```

文件顶部 `weight_manager` 导入失败时设为 `None`，但 `update_accuracy` 和 `get_weights_info` 未做检查（`predict_all` 已正确处理了此情况）。

---

## 性能瓶颈

### P1. 数据库写入风暴（最高优先级）

**每次刷新周期**对每个视频执行：

| 写入类型 | 每次刷新建行数 |
|---------|--------------|
| `monitor_records` | 1 行 |
| `predictions` | 55 算法 × 4 阈值 = **220 行** |
| `weekly_scores` | 1 行 |
| `yearly_scores` | 1 行 |

**10 个视频 × 75 秒间隔的日增量**：

| 表 | 日增量 |
|---|-------|
| predictions | ~253 万行 |
| monitor_records | ~11,520 行 |
| weekly/yearly | ~23,040 行 |

**建议**：
- 预测结果仅在有显著变化时写入（差值 > 5%）
- 用 `executemany` + 单次事务替代逐行 INSERT
- 周/年分数改为小时级去重

---

### P2. `_request_public` 每次创建新 Session

```python
def _request_public(self, ...):
    public_session = _req.Session()  # ← 每次调用新建
    ...
    # 无 public_session.close()
```

每次公共 API 请求新建独立 Session，无法复用 TCP 连接。高频调用时浪费大量握手开销。应复用实例级 session 或使用模块级共享 session。

---

### P3. 封面缓存 FIFO 淘汰

```python
# ui/video_list_panel.py
if len(self._cover_cache) > 50:
    self._cover_cache.pop(next(iter(self._cover_cache)))  # ← FIFO
```

FIFO 淘汰策略：频繁访问的老封面会被新封面踢出，导致反复网络下载。建议改用 `OrderedDict` 实现 LRU。

---

### P4. 每 tick 完整重绘图表

`monitor_service.py:430` 每个 Worker 刷新完成后，若视频被选中且在图表页，完整重绘画布。数据点未变化时纯属浪费。

**建议**：仅在数据点数量或最新值变化时才重绘，或使用增量绘制。

---

### P5. `_merge_history` 每次刷新全量加载 DB

`get_all_records()` 不带 limit，加载全部历史数据。运行数月的视频可能有数万行。建议限制最近 500 条。

---

### P6. WeightManager 每次更新都重算 + 写磁盘

`update_accuracy` 在持锁状态下执行全部算法重算 + JSON 文件写入，55 个算法并发更新时锁竞争严重。

---

## 线程安全问题

### T1. `registry.py:155` — ThreadPoolExecutor 竞态

```python
if not hasattr(cls, "_pool") or cls._pool is None:
    cls._pool = ThreadPoolExecutor(max_workers=4)
```

无锁双重检查。多个线程同时进入 `predict_all` 可能创建多个池子，旧池子变孤儿线程。应加锁或类定义时立即创建。

### T2. `monitor_service.py:329-338` — 共享 video dict 无保护写入

Worker 线程直接修改 `gui.monitored_videos` 列表中的共享 dict 字段（view_count、like_count 等），主线程同时读取。虽 GIL 保护单字段原子性，但无顺序保证。

### T3. `weight_manager.py:94-107` — 持锁做文件 I/O

`update_accuracy` 持有锁时调用 `_save_weights()`（JSON 写入）。文件系统阻塞时全部算法等待。

### T4. `proxy_manager.py:166-171` — 失败代理移除非原子操作

`on_request_failure` 中 `proxies.pop()` 后手动重新索引 `_proxy_ua_map` 和 `_proxy_failure_count`，多线程并发时竞态。

---

## 资源泄漏

### R1. `central_db.py:194` — SQLite 连接泄漏

```python
def sync_from_video_db(bvid):
    video_db = VideoDatabase(bvid, self.data_dir)  # 每次打开新连接
    ...
    return True  # ← video_db.close() 从未调用
```

每次视频刷新触发中央 DB 同步时创建新的 `VideoDatabase` 实例（含新 SQLite 连接），从不关闭。10 视频 × 1152 次/天 = 11,520 次连接泄漏/天。

### R2. `bilibili_api.py:316` — Session 泄漏

`_request_public` 和 `get_qrcode_login_url` 创建 `requests.Session` 后不关闭，连接池 TCP 连接等 GC 回收。

---

## 数据库膨胀

### D1. Predictions 表无保留策略

55 算法 × 4 阈值 × 每天 1152 次刷新 = 每个视频每天 ~25 万行。无 TTL 或行数上限。

**建议**：保留最近 7 天，或按 `created_at` 限制 10 万行。

### D2. Weekly/Yearly 分数无去重

每次刷新都插入新行。建议改为每小时最多一条。

### D3. 中央 DB 全量同步

`sync_from_video_db` 每次读取视频 DB 的全部历史记录（`SELECT *`）再 `INSERT OR IGNORE`。大量行被反复读取但跳过。限制为仅同步最近 N 条。

---

## 代码复杂度

### 最高复杂度排名

| 排名 | 函数 | 文件 | CC 分数 |
|------|------|------|---------|
| 1 | `ProxyManager.test_proxy` | `core/proxy_manager.py` | **38** |
| 2 | `MilestoneStatsWindow._redraw_compare` | `ui/milestone_stats.py` | **27** |
| 3 | `SnapshotTab._quick_filter` | `ui/snapshot_tab.py` | **22** |
| 4 | `TrendTab._collect_data` | `ui/trend_tab.py` | **22** |
| 5 | `DanmakuAnalysisWindow._analyze` | `ui/danmaku_analysis.py` | **20** |

`test_proxy`（CC=38）是代码库中复杂度最高的函数，包含多层嵌套的代理错误处理逻辑，需要重构拆分为多个小函数。

### 最大文件

| 行数 | 文件 |
|------|------|
| 1383 | `ui/settings_window.py` |
| 908 | `ui/snapshot_tab.py` |
| 890 | `ui/main_gui.py` |
| 853 | `core/bilibili_api.py` |

### Lint 状态

- **flake8**: 0 error（core/ + ui/ + algorithms/）
- **bandit**: 0 medium/high severity issue
- **bare except**: 0（全部使用 `except Exception`）

---

## 综合建议

### 立即修复（高优先级）

| # | 问题 | 文件 | 预计工作量 |
|---|------|------|-----------|
| 1 | `record.bvid` → `prediction.bvid` | `video_db.py:408` | 1 行 |
| 2 | `_apply_request_interval` → `_ensure_min_interval` | `bilibili_api.py:645` | 1 行 |
| 3 | Predictions 写入限流（差值 > 5% 才写） | `monitor_service.py` | 半天 |

### 建议修复（中优先级）

| # | 问题 | 预计工作量 |
|---|------|-----------|
| 4 | `_request_public` 复用 Session | 2 小时 |
| 5 | `registry.py` ThreadPoolExecutor 加锁 | 1 小时 |
| 6 | `central_db.py` SQLite 连接泄漏 | 2 小时 |
| 7 | 封面缓存 LRU 替换 | 1 小时 |
| 8 | Weekly/Yearly 分数去重 | 2 小时 |

### 低优先级/重构

| # | 问题 | 预计工作量 |
|---|------|-----------|
| 9 | `test_proxy` 拆分为小函数 | 半天 |
| 10 | 图表增量绘制 | 半天 |
| 11 | Predictions 表 TTL 清理 | 2 小时 |
| 12 | `_merge_history` limit 限制 | 1 小时 |

---

*报告由自动化工具扫描 + 人工审查完成。部分低严重性问题因篇幅限制未全部列出。*
