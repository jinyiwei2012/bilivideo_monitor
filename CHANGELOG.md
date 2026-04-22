# 更新日志 (Changelog)

所有重要改动按日期分组，方便追踪项目演进。

---

## [2026-04-22] v0.x — 里程碑统计 & 数据对比重构 & UI 打磨

### 新功能

#### 里程碑统计系统
- **新增 `video_milestones` 数据库表**（bvid + period 唯一索引）
- **里程碑录入窗口**（`ui/milestone_stats.py`）：
  - 批量输入 BV 号（每行一个），格式自动校验
  - 支持录入：播放量、点赞、投币、分享、收藏、弹幕、评论、备注
  - 同 BV + 周期记录用 `ON CONFLICT...DO UPDATE` 自动覆盖
  - BV 号不在监控列表时，弹窗询问是否加入监控
- **里程碑对比视图**：
  - 多视频 × 三周期（1周/1月/1年）柱状图，蓝/绿/橙配色
  - 7 种指标（播放/点赞/投币/收藏/分享/弹幕/评论）切换
  - BV 关键词筛选过滤
  - 明细表格（Treeview），右键删除

#### 数据对比全面重构（`ui/data_comparison.py`）
- **标签1「趋势图」**：折线图，支持 8 种指标切换，最多 8 个视频同时对比
- **标签2「快照对比」**：
  - 选视频后自动加载历史时间点（智能采样，每天最多 8 个时间点）
  - 快捷筛选：最近1h / 今天 / 最近3天 / 全部
  - 多指标多选（指标 Checkbutton），任意视频 × 任意时间点组合
  - 里程碑数据叠加（深色柱区分）
  - 图表横向可滚动，多指标按垂直分区布局
- **标签3「数据录入」**：
  - 里程碑模式：一周/月/年周期批量录入
  - 历史快照模式：指定日期时间录入到历史表
  - 「从监控列表添加全部」快速填充 BV 号
  - 已录入数据表格，右键可删除

#### 75 分钟短期预测
- `model_adapter.py` 将 50+ 算法统一适配为 6 个基础算法池
- 75 分钟时间窗口内的短期播放量预测

### 性能优化
- **per-video 独立刷新定时器**：每个视频独立计时，靠近阈值（距离 < 500）自动切换 10s 快速模式，正常 75s 间隔
- **全局 1 秒滴答器** (`_global_tick`) 统一调度，避免多线程竞态
- **图表防抖**：窗口 resize 时 200ms 防抖，拆分为 `_do_chart_redraw` 实际重绘
- **封面图优化**：封面从顶部移至左侧卡片缩略图（80×45），新增 `_load_cover_thumb` 异步加载，缓存 key 区分尺寸

### UI/UX 改进
- **深色 / 浅色主题切换**：`ui/theme.py` 基于 C 设计令牌字典，`apply_theme()` 就地更新所有控件颜色
- **数据对比界面美化**：
  - Listbox 选中高亮统一改为柔和粉色 `bilibili_dim`
  - LabelFrame 标题加粗蓝色，右侧面板加背景色
  - 快捷筛选按钮改为胶囊风格，hover 效果切换粉色
  - 柱状图改用 polygon 圆角矩形，质感更细腻
  - 图表区域加 `bg_elevated` 外框卡片感
  - 图例文字颜色与对应视频主题色呼应
- **日志面板重构**：`log_panel.py` 提取 `_should_show()` 统一过滤逻辑，支持 DEBUG / INFO / WARNING / ERROR 多级别

### Bug 修复
- 修复 `show='tree headings'` 导致 Treeview 列偏移问题（`database_query.py`）
- `monitor_service.py` 重复导入合并、死代码清理
- `period_map` 死代码删除
- Entry 颜色 `entry_bg` → `bg_base`
- 两处静默 `except: pass` 改为打印日志
- 趋势图网格线 `n_grid=5` 统一
- 图例 Frame 背景色补全
- `_hover_btn` 悬停效果精简

---

## [2026-04-21] — 模块化重构 & 数据库优化

### 架构重构
- **main_gui.py 拆分为 5 个模块**（约 2925 行 → 精简控制器 + 独立模块）
  - `ui/theme.py` — 主题系统（C 设计令牌、深色/浅色主题、控件刷新）
  - `ui/helpers.py` — 界面工具（字体、阈值常量、格式化、圆角矩形）
  - `ui/chart.py` — 图表绘制（Canvas 播放量趋势图）
  - `ui/log_panel.py` — 日志面板（LogPanel 类）
  - `ui/monitor_service.py` — 业务逻辑（数据拉取、预测、监控管理）

### 数据库优化
- `VideoDatabase` 和 `Database` 改为**长连接 + `threading.Lock` + `_ConnectionCtx` 上下文管理器**
- `with self._get_connection()` 语法兼容，自动获取锁 / commit / 释放

---

## [更早版本]

### 基础功能
- 视频搜索（B站关键词 + 多关键词批量）
- 数据监控（播放量、点赞、投币、弹幕、在线人数）
- 40+ 预测算法（Gompertz、Logistic、LSTM、SVR、随机森林、XGBoost 等）
- 阈值推送（Windows 原生通知 + QQ Bot OneBot 协议）
- 交叉分析（视频播放量交会预测）
- 数据库查询（Treeview 分页展示）
- CSV / JSON 导出
