# B站视频监控与播放量预测系统

基于 Tkinter 的 B站视频数据监控与播放量预测桌面应用，集成 **75 种预测算法**，支持 Windows 原生推送和 QQ Bot 推送。

## 功能特性

### 核心功能
- **视频搜索**: 关键词搜索B站视频，支持多关键词批量搜索与自动去重
- **数据监控**: 实时监控播放量、点赞、投币、弹幕、在线观看人数等指标
- **播放量预测**: 75 种算法预测到达 10万 / 100万 / 1000万 播放量所需时间
- **算法权重管理**: ML 权重自动调整（含 Hedge 在线学习算法）
- **因果推断**: Granger 因果检验分析各指标与播放量的领先/滞后关系
- **图神经网络**: 基于视频关联图的 GCN 节点嵌入增强预测
- **阈值推送**: 视频突破播放量阈值时自动推送通知
- **数据对比**: 趋势折线图（8种指标切换）+ 快照柱状图（多指标多时间点对比），支持里程碑数据叠加
- **交叉计算**: 分析多个视频播放量交会时间和预测
- **里程碑统计**: 记录视频投稿一周 / 一月 / 一年后的数据，多视频多周期柱状对比
- **数据库查询**: 本地历史数据的可视化查询工具
- **数据导出**: 支持 CSV / JSON 导出

### 预测算法（75种）

| 类别 | 算法 | 数量 |
|------|------|:----:|
| **基础速度** | 线性速度 | 1 |
| **增长模型** | 指数增长、对数增长、幂律增长、Gompertz、Logistic、Richards、Weibull | 7 |
| **扩散模型** | Bass扩散、Gompertz扩散、Logistic扩散、Richards曲线、Weibull增长 | 5 |
| **时间序列** | ARIMA、**SARIMA**、指数平滑、Holt-Winters、移动平均、加权移动平均、线性增长、**多季节分解**、**马尔可夫体制转换**、趋势外推、趋势回归、Theta、Prophet | 13 |
| **深度学习** | MLP、神经网络、LSTM、GRU、**BiLSTM**、**TCN**、**CNN-LSTM混合**、N-BEATS、TimesNet、DLinear | 10 |
| **Transformer** | 注意力机制、Informer、TFT、PatchTST | 4 |
| **统计模型** | SVR、随机森林、高斯过程、贝叶斯回归、**Theil-Sen回归**、**分位数回归**、**泊松回归**、ElasticNet、Huber回归 | 9 |
| **集成学习** | AdaBoost、Gradient Boost、XGBoost、LightGBM、CatBoost、**ExtraTrees**、**Bagging**、**Cascade级联集成** | 8 |
| **集成模型** | 加权集成、投票集成、堆叠集成、均值集成、加权速度 | 5 |
| **互动率** | 点赞动量、分享速度、评论趋势、投币Boost、互动率综合、内容质量评分、病毒潜力 | 7 |
| **高级分析** | 卡尔曼滤波、变化点检测、生存分析、生命周期建模、**Hawkes自激过程** | 5 |
| **其他** | UP主贝叶斯、多任务学习 | 2 |

**加粗** 为本次新增算法。详细说明参见 [algorithms/ALGORITHMS.md](algorithms/ALGORITHMS.md)

### 推送通知
- **Windows 原生通知**: 系统级通知弹窗 + 声音提醒
- **QQ Bot**: OneBot 协议，支持私聊 / 群聊推送

## 项目结构

