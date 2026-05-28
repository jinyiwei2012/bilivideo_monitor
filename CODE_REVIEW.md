# 代码审查报告

**项目:** B站视频监控与播放量预测系统
**审查日期:** 2026-05-28
**代码总量:** ~51,307 行 / 199 个 Python 文件

---

## 1. 架构评价

### 1.1 优点

| 维度 | 评价 |
|------|------|
| **模块化** | 清晰的3层架构 (algorithms/core/ui)，各模块职责单一、接口明确 |
| **算法自动发现** | `AlgorithmRegistry` 自动扫描 `models/` 目录，新增算法零配置注册 |
| **线程模型** | 每视频独立 Worker 线程 + 全局线程池，无共享状态竞争 |
| **懒加载** | 算法注册器 / torch / API 实例 / UI 面板均按需初始化，启动 ~0.4s |
| **异常处理** | 591 处 try/except，覆盖网络请求/数据库/算法预测等所有外部调用 |
| **数据库设计** | 按视频分库 + 中央库同步，避免单点写入瓶颈 |
| **反爬措施** | 412 重试 + 指数退避 + 代理轮换 + UA 轮换 + WBI 签名 + Cookie 持久化 |

### 1.2 可改进点

| 问题 | 位置 | 建议 |
|------|------|------|
| **`asyncio.run()` 重复创建事件循环** | `core/notification.py:_call_action_ws()` | 改为全局事件循环或使用 `asyncio.run_coroutine_threadsafe` |
| **ThreadPoolExecutor 单例退出不优雅** | `algorithms/registry.py` | `shutdown(wait=False)` 可能遗留任务，改为 `wait=True` 或注册 atexit 回调 |
| **bare except 5 处** | `utils/update_checker.py` | 至少改为 `except Exception`，避免吞 `KeyboardInterrupt` |
| **XML bomb 防护注释** | `core/bilibili_api.py` | `# nosec B314` 注释表明已知风险，建议加 `DefusedParser` |
| **torch.load 不安全反序列化** | `algorithms/training/hf_loader.py` | `weights_only=False` 加载 Lag-Llama，确认 checkpoint 来源可信 |

---

## 2. 算法模块审查 (103 种)

### 2.1 注册机制

`AlgorithmRegistry` 使用双重检查锁定 (`_init_lock`) 保证线程安全的后台预加载。采用 `ThreadPoolExecutor(max_workers=4)` 并行执行所有算法预测。

```
predict_all() 流程:
  prepare_video_data()  →  统一转换历史数据 (缓存)
  ThreadPoolExecutor    →  并行运行 103 个算法
  coherence 权重调整    →  偏离中位数越远权重越低
  加权集成             →  CV 倒数为置信度
  保形预测             →  预测区间
```

### 2.2 接口设计

`ModelAlgorithmAdapter` 自动检测算法接口类型并桥接：
- `predict(video_data, threshold)` — 现代接口 (匹配 BaseAlgorithm)
- `predict(current_views, target_views, history_data, video_info)` — 遗留接口
- 输出统一转换为 75 秒短期预测窗口

### 2.3 风险

- 当 `_torch_upgrade.py` 导入失败时，28 个深度学习算法全部回退到 numpy 预测
- `threading.Semaphore(2)` 限制并发预测数，监控视频 >2 个时预测队列可能堆积
- Prophet 导入时 `prophet.plot` 的 plotly 缺失日志已压制 (CRITICAL)

---

## 3. 核心模块审查

### 3.1 Bilibili API (`core/bilibili_api.py`)

**连接池:** `HTTPAdapter(pool_connections=10, pool_maxsize=10)` 减少 TCP 握手

**反 412 策略链:**
```
_request() 失败 → rotate UA → double min_interval → rotate proxy → disable cookies
```

**认证:**
- QR 扫码登录 (`get_qrcode_login_url` / `poll_qrcode_login`)
- 密码登录 (RSA 加密)
- Cookie 使用 XOR + `utils/crypto.py` 加密持久化

**建议:** QR 登录轮询间隔 3s 固定，可增加指数退避避免高频轮询。

### 3.2 数据库 (`core/database/`)

**3 层架构:**
```
VideoDatabase (每视频独立 SQLite)  →  按 BV 分库
    ↓ sync_from_video_db()
Database (中央库 bilibili_monitor.db)
    ↓ sync_to_central()
备份同步
```

**线程安全:** `_ConnectionCtx` 上下文管理器 + `threading.Lock()`

