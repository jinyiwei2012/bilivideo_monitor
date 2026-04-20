# B站视频监控与播放量预测系统

一个功能完整的B站视频数据监控和播放量预测GUI应用，支持40+种预测算法，Windows原生推送和QQ Bot推送。

## 功能特性

### 核心功能
- **视频搜索**: 支持关键词搜索B站视频，多关键词批量搜索，自动去重
- **数据监控**: 实时监控视频播放量、点赞、投币、弹幕、在线观看人数等数据
- **播放量预测**: 使用40+种算法预测到达10万/100万/1000万播放量所需时间
- **阈值推送**: 当视频突破播放量阈值时自动推送通知
- **交叉计算**: 分析多个视频播放量交会时间和预测
- **数据导出**: 支持CSV/JSON导出，按BV号命名文件

### 数据记录
- **观看人数**: 记录APP端、网页端、总观看人数
- **视频封面**: 自动下载保存到 `data/cover/` 目录
- **播赞比**: 自动计算并记录点赞/播放比例
- **预测记录**: 记录各算法的预测时间和实际到达时间
- **历史数据**: 完整的监控历史记录

### 推送功能
- **Windows原生通知**: 系统级通知弹窗
- **QQ Bot推送**: 支持OneBot协议，可推送到私聊或群聊

### 数据管理
- **SQLite数据库**: 本地存储所有数据
- **自动导出**: 搜索完成后自动导出CSV
- **历史记录**: 保存监控历史，支持趋势分析
- **封面管理**: 自动下载并管理视频封面

## 安装说明

### 环境要求
- Windows 10/11
- Python 3.10+
- Conda (推荐)

### 安装步骤

1. **创建Conda环境**
```bash
conda create -n bilibili python=3.10
conda activate bilibili
```

2. **安装依赖**
```bash
pip install -r requirements.txt
```

3. **启动程序**
- 双击 `start.bat` 或 `start.ps1`
- 或在命令行运行:
```bash
conda activate bilibili
python main.py
```

## 项目结构

```
b站监控/
├── main.py                    # 主入口文件
├── README.md                  # 项目说明
├── requirements.txt           # Python依赖
│
├── algorithms/                # 预测算法模块
│   ├── __init__.py
│   ├── base.py               # 算法基类
│   ├── manager.py            # 算法管理器
│   ├── ALGORITHMS.md         # 算法详细说明
│   └── models/               # 40+种算法实现
│
├── config/                    # 配置模块
│   └── __init__.py           # 配置和常量定义
│
├── core/                      # 核心模块
│   ├── __init__.py
│   ├── database.py           # 数据库操作（增强版）
│   ├── bilibili_api.py       # B站API封装（含观看人数）
│   └── notification.py       # 通知管理
│
├── ui/                        # 界面模块
│   ├── __init__.py
│   ├── main_gui.py           # 主GUI界面
│   ├── settings_window.py    # 系统设置界面
│   ├── video_search.py       # 视频搜索界面
│   ├── crossover_analysis.py # 交叉计算界面
│   └── data_comparison.py    # 数据对比界面
│
├── utils/                     # 工具模块
│   ├── __init__.py
│   ├── helpers.py            # 辅助函数
│   └── exporters.py          # 导出工具
│
├── data/                      # 数据目录
│   ├── bilibili_monitor.db   # SQLite数据库
│   ├── cover/                # 视频封面（按BV号存储）
│   ├── settings.json         # 配置文件
│   └── exports/              # 导出文件
│
└── exports/                   # 导出目录（按BV号命名）
```

## 使用说明

### 添加视频监控
1. **搜索添加**: 点击"工具"→"视频搜索"，输入关键词搜索并选择视频
2. **BV号添加**: 在主界面直接输入BV号，点击"添加监控"
3. **批量导入**: 在视频搜索界面选择多个视频批量导入

### 查看预测
1. 在左侧列表选择视频
2. 右侧显示当前播放量数据（含观看人数）
3. 预测面板显示到达各阈值的时间
4. 可选择不同算法查看预测结果
5. 点击"算法对比"查看所有算法预测对比

