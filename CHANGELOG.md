# 更新日志

## Release 2026-05-20 (v2.4.0)

### ✨ 新功能
- **PyTorch 训练基础设施**: 新增 `algorithms/training/` 模块
  - `device.py`: GPU 自动检测（CUDA > MPS > CPU），支持 `force_cpu()` 全局开关
  - `checkpoint_manager.py`: 多版本 checkpoint 管理，支持 `list_versions / save / load / activate / delete`，目录结构 `algorithms/checkpoints/<algo_id>/v<N>_<时间戳>.pt`
  - `dataset.py`: `VideoTimeSeriesDataset` 从每视频 SQLite DB 滑动窗口加载，支持全局训练 + 指定视频微调两种模式
  - `trainer.py`: 通用训练管线 `ModelTrainer.train_global / finetune_for_video / estimate_data_size`，z-score 归一化 + 单步速度差分作为训练目标
  - `hf_loader.py`: HuggingFace Foundation 模型懒加载（MOIRAI / Lag-Llama），首次自动下载缓存
- **8 个 2026 前沿预测算法**:
  - `moirai`: Salesforce MOIRAI-1.1-R-small，HF 通用时序基座
  - `lag_llama`: time-series-foundation-models/Lag-Llama，lag-feature 加权预测
  - `knf`: Koopman Neural Forecaster（全局算子 + 局部低秩修正 + meta 网络）
  - `diffusion_ts`: 简化 DDPM + UNet1D，100 步反向扩散采样
  - `mar_bilstm`: BiLSTM + 可学习 Markov 转移矩阵，5 状态混合输出
  - `cnn_image`: 时序数据展平成 2D 图像，双分支 Conv2d（kernel=3 dilation=1/2）
  - `tsfc_classification`（统计模型）: sklearn `RandomForestClassifier`，弱标签 5 桶（decay/slow/steady/growing/viral）
  - `distdf_align`（高级分析）: scipy `wasserstein_distance` 度量分布漂移，自适应 α 加权
- **14 个既有深度学习算法升级为真实 PyTorch 实现**:
  - 升级文件: `attention_mechanism`, `bilstm_simple`, `cnn_lstm_hybrid`, `dlinear_simple`, `gru_simple`, `informer_simple`, `lstm_simple`, `mlp_predictor`, `n_beats_simple`, `neural_network_simple`, `patch_tst_simple`, `tcn_simple`, `tft_simple`, `timess_net_simple`
  - 新增统一辅助模块 `algorithms/models/deep_learning/_torch_upgrade.py`，包含 13 个 torch 模型类 + `try_torch_predict()` 调度
  - **三级优雅降级链**: torch checkpoint 推理 → numpy 简化版 → 速度估算兜底
  - 保留原 numpy 简化实现作为 `_numpy_predict`，无 checkpoint 或推理失败时无缝降级，行为完全向后兼容
- **设置窗口新增「模型训练」分页** (`ui/settings_window.py`):
  - **训练设备**: 实时显示 CUDA/MPS/CPU 设备名 + 显存容量 + "强制使用 CPU" 开关
  - **数据规模**: 后台估算视频总数 / 训练样本数 / 预计单算法训练时间
  - **可训练算法列表**: 自动发现 18 个 torch 算法（14 升级 + 4 新增本地训练），显示算法名/ID/checkpoint 状态/版本数，支持 全选 / 全不选 / 仅选未训练
  - **训练控制**: Epoch/Batch 可调，实时进度条 + 每 epoch loss + ETA，支持取消（算法间隙生效）
  - **版本管理弹窗**: 每个算法独立 Treeview 显示所有版本，支持 激活 / 删除 / 导出 .pt
  - 后台 `threading.Thread` + `queue.Queue` 异步训练，主线程 `window.after` 轮询，不阻塞 UI

### 🔧 优化
- **新依赖** (`requirements.txt`): torch>=2.1.0、transformers>=4.40.0、huggingface-hub>=0.20.0、safetensors>=0.4.0；CPU/GPU 安装方式见 README
- **.gitignore**: 排除 `algorithms/checkpoints/*/`（保留 `README.md`）、`*.pt`、`*.pkl` 避免大文件入库
- **算法总数 75 → 83**: 8 个 2026 新算法增量加入，自动发现机制无需修改注册器

