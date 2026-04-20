# B站视频监控与播放量预测系统

基于 Tkinter 的 B站视频数据监控与播放量预测桌面应用，集成 40+ 种预测算法，支持 Windows 原生推送和 QQ Bot 推送。

## 功能特性

### 核心功能
- **视频搜索**: 关键词搜索B站视频，支持多关键词批量搜索与自动去重
- **数据监控**: 实时监控播放量、点赞、投币、弹幕、在线观看人数等指标
- **播放量预测**: 40+ 种算法预测到达 10万 / 100万 / 1000万 播放量所需时间
- **算法权重管理**: ML 权重自动调整，支持算法计数与失败数追踪
- **阈值推送**: 视频突破播放量阈值时自动推送通知
- **数据对比**: 2-5 个视频在同一图表上对比播放量趋势
- **交叉计算**: 分析多个视频播放量交会时间和预测
- **数据库查询**: 本地历史数据的可视化查询工具
- **数据导出**: 支持 CSV / JSON 导出

### 预测算法（40+）

| 类别 | 算法 |
|------|------|
| 基础速度 | 线性速度、近期速度、加权速度、分享速度、点赞动量 |
| 时间衰减 | 指数衰减、对数增长、幂律增长 |
| 增长模型 | Gompertz、Logistic、Richards、Bass 扩散、Weibull |
| 机器学习 | 神经网络、LSTM、MLP、SVR、随机森林、XGBoost、CatBoost、LightGBM |
| 集成模型 | 加权集成、投票集成、堆叠集成、均值集成 |
| 时间序列 | ARIMA、指数平滑、Holt-Winters、季节分解 |
| 统计模型 | 高斯过程、贝叶斯回归、卡尔曼滤波 |
| 特色分析 | 病毒潜力、质量评分、互动率、评论趋势 |

详细说明参见 [algorithms/ALGORITHMS.md](algorithms/ALGORITHMS.md)

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
│   ├── manager.py              # 算法管理器
│   ├── weight_manager.py       # 权重管理（ML 自动调整）
│   ├── model_adapter.py        # 模型适配层
│   ├── ALGORITHMS.md           # 算法详细文档
│   └── models/                 # 40+ 种算法实现
│
├── config/                     # 配置模块
│
├── core/                       # 核心模块
│   ├── database.py             # SQLite 数据库操作
│   ├── bilibili_api.py         # B站 API 封装
│   └── notification.py         # 通知管理
│
├── ui/                         # 界面模块
│   ├── main_gui.py             # 主界面
│   ├── settings_window.py      # 系统设置
│   ├── video_search.py         # 视频搜索
│   ├── crossover_analysis.py   # 交叉分析
│   ├── data_comparison.py      # 数据对比
│   ├── database_query.py       # 数据库查询
│   ├── weight_settings.py      # 权重设置
│   └── network_settings.py     # 网络设置
│
├── utils/                      # 工具模块
│   ├── helpers.py              # 辅助函数
│   ├── exporters.py            # 导出工具
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
2. 选择 2-5 个已监控视频
3. 同一图表对比播放量趋势

### QQ Bot 配置
1. 部署 OneBot 协议实现（如 go-cqhttp、LLOneBot）
2. 设置 → 系统设置 → OneBot 配置 HTTP / WS 地址
3. 填写推送目标 QQ 号或群号
4. 点击「测试连接」验证

## 技术栈

| 组件 | 技术 |
|------|------|
| GUI | tkinter + ttkbootstrap |
| 数据库 | SQLite3（按视频分库存储） |
| 数据处理 | pandas, numpy, scipy |
| 机器学习 | scikit-learn, xgboost, lightgbm, statsmodels, prophet |
| 推送 | plyer（Windows）, websockets（QQ Bot） |
| 可视化 | matplotlib, seaborn |

## 注意事项

- 请合理使用 API，监控间隔建议 5 分钟以上
- 预测结果仅供参考，实际播放量受多种因素影响
- QQ Bot 需自行搭建 OneBot 协议服务端
- 数据库文件按 BV 号独立存储在 `data/` 下

## License

MIT License