```
b站监控/
├── main.py                     # 主入口
├── run.py                      # 启动脚本
├── requirements.txt            # Python 依赖
│
├── algorithms/                 # 预测算法模块
│   ├── base.py                 # BaseAlgorithm 基类
│   ├── registry.py             # 算法注册器（自动扫描 models/）
│   ├── model_adapter.py        # 模型适配层
│   ├── weight_manager.py       # 权重管理（ML 自动调整）
│   ├── online_learner.py       # Hedge 在线学习
│   ├── causal_inference.py     # Granger 因果推断
│   ├── graph_neural.py         # 图神经网络
│   ├── ALGORITHMS.md           # 算法详细文档
│   └── models/                 # 75 种算法实现（7 个子目录）
│       ├── simple/             # 基础速度
│       ├── growth/             # 增长模型
│       ├── time_series/        # 时间序列
│       ├── statistical/        # 统计模型
│       ├── ensemble/           # 集成学习
│       ├── deep_learning/      # 深度学习
│       └── advanced/           # 高级分析
│
├── config/                     # 配置模块
│
├── core/                       # 核心模块
│   ├── database.py             # SQLite 数据库操作
│   ├── bilibili_api.py         # B站 API 封装
│   └── notification.py         # 通知管理
│
├── ui/                         # 界面模块
│   ├── main_gui.py             # 主界面（三栏布局控制器）
│   ├── theme.py                # 主题系统（深色/浅色，设计令牌 C 字典）
│   ├── helpers.py              # 界面工具（字体、阈值常量、格式化）
│   ├── chart.py                # 图表绘制（Canvas 播放量趋势图 + 阈值辅助线）
│   ├── log_panel.py            # 日志面板
│   ├── video_list_panel.py     # 左侧视频列表
│   ├── detail_panel.py         # 中间详情+图表
│   ├── prediction_panel.py     # 右侧预测面板
│   ├── bottom_bar.py           # 底部状态栏
│   ├── monitor_service.py      # 业务逻辑（per-video 独立线程）
│   ├── dialogs.py              # 弹窗管理（数据对比/交叉计算/里程碑/数据库查询）
│   ├── settings_window.py      # 系统设置
│   ├── video_search.py         # 视频搜索
│   ├── crossover_analysis.py   # 交叉分析
│   ├── data_comparison.py      # 数据对比（趋势折线图 + 快照柱状图 + 数据录入）
│   ├── milestone_stats.py      # 里程碑统计（投稿一周/月/年数据录入与对比）
│   ├── database_query.py       # 数据库查询（Treeview 分页展示）
│   ├── weight_settings.py      # 权重设置
│   ├── network_settings.py     # 网络设置
│   └── weekly_score.py         # 周报评分
│
├── utils/                      # 工具模块
│   ├── __init__.py             # 工具模块入口
│   └── file_logger.py          # 日志记录（按时间段命名，跨天 23:59:59 切分）
│
└── data/                       # 运行时数据（不入库）
    ├── settings.json           # 监控列表与配置
    ├── <BV号>/                 # 每个视频独立数据库
    └── log/                    # 日志文件
```

## 快速开始

### 环境要求
- Windows 10 / 11
- Python 3.10+
- Conda（推荐）

### 安装

```bash
# 创建环境
conda create -n bili python=3.10
conda activate bili

# 安装依赖
pip install -r requirements.txt
```

### 启动

```bash
python main.py
```

## 使用说明

### 添加监控
1. **BV号添加**: 主界面输入 BV 号 → 点击「添加监控」
2. **搜索添加**: 工具 → 视频搜索 → 关键词搜索 → 选择视频导入
3. 监控列表保存在 `data/settings.json`，重启自动恢复

### 查看预测
1. 左侧列表选中视频
2. 右侧面板实时显示播放量数据与预测结果
3. 预测阈值：10万 / 100万 / 1000万
4. 可切换算法查看不同预测结果

### 数据对比
1. 工具 → 数据对比
2. **趋势图**标签：选视频 → 选指标（播放/点赞/硬币/收藏/分享/弹幕/评论/点赞率）→ 折线图对比
3. **快照对比**标签：选视频 → 智能加载历史时间点（支持快捷筛选：最近1h/今天/最近3天）→ 多指标柱状对比，可叠加里程碑数据
4. **数据录入**标签：里程碑模式（投稿后周期录入）或历史快照模式（指定时间点录入）

### QQ Bot 配置
1. 部署 OneBot 协议实现（如 go-cqhttp、LLOneBot）
2. 设置 → 系统设置 → OneBot 配置 HTTP / WS 地址
3. 填写推送目标 QQ 号或群号
4. 点击「测试连接」验证

## 技术栈

| 组件 | 技术 |
|------|------|
| GUI | CustomTkinter + tkinter |
| 数据库 | SQLite3（按视频分库存储） |
| 数据处理 | pandas, numpy, scipy |
| 机器学习 | scikit-learn, xgboost, lightgbm, catboost, statsmodels |
| 时间序列 | statsmodels, Prophet |
| 推送 | plyer（Windows）, websockets（QQ Bot/OneBot） |
| 可视化 | matplotlib, seaborn |
| 代码质量 | Black, Flake8, MyPy, Bandit, Radon, Pre-commit |

## 注意事项

- 请合理使用 API，监控间隔建议 5 分钟以上
- 预测结果仅供参考，实际播放量受多种因素影响
- QQ Bot 需自行搭建 OneBot 协议服务端
- 数据库文件按 BV 号独立存储在 `data/` 下

## License

MIT License