### 🐛 修复
- **U+0001 控制字符污染**: Phase 3 批量升级脚本中 regex backreference `\1` 误写入文件，导致 11 个 deep_learning 算法 import 失败，算法总数从 83 跌至 72；已用清理脚本去除控制字符并恢复

### 📐 架构
- **`BaseAlgorithm` 接口兼容**: `mlp_predictor` / `attention_mechanism` 保持原 full_params 签名 `predict(current_views, target_views, history_data, video_info) -> Optional[Tuple[int, float]]`，通过内部 `_try_torch_predict` 包装为统一调度路径
- **Foundation 模型懒加载**: MOIRAI / Lag-Llama 首次预测时自动从 HuggingFace 下载（`~/.cache/huggingface/`），不阻塞应用启动

## Release 2026-05-19 (v2.3.0)

### ✨ 新功能
- **图表"新增"模式（默认）**: 新增第三种图表模式 `step`，绘制每两次刷新之间的播放量增量（`v[i] - v[i-1]`）折线图，0 基线，正增量绿点 / 负增量红点；右上角实时统计「N 点 | 总+X | 均+Y」
- **新增模式自动刷新 + 其他模式手动渲染**: 默认进入「新增」模式自动跟随数据刷新；切到「增量」/「全量」需点击「渲染」按钮才绘制，避免重数据下的卡顿
- **渲染门控防绕过**: 新增 `_rendered_modes` 集合追踪已手动渲染过的模式；窗口 resize 不会绕过"手动点击"门控自动重绘 delta/full

### 🔧 优化
- **图表代码拆分**: `_draw_step_chart` 拆为 `_step_compute_scale` / `_step_draw_grid` / `_step_draw_series` 三个职责单一的子函数，圈复杂度从 16 降至 15 以下，符合 flake8 `max-complexity=15` 约束
- **切换 tab/视频自动清图**: 切回趋势 tab 或切换视频时，若当前为非自动模式（增量/全量）则清除旧图显示占位提示（"点击「渲染XX」查看…"），避免显示其他视频的残留数据

## Release 2026-05-11 (v2.2.0)

### ✨ 新功能
- **图表增量/全量模式**: 新增增量模式（以起始播放量为基准归零，仅显示增长量）和全量模式（显示绝对值），图表明细中可切换
- **图表显示点数可配置**: 新增"显示 X 点"输入框，默认 20 点，固定间隔均匀取点（替代原来固定 8 点的硬编码）
- **全量模式手动渲染**: 全量模式下不自动重绘，点击「渲染全量」按钮后手动触发，避免密集数据时卡顿

### 🔧 优化
- **UI自适应缩放**: 主界面改为 grid 比例布局（22/58/20），所有对话框窗口使用屏幕百分比尺寸，标题/封面自适应折行
- **拉取后 UI 卡死修复**: 移除旧 `_on_single_fetch_done` 回调（与 Worker 的 `_on_fetch_done` 重复调用，导致每次拉取做两次预测 + 两次图表绘制）；Worker 新增 `_fetching` 并发锁防止同一视频重复拉取；`_predict_single` 新增 `_prediction_semaphore(2)` 限制并发预测数量，防止 GIL 饥饿

### 🐛 修复
- **预测时间缺少年份**: ETA 显示从 `%m-%d %H:%M` 改为 `%Y-%m-%d %H:%M`，避免跨年混淆
- **图表时间标签缺月份**: 时间轴从 `%H:%M` 改为 `%m-%d %H:%M`，跨天数据可识别日期

## Release 2026-05-11 (v2.1.0)

### 🔧 优化
- **sync_to_central 性能**: 从 4.5-5s 降至 0.5s（后续同步），预测同步改用 COUNT(DISTINCT)快速检查 + GROUP BY 去重避免全表扫描
- **拉取数据后 UI 卡顿修复**: 中央库同步 `sync_from_video_db` 从主线程回调移入工作线程，消除 UI 阻塞；图表重绘添加 100ms 防抖
- **索引优化**: 新增 `idx_predictions_bvid` 索引加速 predictions 表按 bvid 查询

