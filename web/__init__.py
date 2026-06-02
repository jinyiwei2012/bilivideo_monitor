"""
Web 模块 —— REST API 服务器 + Web Dashboard

本模块提供基于 FastAPI 的 Web 服务，包含：
- REST API（/api/v1/ 前缀）：视频管理、数据查询、预测、用户认证
- WebSocket（/ws）：实时数据推送
- Web Dashboard（/）：Jinja2 模板渲染的管理面板
- 多用户认证（Bearer Token / API Key）
- CORS 跨域支持
"""
