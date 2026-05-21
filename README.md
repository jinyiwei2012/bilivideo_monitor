# B站视频监控与播放量预测系统

基于 CustomTkinter 的 B站视频数据监控与播放量预测桌面应用，集成 **83 种预测算法**（含 8 种 2026 前沿算法），支持 Windows 原生推送和 QQ Bot 推送。

## 功能特性

### 核心功能
- **视频搜索**: 关键词搜索B站视频，支持多关键词批量搜索与自动去重
- **数据监控**: 实时监控播放量、点赞、投币、弹幕、在线观看人数等指标
- **播放量预测**: 83 种算法预测到达 10万 / 100万 / 1000万 播放量所需时间
- **算法权重管理**: ML 权重自动调整（含 Hedge 在线学习算法）
- **因果推断**: Granger 因果检验分析各指标与播放量的领先/滞后关系
- **图神经网络**: 基于视频关联图的 GCN 节点嵌入增强预测
- **阈值推送**: 视频突破播放量阈值时自动推送通知
- **数据对比**: 趋势折线图（8种指标切换）+ 快照柱状图（多指标多时间点对比），支持里程碑数据叠加
- **弹幕分析**: 获取视频弹幕，支持 LLM 自动分析情感倾向与关键词提取
- **AI 问答**: 基于历史播放数据的 LLM 智能问答助手
- **UP主追踪**: 监控 UP 主粉丝数、投稿数变化趋势
- **热门发现**: 发现当前热门视频与趋势话题
- **健康探针**: API 连通性检测与 LLM 服务状态监控
- **模型训练**: 内置 PyTorch 训练管线，支持全局预训练与视频微调，实时 loss 图表可视化
- **模型激活**: 自动/手动切换各算法最新训练模型
- **交叉计算**: 分析多个视频播放量交会时间和预测
- **里程碑统计**: 记录视频投稿一周 / 一月 / 一年后的数据，多视频多周期柱状对比
- **数据库查询**: 本地历史数据的可视化查询工具
- **数据导出**: 支持 CSV / JSON 导出
- **看板模式**: 多视频关键指标一览面板

### LLM 集成
- **多供应商支持**: OpenAI / DeepSeek / Claude / SiliconFlow 等多配置切换
- **弹幕智能分析**: LLM 自动分析弹幕情感倾向与核心关键词，结果本地缓存
- **历史问答**: 基于视频播放量趋势数据的上下文智能问答

### 预测算法（83种）

| 类别 | 算法 | 数量 |
|------|------|:----:|
| **基础速度** | 线性速度、加权速度 | 2 |
| **增长/衰减** | 指数增长、对数增长、幂律衰减、指数衰减 | 4 |
| **扩散模型** | Bass扩散、Gompertz、Logistic、Richards、Weibull | 5 |
| **时间序列** | ARIMA、SARIMA、指数平滑、Holt-Winters、移动平均、加权移动平均、线性增长、多季节分解、马尔可夫体制转换、趋势外推、Theta、Prophet、卡尔曼滤波 | 13 |
| **深度学习** | MLP、神经网络、LSTM、GRU、BiLSTM、TCN、CNN-LSTM混合、CNN图像化、N-BEATS、TimesNet、DLinear、注意力机制、Diffusion TS、KNF Koopman、Mar-BiLSTM | 15 |
| **Transformer模型** | Informer、TFT、PatchTST、Lag-Llama、MOIRAI | 5 |
| **统计模型** | SVR、随机森林、高斯过程、贝叶斯回归、ElasticNet、Huber、Theil-Sen、分位数回归、泊松回归、TSFC特征分类、变化点检测、生存分析 | 12 |
| **机器学习** | AdaBoost、GradientBoost、XGBoost、LightGBM、CatBoost、ExtraTrees、Bagging、Cascade级联 | 8 |
| **集成模型** | 加权集成、投票集成、堆叠集成、平均集成 | 4 |
| **互动率** | 点赞动量、分享速度、评论趋势、投币Boost、互动率综合、质量评分、病毒潜力 | 7 |
| **高级分析** | Hawkes自激过程、DistDF分布对齐、生命周期建模、多任务学习、UP主贝叶斯、概率模型 | 6 |
| **概率/贝叶斯** | 贝叶斯回归、高斯过程 | 2 |

