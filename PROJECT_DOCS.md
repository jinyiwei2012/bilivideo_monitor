# B站视频监控与播放量预测系统 - 项目文档

> 本文档详细说明项目中每个文件的功能、类、函数及设计决策。

---

## 目录结构总览

```
b站监控/
├── main.py                     # 主入口
├── run.py                      # 启动脚本（环境检查+依赖安装）
├── requirements.txt             # Python 依赖清单
│
├── algorithms/                 # 预测算法模块（40+算法）
│   ├── __init__.py
│   ├── base.py                 # BaseAlgorithm 抽象基类
│   ├── manager.py              # AlgorithmManager（单例模式）
│   ├── registry.py             # AlgorithmRegistry（算法注册与批量预测）
│   ├── weight_manager.py       # WeightManager（ML权重自动调整）
│   ├── model_adapter.py        # ModelAlgorithmAdapter（算法接口适配器）
│   ├── ALGORITHMS.md          # 算法详细文档
│   └── models/                 # 40个算法实现
│       ├── linear_velocity.py, exponential_decay.py, logarithmic_growth.py...
│       ├── neural_network_simple.py, lstm_simple.py, svr_predictor.py...
│       ├── gompertz_growth.py, logistic_growth.py, richards_curve.py...
│       └── viral_potential.py, quality_score.py, engagement_rate.py...
│
├── config/                     # 配置模块
│
├── core/                       # 核心业务模块
│   ├── __init__.py
│   ├── database.py             # SQLite 数据库操作（VideoDatabase + Database）
│   ├── bilibili_api.py         # B站 API 封装（重试、代理、UA轮换）
│   └── notification.py         # 通知管理器（Windows通知 + QQ Bot）
│
├── ui/                         # Tkinter GUI 模块
│   ├── __init__.py
│   ├── main_gui.py            # 主界面（~1640行，三栏布局控制器）
│   ├── theme.py               # 主题系统（设计令牌 C 字典，深/浅色切换）
│   ├── helpers.py             # 界面工具（字体、阈值常量、格式化、圆角矩形）
│   ├── chart.py               # Canvas 图表绘制（趋势折线图）
│   ├── log_panel.py           # 日志面板（多级别过滤+文件日志）
│   ├── monitor_service.py     # 业务逻辑（数据拉取、预测、per-video独立定时器）
│   ├── settings_window.py     # 系统设置
│   ├── video_search.py        # 视频搜索
│   ├── crossover_analysis.py  # 交叉计算
│   ├── data_comparison.py    # 数据对比（趋势图+快照柱状图+数据录入）
│   ├── milestone_stats.py     # 里程碑统计（投稿1周/月/年数据）
│   ├── database_query.py      # 数据库查询（Treeview分页）
│   ├── weight_settings.py     # 权重设置
│   ├── network_settings.py    # 网络设置
│   └── weekly_score.py       # 周刊评分
│
├── utils/                     # 工具模块
│   ├── __init__.py
│   ├── helpers.py             # 通用工具函数（格式化、解析等）
│   ├── exporters.py           # 数据导出（CSV/JSON）
│   ├── file_logger.py         # 文件日志（按天分文件，跨天自动切换）
│   ├── weekly_score.py        # 周刊评分算法
│   └── yearly_score.py        # 年刊评分算法
│
└── data/                      # 运行时数据
    ├── settings.json          # 监控列表与配置
    ├── bilibili_monitor.db   # 总数据库
    ├── <BV号>/               # 每视频独立数据库
    ├── cover/                # 封面缓存
    ├── exports/               # 导出文件
    └── log/                  # 日志文件
```

---

## 一、入口文件

### `main.py`
**功能**：主入口，直接启动GUI
**关键点**：
- 添加项目根目录到 `sys.path`
- 导入 `ui.main` 并调用 `main()`

### `run.py`
**功能**：conda环境检查 + 依赖安装 + 启动
**关键点**：
- 检测Python路径是否包含 `bilibili` 环境名
- 提示用户激活conda环境或使用 `conda run -n bilibili python run.py`
- 自动执行 `pip install -r requirements.txt`

---

## 二、核心模块（core/）

### `core/database.py`
**核心类**：
| 类名 | 职责 |
|------|------|
| `_ConnectionCtx` | 线程安全的数据库连接上下文管理器（`__enter__`获取锁，`__exit__`自动commit+释放） |
| `VideoDatabase` | 单个视频的独立数据库（`data/<bvid>/<bvid>.db`） |
| `Database` | 总数据库管理类（`data/bilibili_monitor.db`），同步所有视频库 |