### 🐛 修复
- **predictions 未同步 created_at**: INSERT 时携带 created_at 确保后续 MAX(created_at) 比较正确
- **多 Worker 同时完成时的 UI 卡顿**: `_on_fetch_done` 图表重绘防抖合并，避免重复 Canvas 操作


## Release 2026-05-10

### ✨ 新功能
- **UP主追踪多源获取**: 新增 `core/up_fetcher.py`，整合 bilibili-api-python / curl_cffi / 自有 API 三层独立数据源，避免单一接口 412 限制导致完全不可用
- **设置窗口 - 关于作者**: 新增"关于作者"标签页，包含项目信息、版本号、GitHub 仓库链接、B站主页链接（点击浏览器跳转）
- **封面管理器**: 封面图片自动本地缓存（data/cover/），MD5 完整性校验，损坏自动重下载，文件命名格式 `{bvid}_{title}.jpg`

### 🔧 优化
- **README 全面更新**: 项目结构补充缺失文件（cover_manager.py、proxy_manager.py、smart_alert.py 等）、算法计数修正、数据路径修正
- **算法计数修正**: `__init__.py` 元数据 40+ → 75 种算法
- **PyInstaller 打包**: 从 onefile 改为 onedir 模式，运行时文件（data/、config/）暴露在 exe 同级目录

### 🐛 修复
- **UP主追踪 412 限制**: `get_up_info`/`get_up_stat`/`search_up_users` 改为多源轮询，任意源成功即返回
- **公共请求代理支持**: `_request_public` 增加代理绑定，使无 Cookie 请求也能走代理轮换
- **资源泄露修复**: 数据库连接池正确释放
- **代理 SSL 验证**: SOCKS5 代理关闭 SSL 验证避免自签名证书报错
- **代理批量导入**: 支持多行代理粘贴导入


## Release 2026-05-05

### ✨ 新功能
- **代理模块化**: 提取独立 `ProxyManager` 类，支持代理轮询、UA 绑定、可用性检测、失败自动剔除
- **代理测试 UI**: 测试代理时显示出口 IP 并记录日志
- **AI 多配置管理**: 支持 OpenAI / DeepSeek / Claude / SiliconFlow 等多配置切换

### 🔧 优化
- **配置统一**: 所有配置文件迁移至 `data/` 目录（settings.json、network_config.json）
- **设置窗口合并**: 网络设置（代理/Cookie/扫码登录）合并至统一设置窗口
- **日志系统**: 网络请求输出 DEBUG 级别日志
- **代码合规**: Black 格式化、Flake8/MyPy/Bandit/Radon 全量合规修复
- **主题精简**: 移除昼夜切换功能，固定亮色主题

### 🐛 修复
- **412 错误重试**: 指数退避 + 抖动，自动切换代理和 UA
- **代理日志**: `core.proxy_manager` 日志接入系统日志面板
- **代理测试**: 超时处理、ASN 解析异常、失败原因高亮显示
- **Cookie 登录**: 支持自动识别格式并同步登录状态
- **资源泄露**: 数据库 WAL 模式定时检查


## Release 2026-04-30

### ✨ 新功能
- **75 种预测算法**: 基础速度、增长模型、时间序列、深度学习、统计模型、集成学习、高级分析等
- **算法权重管理**: ML 权重自动调整（含 Hedge 在线学习算法）
- **LLM 集成**: 弹幕智能分析（情感/关键词）、历史问答
- **看板模式**: 多视频关键指标一览面板
- **里程碑统计**: 多视频多周期柱状对比
- **数据对比**: 趋势折线图 + 快照柱状图
- **交叉计算**: 多视频播放量交会预测

### 🔧 优化
- 算法自动发现机制：放在 `models/` 下即可自动注册
- 每视频独立线程 + 独立数据库
- CustomTkinter 现代化 UI
