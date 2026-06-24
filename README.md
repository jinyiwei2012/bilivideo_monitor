# B站视频监控与播放量预测系统

基于 **PyQt6** 的 Bilibili 视频数据监控与播放量预测桌面应用，集成 **120+ 种预测算法**，支持 Windows 原生推送和 QQ Bot (OneBot) 推送。

## 功能特性

- **视频监控** — 实时监控播放量、点赞、投币、弹幕、在线人数等指标
- **播放量预测** — 120+ 种算法预测到达 10万 / 100万 / 1000万 播放量所需时间
- **加权集成** — ML 驱动的算法权重自动调整（含 Hedge 在线学习）
- **异常检测** — 8 种检测器（飙升/放缓/停滞/买量/直播/深夜异常等），自动推送告警
- **趋势图表** — QGraphicsView 绘制，支持新增/增量/全量三种模式，阈值辅助线 + 预测投影
- **弹幕分析** — 实时弹幕抓取 + LLM 情感分析 + 关键词提取
- **AI 问答** — 基于历史播放数据的 LLM 智能问答（OpenAI / DeepSeek / Claude / SiliconFlow）
- **模型训练** — PyTorch 训练管线，支持全局预训练与视频微调，实时 loss 可视化
- **数据对比** — 趋势折线图（8 种指标）+ 快照柱状图 + 里程碑叠加
- **看板模式** — 全屏无边框轮播数据大屏
- **UP 主追踪** — 监控粉丝数、投稿数变化趋势
- **推送通知** — Windows 原生通知 + QQ Bot (OneBot 协议)

## 快速开始

### 环境要求
- Windows 10 / 11 | Python 3.10+ | Conda (推荐)

### 安装

```bash
git clone https://github.com/jinyiwei2012/bilivideo_monitor.git
cd bilivideo-monitor

conda create -n bilibili python=3.10
conda activate bilibili

pip install -r requirements.txt
pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu

python main.py
```

首次启动会自动创建 `data/` 目录和 SQLite 数据库，后台加载预测算法。

### 首次配置

1. **代理设置** — 系统设置 → 代理设置 → 粘贴代理地址（B站 API 有 IP 频率限制）
2. **Cookie 配置** — 系统设置 → Cookie 设置 → 扫码登录或浏览器导入
3. **添加监控** — 输入 BV 号或搜索关键词添加视频
4. **LLM 配置** — 系统设置 → AI 配置 → 填写 API Key（弹幕分析 / AI 问答需要）

## 项目结构

```
b站监控/
├── main.py / run.py            # 入口文件
├── algorithms/                 # 预测引擎 (120+ 算法)
│   ├── base.py                 # BaseAlgorithm 基类
│   ├── registry.py             # 算法注册器（自动发现 + 加权集成）
│   ├── weight_manager.py       # ML 权重管理
│   ├── online_learner.py       # Hedge 在线学习
│   ├── causal_inference.py     # Granger 因果推断
│   ├── graph_neural.py         # 图神经网络
│   ├── training/               # PyTorch 训练管线
│   └── models/                 # 算法实现（按类别分目录）
├── core/                       # 核心模块
│   ├── bilibili_api.py         # B站 API (412 重试 / 代理 / WBI 签名)
│   ├── bilibili_auth.py        # 登录认证（扫码/密码/Cookie）
│   ├── notification.py         # Windows 推送 + QQ Bot
│   ├── proxy_manager.py        # 代理管理器
│   ├── smart_alert.py          # 8 种异常检测器
│   └── database/               # SQLite（每视频独立库 + 中央库）
├── ui/                         # PyQt6 界面
│   ├── main_gui.py             # 主窗口（三栏布局 + 全局时钟）
│   ├── detail_panel.py         # 中间详情 + 图表
│   ├── prediction_panel.py     # 右侧预测面板
│   ├── video_list_panel.py     # 左侧视频列表
│   ├── chart.py                # QGraphicsView 趋势图
│   ├── theme.py                # 深色主题设计令牌
│   ├── dashboard_mode.py       # 看板大屏
│   ├── monitor/                # 监控服务 (per-video worker)
│   └── settings_*.py           # 各设置标签页
├── utils/                      # 工具模块
├── config/                     # 配置管理
└── data/                       # 运行时数据（不入 git）
```

## 界面布局

```
┌──────────────┬───────────────────┬──────────────┐
│  视频列表     │   详情 + 趋势图    │  预测面板     │
│  (22%)       │     (58%)         │   (20%)      │
│              │                   │              │
│  · 封面缩略图 │  · 播放量趋势      │  · 加权预测值  │
│  · BV号/标题  │  · 阈值辅助线      │  · 阈值进度    │
│  · 播放量     │  · 8 种指标切换    │  · 互动率      │
│  · 搜索过滤   │  · 详细数据/互动率  │  · 算法统计    │
│              │  · 弹幕显示        │  · 数据健康    │
└──────────────┴───────────────────┴──────────────┘
```

## 技术栈

| 组件 | 技术 |
|------|------|
| GUI | PyQt6 + QGraphicsView + QSS |
| 数据库 | SQLite3（WAL 模式，按 BV 分库 + 中央库） |
| 数据处理 | pandas, numpy, scipy |
| 机器学习 | scikit-learn, xgboost, lightgbm, catboost |
| 深度学习 | PyTorch 2.5+, HuggingFace Transformers |
| 推理加速 | CUDA / DirectML (Intel NPU) / XPU / MPS |
| 时间序列 | statsmodels, Prophet |
| 推送 | plyer (Windows), websockets (QQ Bot/OneBot) |
| LLM | OpenAI / DeepSeek / Claude / SiliconFlow API |

## 如何添加算法

算法采用**自动发现**机制，在 `algorithms/models/<类别>/` 下创建 `.py` 文件：

```python
from algorithms.base import BaseAlgorithm, PredictionResult

class MyAlgorithm(BaseAlgorithm):
    category = "时间序列"

    def predict(self, video_data, threshold, **kwargs) -> PredictionResult:
        ...
```

`AlgorithmRegistry` 启动时自动扫描并注册，无需手动配置。

## 开发命令

```bash
python main.py                    # 启动
black --line-length=120 .         # 格式化
flake8 .                          # 静态检查
bandit -r . -c pyproject.toml -ll # 安全扫描
radon cc -a .                     # 圈复杂度
pre-commit run --all-files        # 提交前检查
```

## 文档

- [CODE_REVIEW.md](CODE_REVIEW.md) — 最新代码审查报告
- [algorithms/ALGORITHMS.md](algorithms/ALGORITHMS.md) — 算法详细说明
- [CHANGELOG.md](CHANGELOG.md) — 版本更新日志
- [AGENTS.md](AGENTS.md) — AI 助理开发指南

## 注意事项

- 请合理使用 API，监控间隔建议 ≥5 分钟
- 预测结果仅供参考，实际播放量受多种因素影响
- QQ Bot 需自行搭建 OneBot 协议服务端
- LLM 功能需自行配置 API Key

## License

MIT