**Schema 迁移:** 自动检测列变更并 `ALTER TABLE`，`_schema_migrated_version` 缓存避免重复迁移

**风险:** `sync_from_video_db()` 每小时同步时持有 `_data_lock`，大量视频可能导致 UI 短暂卡顿。建议使用增量同步标记位。

### 3.3 通知 (`core/notification.py`)

**双通道:**
```
send_*
  → _call_action_ws()     (asyncio.run + websockets, 首选)
  → 失败回退 _call_action_http()  (requests, 同步)
```

**安全:** 有 Token 时拒绝明文 WS/HTTP 连接

**问题:** `asyncio.run()` 每次调用创建新事件循环，不兼容 Jupyter/某些调试器。建议在 `NotificationManager.__init__` 中创建持久化事件循环 + 后台线程。

---

## 4. UI 模块审查 (41 文件)

### 4.1 主界面 (`main_gui.py`)

**布局:** 22% 左 | 58% 中 | 20% 右 (三栏)

**导航:** 4 标签页 (监控列表/日志/模型训练/微调训练)

**全局时钟 (1s tick):**
- 倒计时徽章更新
- 每 300 tick (5min): WAL checkpoint + 异常扫描
- 每 3600 tick (1h): 数据库同步
- 每小时模型激活状态刷新

**对话框:** 17 种，通过 `Dialogs` 类统一路由，懒加载

### 4.2 Worker 模型 (`monitor_service.py`)

每个视频一个独立 `threading.Thread`:
```
_run() 循环:
  fetch_and_predict()
    → BilibiliAPI.get_video_info()
    → 写数据库 (持 _data_lock)
    → _predict_single()
    → gui.root.after(0, _on_fetch_done)
  分段睡眠 (支持中途停止)
```

**防抖:** 选中视频更新 50ms 防抖，图表更新 100ms 防抖

### 4.3 主题系统 (`theme.py`)

`C` 字典定义所有颜色 token，支持深色/浅色统一管理。当前仅使用深色主题。

---

## 5. 训练管线审查 (`algorithms/training/`)

### 5.1 组件

| 组件 | 职责 | 要点 |
|------|------|------|
| `device.py` | GPU 检测 | CUDA > DirectML > XPU > MPS > CPU，冒烟测试确保可用 |
| `dataset.py` | 数据加载 | 5 维衍生特征 + Z-score 归一化 + 滑动窗口 |
| `trainer.py` | 训练编排 | HyperbolicLR + MixUp + Label Smoothing + SPADE-S + Activation Decay |
| `checkpoint_manager.py` | 版本管理 | `v{N}_{YYYYMMDD_HHMM}.pt` + active.json |
| `hf_loader.py` | HF 模型 | MOIRAI-2 + Lag-Llama，懒加载 + 线程安全缓存 |

### 5.2 训练流程

```
train_global(algo_ids, epochs=50):
  对每个 algo_id:
    1. build_model() → nn.Module
    2. 加载数据集 (所有视频数据)
    3. 训练循环: forward → loss → backward → scheduler.step()
    4. 保存 checkpoint (含 val_loss/epochs/device/lr)

finetune_for_video(algo_id, bvid, epochs=5):
    1. 加载全局 checkpoint
    2. 加载单个视频数据
    3. 微调
    4. 保存到 _video/<BVID>/ 子目录
```

### 5.3 风险

- `torch.load(weights_only=False)` 在 `hf_loader.py` 中加载 Lag-Llama，存在 pickle 反序列化风险
- 训练时 `data_trained_until` 时间戳标记可能因时区问题导致重复训练
- 特征标准化使用 Z-score，新视频加入后旧视频标准化参数未更新

---

## 6. 异常检测审查 (`core/smart_alert.py`)

### 6.1 检测器清单 (8 种)

| 检测器 | 方法 | 自适应阈值 |
|--------|------|-----------|
| 播放飙升 | 最近增速 vs 平均增速 | 1.5x~3x 按播放量分级 |
| 增长放缓 | 近期增速 vs 前期增速 | 降至 30% 以下 |
| 播放停滞 | 近 2h 增速绝对值/相对值 | <1万用绝对值，>1万用十万分之五 |
| 在线飙升 | 最后在线 vs 之前平均 | 2.5x + 最低 30 人 |
| 在线暴跌 | 最后 vs 之前比值 | <30% + 差值 >50 |
| 深夜异常 | 夜间 vs 日间在线比 | >40% + 最低 10 人 |
| 买量检测 | 7 维评分 (0-9) | ≥3 疑似, ≥5 高度疑似 |
| 直播检测 | UP 主 live_status | =1 直播中 |