**数据结构**（DataClasses）：
- `VideoInfo` - 视频信息
- `MonitorRecord` - 监控记录
- `PredictionRecord` - 预测记录

**数据库表**：
- `video_info` / `videos` - 视频基本信息
- `monitor_records` - 时序监控记录
- `predictions` - 预测历史
- `weekly_scores` / `yearly_scores` - 周刊/年刊分数
- `video_milestones` - 里程碑数据（bvid+period UNIQUE）

**设计亮点**：
- `VideoDatabase` 和 `Database` 都用 `threading.Lock` + `_ConnectionCtx` 实现线程安全
- `with self._get_connection()` 语法兼容，自动获取锁/commit/释放
- 每视频独立数据库，避免单文件过大

---

### `core/bilibili_api.py`
**核心类**：`BilibiliAPI`

**API端点**：
```python
SEARCH_URL  = "https://api.bilibili.com/x/web-interface/search/type"
VIDEO_URL   = "https://api.bilibili.com/x/web-interface/view"
STAT_URL    = "https://api.bilibili.com/x/web-interface/stat"
VIEWERS_URL = "https://api.bilibili.com/x/player/online/total"
```

**核心方法**：
| 方法 | 说明 |
|------|------|
| `get_video_info(bvid)` | 获取视频详细信息 |
| `get_video_stat(bvid)` | 获取播放量等统计数据 |
| `get_video_viewers(bvid, cid)` | 获取在线观看人数 |
| `get_video_full_data(bvid)` | 获取完整数据（info + viewers） |
| `search_videos(keyword, page, page_size)` | 关键词搜索视频 |

**容错机制**：
- **多UA轮换**：6个User-Agent随机使用
- **指数退避重试**：基础2秒 × 2^attempt + 随机抖动，最高60秒
- **412错误绕过**：更换UA → 增加间隔 → 更换代理
- **代理支持**：支持HTTP/HTTPS代理，自动轮换
- **最小请求间隔**：全局 `0.5s` 间隔保护

---

### `core/notification.py`
**核心类**：`NotificationManager`

**推送渠道**：
1. **Windows原生通知** - 使用 `plyer` 库
2. **QQ私聊** - OneBot HTTP API `/send_private_msg`
3. **QQ群聊** - OneBot HTTP API `/send_group_msg`

**安全注意**：
- Token通过明文HTTP传输会记录WARNING日志
- 建议配置为HTTPS/WSS地址

---

## 三、算法模块（algorithms/）

### `algorithms/base.py`
**核心类**：`BaseAlgorithm`（抽象基类）

```python
class BaseAlgorithm(ABC):
    name: str = "基类算法"
    description: str = "预测算法基类"
    category: str = "基础"
    
    @abstractmethod
    def predict(self, current_views, target_views, history_data, video_info) -> Optional[tuple]:
        """返回 (预测秒数, 置信度) 或 None"""
```

### `algorithms/registry.py`
**核心类**：`AlgorithmRegistry`（类方法）

**职责**：
- 加载基础目录算法（6个）
- 加载 `models/` 目录算法（通过 `model_adapter` 适配）
- 提供 `predict_all()` 批量预测接口
- 计算加权预测结果 `_weighted`

**`predict_all()` 返回格式**：
```python
{
    "算法名": {
        "prediction": float,   # 预测值
        "confidence": float,   # 置信度 0-1
        "weight": float,       # 权重
        "metadata": {...}     # 额外数据
    },
    "_weighted": {  # 加权预测结果
        "prediction": float,
        "valid_algorithms": int,
        "total_algorithms": int
    }
}
```

### `algorithms/weight_manager.py`
**核心类**：`WeightManager`（单例）

**权重体系**：
- **用户自定义权重**（优先级最高）
- **ML权重**：基于历史准确率的指数加权平均
- 权重范围：0.5 ~ 2.0（归一化后）
- 准确率记录最多保留100条

### `algorithms/model_adapter.py`
**核心类**：`ModelAlgorithmAdapter`

**职责**：统一 40+ 种 models 算法接口

**接口类型检测**：
- 类型1：`predict(video_data, threshold)`
- 类型2：`predict(current_views, target_views, history_data, video_info)`

**语义统一**：
- models 算法原始返回「达到阈值所需时间」
- 适配器统一转换为「下一周期的短期播放量预测」
- 短期窗口固定为 **75秒**（与 `DEFAULT_INTERVAL` 对齐）

### `algorithms/models/`（40个算法）