详细说明参见 [algorithms/ALGORITHMS.md](algorithms/ALGORITHMS.md)

### 推送通知
- **Windows 原生通知**: 系统级通知弹窗 + 声音提醒
- **QQ Bot**: OneBot 协议，支持私聊 / 群聊推送

## 项目结构

```
b站监控/
├── main.py                     # 主入口
├── run.py                      # 启动脚本（环境检查 + 初始化）
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
│   ├── training/               # PyTorch 训练管线
│   │   ├── trainer.py          # 统一训练编排器
│   │   ├── dataset.py          # 时序数据集
│   │   ├── checkpoint_manager.py # 多版本 Checkpoint 管理
│   │   ├── hf_loader.py        # HuggingFace 模型加载器
│   │   └── device.py           # 设备管理
│   └── models/                 # 83 种算法实现（7 个子目录）
│       ├── simple/             # 基础速度
│       ├── growth/             # 增长模型
│       ├── time_series/        # 时间序列
│       ├── statistical/        # 统计模型
│       ├── ensemble/           # 集成学习
│       ├── deep_learning/      # 深度学习
│       └── advanced/           # 高级分析
│
├── config/                     # 配置模块（加载/保存）
│
├── core/                       # 核心模块
│   ├── database/               # SQLite 数据库包
│   │   ├── __init__.py         # 导出 db, MonitorRecord, PredictionRecord
│   │   ├── models.py           # 数据模型（VideoInfo, MonitorRecord, PredictionRecord）
│   │   ├── connection.py       # 连接管理（线程安全上下文）
│   │   ├── video_db.py         # 单视频数据库（按 BV 分库）
│   │   └── central_db.py       # 中央数据库（全局实例 db）
│   ├── bilibili_api.py         # B站 API 封装（412 重试、代理轮换、WBI 签名、Cookie 持久化）
│   ├── notification.py         # 通知管理（Windows 原生通知 + QQ Bot）
│   ├── proxy_manager.py        # 代理管理器（轮询、可用性检测、UA 绑定、失败自动剔除）
│   ├── smart_alert.py          # 智能告警（异常增长检测、趋势反转）
│   ├── up_database.py          # UP 主数据管理
│   └── data/                   # 数据库运行时文件（自动生成）
│       ├── bilibili_monitor.db # 中央数据库
│       └── <BV号>/             # 按视频分库
│
├── ui/                         # 界面模块
│   ├── main_gui.py             # 主界面（三栏布局控制器 + 全局时钟）
│   ├── theme.py                # 主题系统（深色/浅色，设计令牌 C 字典）
│   ├── helpers.py              # 界面工具（字体、阈值常量、格式化）
│   ├── chart.py                # 图表绘制（Canvas 播放量趋势图 + 阈值辅助线）
│   ├── log_panel.py            # 日志面板（线程安全队列，等级过滤）
│   ├── monitor_service.py      # 业务逻辑（per-video 独立 Worker 线程）
│   ├── video_list_panel.py     # 左侧视频列表（封面缓存 + 状态标签）
│   ├── detail_panel.py         # 中间详情+图表（趋势图 / 详细数据 / 互动率）
│   ├── prediction_panel.py     # 右侧预测面板
│   ├── bottom_bar.py           # 底部状态栏
│   ├── dialogs.py              # 弹窗管理
│   ├── settings_window.py      # 统一系统设置（LLM、代理、Cookie、权重、通知等全参数）
│   ├── video_search.py         # 视频搜索
│   ├── data_comparison.py      # 数据对比主窗口
│   ├── trend_tab.py            # 趋势折线图标签页
│   ├── snapshot_tab.py         # 快照柱状图标签页
│   ├── entry_tab.py            # 数据录入标签页
│   ├── crossover_analysis.py   # 交叉分析
│   ├── danmaku_analysis.py     # 弹幕分析窗口（LLM 情感分析、词云）
│   ├── ai_qa_window.py         # AI 问答助手
│   ├── dashboard_mode.py       # 看板模式
│   ├── up_tracker.py           # UP 主追踪
│   ├── trending_discovery.py   # 热门发现
│   ├── health_probe.py         # 健康探针
│   ├── report_scheduler.py     # 报告调度
│   ├── milestone_stats.py      # 里程碑统计
│   ├── training_panel.py       # 模型训练面板（loss 图表 + 日志）
│   ├── database_query.py       # 数据库查询
│   └── weekly_score.py         # 周报评分
│
├── utils/                      # 工具模块
│   ├── __init__.py
│   ├── ai_qa.py                # LLM API 调用（多供应商兼容）
│   ├── cover_manager.py        # 封面管理器（本地缓存、MD5 校验、按需重下载）
│   ├── file_logger.py          # 日志记录（按时间段命名，跨天切分）
│   ├── interaction_quality.py  # 一键三连健康探针 / 评分
│   ├── weekly_score.py         # 周刊评分计算
│   ├── yearly_score.py         # 年刊评分计算
│   ├── report_exporter.py      # 报告导出（CSV/JSON）
│   └── sentiment_analyzer.py   # 情感分析工具
│
├── assets/                     # 静态资源
│   ├── app_icon.png            # 应用图标（PNG）
│   └── app_icon.ico            # 应用图标（ICO）
│
├── data/                       # 运行时数据（不入库）
│   ├── settings.json           # 监控列表与配置
│   ├── network_config.json     # 网络配置（代理、Cookie）
│   ├── bilibili_monitor.db     # 中央数据库（摘要同步）
│   ├── cover/                  # 封面图片缓存
│   ├── exports/                # CSV/JSON 导出文件
│   ├── <BV号>/                 # 每个视频独立数据库（data/<BV>/<BV>.db）
│   └── log/                    # 日志文件
│
├── .flake8                     # Flake8 配置
├── .gitignore
├── .pre-commit-config.yaml     # Pre-commit 钩子配置
├── CLAUDE.md                   # Claude Code 项目指令
├── CODE_REVIEW.md              # 代码审查指南
├── mypy.ini                    # MyPy 类型检查配置
├── pyproject.toml              # 项目工具配置（Bandit 等）
├── start.bat                   # Windows 快速启动脚本
```