### 播放量交叉计算
1. 点击"工具"→"播放量交叉计算"
2. 选择2-5个视频进行对比
3. 查看交会点预测和趋势图
4. 导出详细分析报告

### 推送设置
1. **Windows通知**: 默认开启，突破阈值时显示系统通知
2. **QQ Bot**: 点击"设置"→"系统设置"配置OneBot协议

### QQ Bot配置
1. 安装OneBot协议实现的QQ Bot (如go-cqhttp, LLOneBot)
2. 在"系统设置"→"OneBot设置"中配置：
   - HTTP地址 (默认: http://127.0.0.1:5700)
   - WebSocket地址 (默认: ws://127.0.0.1:6700)
   - 访问令牌（如有）
3. 设置推送目标QQ号或群号
4. 点击"测试连接"验证配置

### 数据导出
- **自动导出**: 视频搜索完成后自动导出CSV
- **命名格式**: `{BV号}.csv` 或 `{BV号}.json`
- **导出内容**: 视频详情、历史记录、预测结果
- **导出路径**: `data/exports/` 或自定义路径

## 数据库结构

### videos表 - 视频信息
| 字段 | 说明 |
|------|------|
| bvid | BV号（主键） |
| title | 视频标题 |
| view_count | 播放量 |
| like_count | 点赞数 |
| viewers_app | APP端观看人数 |
| viewers_web | 网页端观看人数 |
| viewers_total | 总观看人数 |
| cover_path | 封面本地路径 |
| like_view_ratio | 播赞比 |

### monitor_records表 - 监控记录
| 字段 | 说明 |
|------|------|
| bvid | BV号 |
| timestamp | 记录时间 |
| view_count | 播放量 |
| viewers_app/web/total | 观看人数 |
| like_view_ratio | 播赞比 |

### predictions表 - 预测记录
| 字段 | 说明 |
|------|------|
| bvid | BV号 |
| algorithm | 算法名称 |
| algorithm_id | 算法ID |
| target_threshold | 目标阈值 |
| predicted_seconds | 预测所需秒数 |
| predicted_time | 预测到达时间 |
| is_reached | 是否已到达 |
| actual_time | 实际到达时间 |
| error_rate | 预测误差率 |

## 阈值说明

| 阈值 | 名称 | 说明 |
|------|------|------|
| 10万 | 小热门 | 有一定传播度的视频 |
| 100万 | 热门视频 | 优质内容，推荐度高 |
| 1000万 | 爆款视频 | 现象级传播内容 |

## 算法说明

系统包含40+种预测算法，分为以下类别：

1. **基础速度模型**: 线性速度、近期速度、加权速度
2. **时间衰减模型**: 指数衰减、对数增长、幂律增长
3. **扩散模型**: Bass扩散模型、Gompertz增长、Logistic增长
4. **机器学习模型**: 神经网络、LSTM、随机森林、XGBoost
5. **集成模型**: 加权集成、投票集成、堆叠集成
6. **时间序列模型**: ARIMA、指数平滑、Holt-Winters
7. **统计模型**: 高斯过程、贝叶斯回归、卡尔曼滤波

详细算法说明请参考: [algorithms/ALGORITHMS.md](algorithms/ALGORITHMS.md)

## 注意事项

1. 请合理使用API，避免频繁请求
2. 监控间隔建议设置为5分钟以上
3. 预测结果仅供参考，实际播放量受多种因素影响
4. QQ Bot需要自行搭建OneBot协议服务端
5. 封面图片保存在 `data/cover/` 目录，以BV号命名

## 技术栈

- **GUI**: tkinter + ttkbootstrap
- **数据库**: SQLite3
- **数据处理**: pandas, numpy
- **机器学习**: scikit-learn, statsmodels, tensorflow
- **推送**: plyer (Windows), websockets (QQ Bot)
- **可视化**: matplotlib

## License

MIT License