| 类别 | 算法文件 | 说明 |
|------|----------|------|
| 基础速度 | `linear_velocity.py` | 线性速度 |
| | `weighted_velocity.py` | 加权速度 |
| | `share_velocity.py` | 分享速度 |
| | `like_momentum.py` | 点赞动量 |
| 时间衰减 | `exponential_decay.py` | 指数衰减 |
| | `logarithmic_growth.py` | 对数增长 |
| | `power_law.py` | 幂律增长 |
| 增长模型 | `gompertz_growth.py` | Gompertz |
| | `logistic_growth.py` | Logistic |
| | `richards_curve.py` | Richards |
| | `bass_diffusion.py` | Bass扩散 |
| | `weibull_growth.py` | Weibull |
| 神经网络 | `neural_network_simple.py` | 简单神经网络 |
| | `lstm_simple.py` | LSTM |
| | `mlp_predictor.py` | MLP |
| | `attention_mechanism.py` | 注意力机制 |
| 机器学习 | `svr_predictor.py` | SVR |
| | `random_forest_simple.py` | 随机森林 |
| | `xgboost_simple.py` | XGBoost |
| | `catboost_simple.py` | CatBoost |
| | `adaptive_boosting.py` | AdaBoost |
| | `gradient_boost_simple.py` | 梯度提升 |
| 时间序列 | `arima_simple.py` | ARIMA |
| | `exponential_smoothing.py` | 指数平滑 |
| | `holt_winters.py` | Holt-Winters |
| | `seasonal_decomposition.py` | 季节分解 |
| 统计模型 | `bayesian_regression.py` | 贝叶斯回归 |
| | `kalman_filter.py` | 卡尔曼滤波 |
| | `gaussian_process.py` | 高斯过程 |
| 集成模型 | `ensemble_weighted.py` | 加权集成 |
| | `ensemble_voting.py` | 投票集成 |
| | `ensemble_stacking.py` | 堆叠集成 |
| | `ensemble_average.py` | 均值集成 |
| 趋势分析 | `trend_regression.py` | 趋势回归 |
| | `moving_average.py` | 移动平均 |
| 特色分析 | `viral_potential.py` | 病毒潜力 |
| | `quality_score.py` | 质量评分 |
| | `engagement_rate.py` | 互动率 |
| | `comment_trend.py` | 评论趋势 |
| | `coin_boost.py` | 硬币助推 |

---

## 四、UI模块（ui/）

### `ui/theme.py`
**设计令牌系统**：全局 `C` 字典管理所有颜色

**主题色板**（深色/浅色）：

| Key | 深色 | 浅色 | 用途 |
|-----|------|------|------|
| `bg_base` | `#0d1117` | `#ffffff` | 底层背景 |
| `bg_surface` | `#161b22` | `#f6f8fa` | 卡片/面板背景 |
| `bilibili` | `#fb7299` | `#fb7299` | 主题色（B站粉） |
| `accent` | `#58a6ff` | `#0969da` | 强调色 |
| `success` | `#3fb950` | `#1a7f37` | 成功/增长 |
| `danger` | `#f85149` | `#d1242f` | 危险/警告 |

**核心函数**：
- `apply_theme(root, theme_name)` - 切换主题，更新C字典 + ttk样式 + 遍历刷新所有控件
- `_recolor_widget_tree(widget)` - 递归刷新所有原生tk控件颜色
- `_recolor_text_tags(text_widget)` - 刷新 tk.Text 的 tag 颜色
- `rounded_rect(canvas, x1, y1, x2, y2, r, **kwargs)` - Canvas 圆角矩形

**主题切换机制**：
- C 是可变全局字典，`apply_theme()` 就地更新
- 所有控件通过引用 `C["key"]` 自动响应
- 使用反向索引 `(_widget_type, _attr, old_color) → semantic_key` 识别控件语义

---

### `ui/helpers.py`
**常量定义**：
```python
THRESHOLDS       = [100_000, 1_000_000, 10_000_000]  # 10万/100万/1000万
THRESHOLD_NAMES  = ["10万", "100万", "1000万"]
DEFAULT_INTERVAL = 75   # 常规刷新间隔（秒）
FAST_INTERVAL    = 10  # 快速模式间隔（秒）
FAST_GAP         = 500 # 进入快速模式的条件：距阈值 < 500
```

**工具函数**：
| 函数 | 说明 |
|------|------|
| `fmt_num(n)` | 格式化数字：`12345 → "12,345"` |
| `fmt_eta(minutes)` | 格式化预计时间：`90 → "约1h30min"` |
| `abbrev(n)` | 数字缩写：`99500 → "9.9w"` |
| `nearest_threshold_gap(views)` | 返回距最近未达标阈值的差距 |
| `card_status_tag(gap)` | 根据gap返回状态标签和颜色 |
| `rounded_rect(...)` | Canvas圆角矩形（polygon + smooth） |

