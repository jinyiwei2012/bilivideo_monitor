# 更新日志

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