### 6.2 冷却机制

`_last_alert_time` 字典 + 30 分钟 cooldown，避免重复推送。

### 6.3 建议

- 买量检测的 7 个维度权重相同，可引入 ML 学习各维度权重
- 深夜异常使用日间均值做对比，对时区非 UTC+8 的用户不准确
- 冷却时间 30 分钟固定，可改为随异常严重程度动态调整

---

## 7. 安全审查

| 项目 | 状态 | 说明 |
|------|------|------|
| SQL 注入 | ✅ 安全 | 所有 SQL 参数化查询 |
| 路径遍历 | ✅ 安全 | BV 号正则 `^BV[A-Za-z0-9]{10,12}$` 校验 |
| Cookie 加密 | ✅ 已实现 | XOR + base64 编码 |
| 反序列化 | ⚠️ 低风险 | `torch.load(weights_only=False)` 在 hf_loader.py |
| XML 注入 | ⚠️ 已注释 | `# nosec B314` 在 bilibili_api.py |
| 文件权限 | ⚠️ 宽松 | `os.chmod(..., 0o666)` 在数据迁移中 |

---

## 8. 性能评估

| 场景 | 耗时 | 说明 |
|------|------|------|
| 模块导入 | ~0.4s | 懒加载后从 ~10.5s 优化至此 |
| 算法全量扫描 | ~5-6s | 后台线程，不阻塞 UI |
| 首次 API 初始化 | ~1.5-2s | 懒加载，首次 API 调用时 |
| torch 导入 | ~1-3s | 按需，仅训练/深度学习算法使用时 |
| 单次预测 (103 算法) | ~3-8s | 4 线程池并行 |
| 数据库每小时同步 | ~1-5s | 后台线程 |
| 异常全量扫描 | ~2-5s | 每 5 分钟后台执行 |

---

## 9. 测试覆盖

| 文件 | 内容 | 行数 |
|------|------|------|
| `tests/test_models.py` | 算法模型测试 | — |
| `tests/test_base_algorithm.py` | 基类测试 | — |
| `tests/test_weight_manager.py` | 权重管理测试 | — |

**建议:** 测试覆盖不足，核心路径（API 调用/数据库 CRUD/UI 回调）缺少测试。推荐至少增加：
- API mock 测试 (412 重试、代理切换)
- 数据库单元测试（分库创建、同步）
- UI 面板初始化测试（确保懒加载无报错）

---

## 10. 改进建议优先级

### ✅ 已修复 (2026-05-28, fixbug branch)

| 问题 | 状态 | commit |
|------|------|--------|
| `hf_loader.py` torch.load unsafe 回退 | ✅ resolved | `6a2013f` |
| `_merged_from_db` 多线程数据竞争 | ✅ resolved | `5474715` |
| 数据库写入静默失败 (video_db/central_db) | ✅ resolved | `7f1ab62` |
| 29 处 `except Exception: pass` 加日志 | ✅ resolved | `d437fa7` |
| XXE 漏洞 (xml.etree → defusedxml) | ✅ resolved | `0cf2b74` |
| checkpoint_manager 路径穿越 | ✅ resolved | `9cf1606` |
| `update_checker.py` bare except | ✅ resolved | `b63a0b8` |
| `_last_alert_time` 字典无锁 | ✅ resolved | `3ad5ffd` |
| 训练取消时文件句柄泄漏 | ✅ resolved | `7561473` |
| 数据库文件权限 0o666→0o600 | ✅ resolved | `7f1ab62` |
| cover_manager bvid 路径校验 | ✅ resolved | `4e90012` |
| git pull 分支名注入 | ✅ resolved | `4e90012` |
| AIQASession 类级竞争 | ✅ resolved | `4e90012` |

### P1 (建议短期优化)
- 增加 API mock 测试
- 数据库每小时同步改为增量标记位，避免全量扫描
- 买量检测权重可配置化
- `asyncio.run()` 重复创建事件循环 → 改为持久化事件循环

### P2 (建议中长期规划)
- `registry.py` 退出时 `pool.shutdown(wait=False)` → 改为 `wait=True`
- 主题系统恢复动态切换（浅色/深色）
- 插件系统允许第三方算法热加载
- Web 管理界面辅助查看
- 分布式监控避免单 IP 限流