---

### `ui/chart.py`
**Canvas图表绘制**：纯 Tkinter Canvas，不依赖 matplotlib

**核心函数**：
| 函数 | 职责 |
|------|------|
| `draw_chart(canvas, history_data, bvid, video, FONT)` | 总入口 |
| `compute_chart_scale(...)` | 计算坐标轴范围和转换函数 px/py |
| `draw_chart_grid(...)` | 坐标轴 + 5等分网格 + Y轴标签 |
| `draw_threshold_lines(...)` | 阈值虚线（10万/100万/1000万） |
| `draw_chart_series(...)` | 面积填充 + 折线 + 数据点 |
| `draw_chart_annotations(...)` | 最新值标注 + X轴时间 + 图例 |

**防抖机制**：200ms 防抖，避免拖拽时每像素触发重绘

---

### `ui/log_panel.py`
**核心类**：`LogPanel`

**日志级别**：DEBUG / INFO / WARNING / ERROR

**核心方法**：
- `add_log(level, message)` - 添加日志（内存+文件）
- `refresh_log_view()` - 根据过滤级别刷新视图
- `set_log_level(level)` - 切换过滤级别
- `start_auto_refresh(root)` - 日志页面打开时3秒自动刷新

**与 FileLogger 协作**：
- 内存最多存2000条（超过时保留后1500条）
- 所有日志实时写入文件

---

### `ui/monitor_service.py`
**业务逻辑层**：不直接操作GUI，只负责数据拉取和预测

**核心函数**：
| 函数 | 职责 |
|------|------|
| `fetch_single_video_data(gui, bvid, callback)` | 后台线程拉取单视频 |
| `fetch_all_video_data(gui, callback)` | 后台线程批量拉取 |
| `predict_single(gui, bvid, video, callback)` | 运行单视频预测 |
| `auto_predict_video(gui, bvid)` | 单视频预测（后台） |
| `auto_predict_all(gui)` | 批量预测（后台） |
| `load_watch_list(gui)` | 启动时从settings.json恢复监控列表 |
| `merge_history(gui, bvid)` | 合并内存历史与数据库历史 |
| `calc_growth_rate(history)` | 计算播放量增长速率（播放量/秒） |

**线程安全**：
- 所有API调用和数据写入在后台线程执行
- GUI更新通过 `gui.root.after(0, callback)` 回调到主线程

---

### `ui/main_gui.py`
**核心类**：`BilibiliMonitorGUI`（~1640行）

**布局结构**：
```
┌─────────────────────────────────────────────────────────────┐
│  标题栏（Logo + 导航按钮 + 主题切换 + 设置）                    │
├──────────┬──────────────────────────────┬───────────────────┤
│          │  详情头 + 统计栏 + 标签切换   │                   │
│  左侧    │  ┌────────────────────────┐  │  右侧             │
│  310px   │  │  Canvas图表/详细文本/   │  │  290px            │
│          │  │  互动率视图             │  │                   │
│  视频列表 │  └────────────────────────┘  │  预测分析          │
│  + 搜索框│                              │                   │
│          │                              │                   │
├──────────┴──────────────────────────────┴───────────────────┤
│  底部操作栏（添加/刷新/删除 + 自动刷新开关）                     │
├─────────────────────────────────────────────────────────────┤
│  状态栏（监控数/间隔/算法/上次刷新/状态）                        │
└─────────────────────────────────────────────────────────────┘
```

**per-video 独立定时器**：
```python
self._video_timers = {bvid: {"next": float, "interval": int}}
self._fetching_set  = set()  # 防止并发拉取
_global_tick()  # 1秒全局滴答，检查到期视频并独立拉取
```

**刷新策略**：
- 距阈值 < 500：快速模式（10秒间隔）
- 其他：正常模式（75秒间隔）

**封面异步加载**：
- 缩略图缓存 key：`("thumb", bvid)`
- 固定尺寸：80×45（16:9比例）
- 后台线程加载 + `root.after()` 回调主线程设置

---

### `ui/data_comparison.py`
**核心类**：`DataComparisonWindow`（标签页界面）

**三个标签**：
1. **趋势图**：选视频 → 选指标（播放/点赞/投币/收藏/分享/弹幕/评论/点赞率）→ 折线图对比
2. **快照对比**：选视频 → 选时间点 → 多指标柱状图，支持快捷筛选（最近1h/今天/最近3天）
3. **数据录入**：里程碑模式（投稿后周期）或历史快照模式