## 从零开始运行

### 环境要求
- Windows 10 / 11（推荐）
- Python 3.10+
- Git
- Conda（推荐，避免依赖冲突）

### 第一步：克隆项目

```bash
git clone https://github.com/jinyiwei2012/bilivideo_monitor.git
cd bilivideo-monitor
```

> 如果已下载 ZIP 压缩包，解压后进入目录即可，无需 git 命令。

### 第二步：创建 Conda 环境

```bash
# 创建 Python 3.10 环境（名称任意，这里用 bilibili）
conda create -n bilibili python=3.10

# 激活环境
conda activate bilibili
```

> 如果你不想用 Conda，也可以用 venv：
> ```bash
> python -m venv venv
> venv\Scripts\activate
> ```

### 第三步：安装依赖

```bash
# 确保 pip 为最新
pip install --upgrade pip

# 安装项目依赖
pip install -r requirements.txt
```

如果安装 `prophet` 失败（Windows 上常见），它是可选的，可以跳过：

```bash
# 先安装除 prophet 外的所有依赖
pip install -r requirements.txt --ignore-installed prophet

# 或手动排除
sed -i '/prophet/d' requirements.txt && pip install -r requirements.txt
```

安装完成后验证关键依赖：

```bash
python -c "import numpy; import requests; import customtkinter; print('✅ 核心依赖就绪')"
```

### 第四步：启动程序

```bash
# 确保 conda 环境已激活
conda activate bilibili

# 方式一：直接启动（推荐）
python main.py

# 方式二：启动脚本（会检查环境 + 初始化算法）
python run.py
```

首次启动会：
1. 自动创建 `data/` 目录和 SQLite 数据库
2. 加载 83 种预测算法
3. 打开主界面

### 首次使用配置

#### 1. 配置代理（绕过 412 限流）

B站 API 有 IP 级别的频率限制，建议配置 HTTP 代理：

```
系统设置 → 代理设置 → 粘贴代理地址（每行一个）→ 检查可用性 → 保存
```

代理格式示例：
```
http://127.0.0.1:7890
http://user:pass@proxy.example.com:8080
socks5://127.0.0.1:1080
```

> 代理配置会自动保存在 `data/network_config.json`，关闭窗口即保存，下次启动自动加载。

#### 2. 配置 Cookie（可选，获取更多数据）

方法一（推荐）：扫码登录
```
系统设置 → Cookie设置 → 扫码登录 → 用 B站 手机客户端扫码
```