**柱状图渲染**（polygon 圆角矩形）：
```python
def _draw_bar(canvas, x0, y0, x1, y1, color_top, color_body):
    # 圆角矩形 = 8点 polygon + smooth=True
    pts = [x0+r, y0, x1-r, y0, x1, y0+r, x1, y1-r,
           x1-r, y1, x0+r, y1, x0, y1-r, x0, y0+r]
```

---

### `ui/milestone_stats.py`
**核心类**：`MilestoneStatsWindow`

**里程碑周期**："1周" / "1月" / "1年"

**功能**：
- 批量BV录入
- 7种指标柱状对比
- 支持将BV添加到监控列表

**数据库接口**（`Database` 类）：
```python
upsert_milestone(bvid, period, data)   # 新增或更新
get_milestones(bvid=None)              # 查询（可按bvid过滤）
get_all_milestones_grouped()           # 返回 {bvid: {period: row}}
delete_milestone(bvid, period)         # 删除
```

---

### 其他UI组件

| 文件 | 核心类 | 功能 |
|------|--------|------|
| `settings_window.py` | `SettingsWindow` | 系统设置（推送配置等） |
| `video_search.py` | `VideoSearchWindow` | 关键词搜索B站视频 |
| `crossover_analysis.py` | `CrossoverAnalysisWindow` | 多视频播放量交叉计算 |
| `database_query.py` | `DatabaseQueryWindow` | SQLite数据查询（Treeview分页） |
| `weight_settings.py` | `WeightSettingsWindow` | 算法权重管理 |
| `network_settings.py` | `NetworkSettingsWindow` | 代理/API设置 |
| `weekly_score.py` | `WeeklyScoreWindow` | 周刊评分计算界面 |

---

## 五、工具模块（utils/）

### `utils/helpers.py`
| 函数 | 说明 |
|------|------|
| `format_number(n)` | 数字格式化（万/亿单位） |
| `format_duration(seconds)` | 时长格式化（12:34） |
| `parse_duration(str)` | 解析时长字符串 |
| `parse_threshold(s)` | 解析阈值字符串（"10万" → 100000） |
| `calculate_growth_rate(...)` | 计算增长率 |
| `calculate_like_view_ratio(...)` | 播赞比 |
| `safe_divide(a, b, default)` | 安全除法 |

### `utils/exporters.py`
| 函数 | 说明 |
|------|------|
| `export_to_csv(data, filepath, headers)` | 导出CSV |
| `export_to_json(data, filepath, indent)` | 导出JSON |
| `export_video_data(video_data, directory, formats)` | 多格式导出 |
| `generate_export_filename(bvid, keyword, ext)` | 生成导出文件名 |

### `utils/file_logger.py`
**核心类**：`FileLogger`（线程安全）

**日志文件命名**：
- 运行中：`20260422_143000-running.log`
- 完成后：`20260422_143000-235959.log`

**跨天处理**：
- 使用 tkinter `root.after(30000, _check)` 每30秒检查一次
- 检测到跨天后：关闭旧文件（命名+重命名）→ 打开新文件
- 退出时自动调用 `close()` 完成最终命名

---

## 六、设计决策总结

### 1. 数据库架构
- **per-video 独立数据库**：`data/<bvid>/<bvid>.db`
- **总数据库**：`data/bilibili_monitor.db` 同步所有视频数据
- **优势**：避免单文件过大，支持按需查询

### 2. 线程模型
- **GUI主线程**：只负责UI渲染和用户交互
- **后台工作线程**：API拉取、数据写入、预测计算
- **通信机制**：`root.after(0, callback)` 将结果回调主线程

### 3. 主题系统
- **设计令牌**：`C` 全局字典存储颜色
- **反向索引**：通过 `(_widget_type, _attr, old_color) → semantic_key` 识别控件语义
- **主题切换**：更新C字典 → 重新配置ttk样式 → 遍历刷新所有控件

### 4. 预测算法
- **适配器模式**：`ModelAlgorithmAdapter` 统一 40+ 算法接口
- **语义统一**：models算法的"到达阈值时间"转换为"下一周期播放量预测"
- **加权集成**：多算法加权平均，配合 ML 权重自动调整

### 5. 监控刷新机制
- **per-video 独立定时器**：每个视频独立计时
- **全局1秒滴答器**：每秒检查哪些视频到期
- **双模式**：正常模式（75s）+ 快速模式（10s，距阈值<500时触发）

---

*文档生成时间：2026-04-22*