方法二：浏览器导出 Cookie
```
系统设置 → Cookie设置 → Cookie-Editor JSON → 粘贴导出的 JSON
```

> 浏览器扩展 [Cookie-Editor](https://github.com/Moustachauve/cookie-editor) 可导出 JSON 格式。

#### 3. 添加监控视频

方法一：直接输入 BV 号
```
主界面顶部输入框 → 粘贴 BV 号 → 点击「添加监控」
```

方法二：搜索添加
```
工具 → 视频搜索 → 输入关键词 → 选择视频 → 导入所选到监控
```

#### 4. 配置 LLM（可选，弹幕分析 / AI 问答）

```
系统设置 → AI配置 → 选择或新建配置 → 填写 API Key → 测试连接 → 保存
```

内置快速填入支持：DeepSeek、OpenAI、Claude、SiliconFlow。

### 运行结构

启动后主界面为三栏布局：

```
┌─────────────────┬────────────────────┬──────────────────┐
│  左侧：视频列表  │  中间：详情 + 图表  │  右侧：预测面板   │
│                 │                    │                  │
│  • 封面缩略图    │  • 播放量趋势图     │  • 集成预测结果   │
│  • BV号/标题    │  • 8种指标切换      │  • 各算法详细预测  │
│  • 播放量/状态   │  • 阈值辅助线       │  • 准确率/样本量  │
│  • 右键菜单      │  • 详细数据表格     │                  │
└─────────────────┴────────────────────┴──────────────────┘
```

所有设置统一在「系统设置」中管理，分为以下标签页：

| 标签页 | 功能 |
|--------|------|
| OneBot通知 | QQ Bot 推送配置 |
| 监控参数 | 检查间隔、最大监控数 |
| 预测参数 | 预测时长、最小置信度 |
| AI配置 | 多 LLM 配置管理 |
| 权重设置 | 83 种算法权重调整 |
| 代理设置 | HTTP/SOCKS 代理管理 |
| Cookie设置 | 扫码登录 / Cookie 导入 |
| 重试参数 | 请求重试策略 |
| 运行状态 | API 连接状态一览 |
| 关于作者 | 项目信息、GitHub 仓库、B站主页链接 |


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

### LLM 配置
1. 系统设置 → AI
2. 选择或创建 AI 配置（支持 OpenAI / DeepSeek / Claude / SiliconFlow）
3. 填写 API Key、Endpoint、Model
4. 点击「测试连接」验证
5. 保存后全局生效（弹幕分析、AI 问答共用）

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
| 数据库 | SQLite3（按视频分库 + 中央库） |
| 数据处理 | pandas, numpy, scipy |
| 机器学习 | scikit-learn, xgboost, lightgbm, catboost, statsmodels |
| 深度学习 | PyTorch, HuggingFace Transformers, uni2ts |
| 时间序列 | statsmodels, Prophet |
| 推送 | plyer（Windows）, websockets（QQ Bot/OneBot） |
| LLM | OpenAI / DeepSeek / Claude / SiliconFlow API |
| 代码质量 | Black, Flake8, MyPy, Bandit, Radon, Pre-commit |

## 注意事项

- 请合理使用 API，监控间隔建议 5 分钟以上
- 预测结果仅供参考，实际播放量受多种因素影响
- QQ Bot 需自行搭建 OneBot 协议服务端
- 数据库文件按 BV 号独立存储在 `core/data/` 下（中央库在 `data/` 下）
- LLM 功能需自行配置 API Key

## 从零开始开发

### 开发环境搭建

```bash
# 1. 克隆仓库
git clone https://github.com/jinyiwei2012/bilivideo_monitor.git
cd bilivideo-monitor

# 2. 创建开发环境（推荐 Conda）
conda create -n bilibili-dev python=3.10
conda activate bilibili-dev

# 3. 安装所有依赖（含开发工具）
pip install --upgrade pip
pip install -r requirements.txt
pip install black flake8 mypy bandit radon pre-commit

# 4. 安装 pre-commit 钩子（提交前自动检查）
pre-commit install

# 5. 验证环境
python -c "
import numpy, scipy, requests, customtkinter
from algorithms.registry import AlgorithmRegistry
AlgorithmRegistry.initialize()
print(f'✅ 开发环境就绪，已加载 {len(AlgorithmRegistry.get_algorithm_names())} 个算法')
"
```

### 项目架构速览

```
b站监控/
├── __init__.py                 # 包元数据（版本号等）
├── main.py                     # 入口：启动 GUI
├── run.py                      # 入口：环境检查 → 算法初始化 → 启动
├── algorithms/                 # 核心：83 种预测算法
│   ├── base.py                 # BaseAlgorithm 基类 + PredictionResult
│   ├── registry.py             # AlgorithmRegistry：自动发现、集成预测
│   ├── model_adapter.py        # 新/旧接口桥接
│   ├── weight_manager.py       # ML 驱动的权重学习
│   ├── online_learner.py       # Hedge 在线学习
│   ├── causal_inference.py     # Granger 因果推断
│   ├── graph_neural.py         # 图神经网络
│   └── models/                 # 83 种算法实现（按类别分目录）
├── core/                       # 核心：B站 API、数据库、通知
│   ├── bilibili_api.py         # API 封装（412 重试、代理、Cookie、WBI 签名）
│   ├── notification.py         # 通知管理
│   ├── proxy_manager.py        # 代理管理器
│   ├── smart_alert.py          # 智能告警
│   ├── up_database.py          # UP 主数据管理
│   └── database/               # SQLite（按 BV 分库 + 中央库）
├── ui/                         # 界面：Tkinter 三栏布局 + 30+ 面板
│   ├── main_gui.py             # 主窗口、菜单、布局
│   ├── settings_window.py      # 统一设置（10 个标签页，所有配置入口）
│   ├── dialog_base.py          # 弹窗基类
│   ├── video_list_panel.py     # 左侧视频列表（封面缓存）
│   ├── detail_panel.py         # 中间详情+图表
│   ├── prediction_panel.py     # 右侧预测面板
│   └── ... (20+ 面板)
├── utils/                      # 工具模块
│   ├── ai_qa.py                # LLM API 调用
│   ├── cover_manager.py        # 封面缓存管理
│   ├── file_logger.py          # 日志记录
│   └── ...
├── config/                     # 配置加载/保存
└── data/                       # 运行时数据（不入库）
    ├── settings.json
    ├── network_config.json
    ├── cover/                  # 封面缓存
    └── log/
```

### 如何添加一个新算法

算法模块采用**自动发现**机制，只需三步：

**第一步：创建算法文件**

在 `algorithms/models/<类别>/` 下创建 `.py` 文件：

```python
"""
我的新算法
"""
from typing import List, Dict, Any
from algorithms.base import BaseAlgorithm, PredictionResult


class MyAlgorithm(BaseAlgorithm):
    """自定义预测算法"""

    category = "时间序列"  # 分组标签，显示在权重列表

    def predict(self, video_data: List[Dict], threshold: int, **kwargs) -> PredictionResult:
        # video_data: [{"time": "2024-01-01", "view": 1000}, ...]
        # threshold: 目标播放量（100000 / 1000000 / 10000000）
        # 返回 PredictionResult(...)
        ...
```

**第二步：自动注册**

`AlgorithmRegistry` 启动时自动扫描 `models/` 目录，文件名以 `Algorithm` 结尾的类会自动注册。**无需手动注册**。

**第三步：验证**

```bash
python -c "
from algorithms.registry import AlgorithmRegistry
AlgorithmRegistry.initialize()
names = AlgorithmRegistry.get_algorithm_names()
print([n for n in names if 'My' in n])  # 确认算法已加载
"
```

算法会出现在「系统设置 → 权重设置」列表中，可调整权重和查看准确率。

### 代码质量工具

所有工具通过 pre-commit 自动运行，也可手动调用：

```bash
# 格式化（必须：所有 PR 前运行）
black --line-length=120 .

# 静态检查
flake8 .                                      # PEP 8 + 逻辑检查
mypy core/ algorithms/base.py ui/ utils/      # 类型检查（允许不通过）

# 安全扫描
bandit -r . -c pyproject.toml -ll             # 安全漏洞检查

# 复杂度分析
radon cc -a .                                 # 圈复杂度报告

# 一键全部
black --line-length=120 . && flake8 . && bandit -r . -c pyproject.toml -ll
```

### 开发工作流

```
1. 创建分支
   git checkout -b feat/your-feature

2. 修改代码
   - 遵循现有代码风格
   - 新增算法放在 algorithms/models/<类别>/ 下
   - 新 UI 窗口放在 ui/ 下，继承 DialogBase

3. 本地验证
   python main.py          # 手动测试
   black --line-length=120 .  # 格式化
   flake8 .                # 静态检查

4. 提交（pre-commit 自动检查）
   git add <files>
   git commit -m "feat: 你的改动说明"
   如果 pre-commit 钩子失败，修复后重新 git commit（不要 --no-verify）

5. 推送并创建 PR
   git push -u origin feat/your-feature
```

### 架构设计原则

| 原则 | 说明 |
|------|------|
| **算法自动发现** | 放在 `models/` 下的 `.py` 文件含 `XxxAlgorithm` 类即可，无需注册 |
| **单基类** | 所有算法继承 `BaseAlgorithm`，实现 `predict(video_data, threshold) -> PredictionResult` |
| **每视频独立线程** | `monitor_service.py` 为每个监控视频创建一个独立工作线程 |
| **每视频独立数据库** | `data/<BV>/<BV>.db` 存储各视频监控数据，中央库同步摘要 |
| **代理 + UA 轮换** | `ProxyManager` 管理代理轮询、失败自动剔除、UA 绑定 |
| **统一设置入口** | 所有配置集中在 `settings_window.py`，不分散到多个弹窗 |

### 关键模块说明

#### algorithms/ — 预测引擎

- **registry.py**: `AlgorithmRegistry` 是核心入口，提供 `predict_all()` 执行所有算法并生成加权集成结果
- **weight_manager.py**: `WeightManager` 记录每个算法的历史准确率，ML 动态调整权重
- **online_learner.py**: Hedge 在线学习算法，根据实时反馈调整权重
- **base.py**: `PredictionResult` 数据类包含 algorithm_name / predicted_hours / confidence 等字段

#### core/bilibili_api.py — B站 API

关键机制：
- **412 自动重试**: 指数退避 + 抖动，自动切换代理和 UA
- **代理轮换**: 通过 `ProxyManager` 轮询代理，失败超 3 次自动移除
- **WBI 签名**: 部分接口需要 WBI 签名，`_wbi_sign()` 自动处理
- **免登录回退**: Cookie 过期时自动用 `_request_public()` 降级

#### ui/ — Tkinter 界面

- **DialogBase**: 所有弹窗的基类，提供 `header()` / `section()` / `button_row()` 方法
- **theme.py**: `C` 字典定义所有颜色 token，深色/浅色统一切换
- **main_gui.py**: `BilibiliMonitorGUI` 主类，管理三栏布局 + 菜单 + 全局时钟
- **dialog_base.py**: 统一弹窗容器，header + 内容区 + 按钮行的标准布局

### 常见开发任务

#### 修改算法类别标签

在算法类上设置 `category` 类属性：

```python
class MyAlgorithm(BaseAlgorithm):
    category = "深度学习"  # 显示在权重列表的分组名
```

已有类别：`速度类` `时间衰减` `扩散模型` `时间序列` `统计模型` `集成学习` `深度学习` `高级分析` `基础` `其他`

#### 新增 UI 弹窗

```python
from ui.dialog_base import DialogBase

class MyDialog:
    def __init__(self, parent):
        self.dlg = DialogBase(parent, "标题", "800x600")
        self.dlg.header("标题", "副标题")
        sec = self.dlg.section()
        # ... 你的控件 ...
        self.dlg.button_row([("取消", self.window.destroy, ""), ("保存", self._save, "primary")])
```

#### 添加新的网络请求日志

核心 API 请求默认输出 DEBUG 级别日志。在 `bilibili_api.py` 的 `_request()` 中已包含 `→ GET/POST url` 和 `← status` 的进出日志。新增 API 方法只需调用 `self._request()` 即可自动获得日志。

#### 调试技巧

```bash
# 查看所有 DEBUG 级别日志（含网络请求）
python -c "
import logging
logging.basicConfig(level=logging.DEBUG, format='%(name)s %(levelname)s %(message)s')
from core.bilibili_api import bilibili_api
data = bilibili_api.get_video_info('BV1GJ411x7hQ')
print(data.get('title', 'N/A') if data else '失败')
"

# 测试单个代理
python -c "
from core.proxy_manager import ProxyManager
r = ProxyManager.test_proxy('http://127.0.0.1:7890')
print(r)
"

# 查看已注册算法
python -c "
from algorithms.registry import AlgorithmRegistry
AlgorithmRegistry.initialize()
for name in AlgorithmRegistry.get_algorithm_names():
    print(name)
"
```

## 如何贡献

欢迎任何形式的贡献！无论是新算法、新功能、Bug 修复还是文档改进。

### 贡献流程

1. **Fork 仓库** 并创建特性分支：
   ```bash
   git checkout -b feat/your-feature
   ```

2. **编写代码**：
   - 新算法放在 `algorithms/models/<类别>/` 下，类名以 `Algorithm` 结尾即可自动注册
   - 新 UI 窗口放在 `ui/` 下，推荐继承 `DialogBase` 获得统一布局
   - 遵循现有代码风格（Black 格式化、Flake8 检查）

3. **本地验证**：
   ```bash
   python main.py           # 手动功能测试
   black --line-length=120 . # 格式化
   flake8 .                  # 静态检查
   ```

4. **提交 PR**：
   - 确保 pre-commit 钩子通过（不要使用 `--no-verify`）
   - PR 标题格式：`feat: 新功能说明` / `fix: 修复问题` / `refactor: 重构说明`
   - 描述中说明改动目的和测试方式

### 贡献范围

| 领域 | 说明 |
|------|------|
| 预测算法 | 实现 `BaseAlgorithm.predict()` 即可自动注册 |
| PyTorch 训练 | 为算法添加 `build_model` 方法即可接入训练管线 |
| UI 面板 | 继承 `DialogBase` 或遵循三栏布局模式 |
| API 适配 | B站 API 变化时的兼容性修复 |
| 文档 | README、算法文档、注释改进 |
| 代码质量 | 减少圈复杂度、消除重复代码、类型注解覆盖 |

### 行为准则

- 保持友好和尊重
- 优先讨论再实现（可以先开 Issue）
- 新算法请附带测试数据或预期行为说明

## 未实现功能

以下功能在规划中或部分实现，欢迎贡献：

### 高优先级

| 功能 | 描述 | 状态 |
|------|------|:----:|
| **主题切换** | 深色/亮色主题动态切换（主题 token 已定义，切换入口已移除） | 待恢复 |
| **定时报告自动推送** | `report_scheduler.py` 框架已存在，尚未完成自动触发和推送逻辑 | 部分实现 |
| **模型批量导出/导入** | 支持一键导出所有算法 checkpoint 和训练配置，跨机器迁移 | 未实现 |
| **训练完成后自动回调** | 训练完成后自动刷新预测面板、推送通知、更新权重 | 未实现 |

### 中优先级

| 功能 | 描述 | 状态 |
|------|------|:----:|
| **Web 管理界面** | 基于 Flask/FastAPI 的辅助 Web 界面，支持移动端查看 | 未实现 |
| **Docker 部署** | 容器化支持，降低环境搭建门槛 | 未实现 |
| **多语言 (i18n)** | 英文/日文等多语言界面支持 | 未实现 |
| **自动更新检查** | 启动时检查 GitHub Release 版本并提示更新 | 未实现 |
| **CSV/JSON 定时导出** | 按计划任务自动导出监控数据到指定目录 | 未实现 |
| **自定义阈值** | 用户自定义播放量阈值（当前固定 10万/100万/1000万） | 未实现 |

### 低优先级 / 探索中

| 功能 | 描述 | 状态 |
|------|------|:----:|
| **插件系统** | 允许第三方算法和 UI 组件以插件形式加载，无需修改核心代码 | 探索中 |
| **分布式监控** | 多机协作监控，避免单 IP 请求频率限制 | 探索中 |
| **ONNX Runtime 推理** | 将 PyTorch 模型导出为 ONNX，加速 CPU 推理 | 探索中 |
| **实时 WebSocket 推送** | 播放量突破阈值时通过 WebSocket 实时推送到浏览器 | 未实现 |
| **算法可视化比较** | 并排对比多个算法的历史预测准确率和误差分布 | 未实现 |

> 标记「部分实现」的功能已有框架代码但未完成闭环；标记「待恢复」的功能曾实现后被暂时移除。
> 如果想实现某个功能，建议先开 Issue 讨论设计方案，避免重复劳动。
