"""
WebSocket 连接管理器 —— 实时数据推送

管理所有活跃的 WebSocket 连接，支持：
- 多频道（channel）分组管理
- 广播推送（同一频道所有连接）
- 单点推送（向特定连接发送）
- 惰性清理死连接
- 连接数统计
"""

import asyncio
import json
import logging
from typing import Dict, Set
from fastapi import WebSocket

logger = logging.getLogger(__name__)


class WebSocketManager:
    """
    WebSocket 连接管理器。
    
    维护频道（channel）到连接集的映射，支持异步锁保护并发访问。
    死连接（发送失败）会被惰性清理。
    
    用法
    ----
    >>> await ws_manager.connect(websocket, channel="broadcast")
    >>> await ws_manager.broadcast({"type": "update", "data": {...}})
    >>> await ws_manager.disconnect(websocket)
    """

    def __init__(self):
        """初始化连接管理器：创建空的频道→连接映射和异步锁。"""
        self._connections: Dict[str, Set[WebSocket]] = {}  # channel → 连接集合
        self._lock = asyncio.Lock()  # 异步锁保护并发添加/清理

    async def connect(self, websocket: WebSocket, channel: str = "broadcast"):
        """
        接受 WebSocket 连接并加入指定频道。
        
        Args:
            websocket: FastAPI WebSocket 对象
            channel: 频道名称（默认 "broadcast" 广播频道）
        """
        await websocket.accept()
        async with self._lock:
            if channel not in self._connections:
                self._connections[channel] = set()
            self._connections[channel].add(websocket)
        logger.info("WebSocket 连接: channel=%s, total=%d", channel, len(self._connections.get(channel, set())))

    async def disconnect(self, websocket: WebSocket, channel: str = "broadcast"):
        """
        从指定频道移除 WebSocket 连接。
        
        如果移除后频道为空，则清理该频道的映射条目。
        
        Args:
            websocket: FastAPI WebSocket 对象
            channel: 频道名称
        """
        async with self._lock:
            if channel in self._connections:
                self._connections[channel].discard(websocket)
                if not self._connections[channel]:
                    del self._connections[channel]
        logger.info("WebSocket 断开: channel=%s", channel)

    async def broadcast(self, data: dict, channel: str = "broadcast"):
        """
        向指定频道的所有连接广播消息。
        
        发送失败的连接会被静默收集并在广播结束后清理。
        
        Args:
            data: 要发送的消息字典（自动转为 JSON）
            channel: 目标频道
        """
        connections = self._connections.get(channel, set()).copy()
        dead: Set[WebSocket] = set()
        for ws in connections:
            try:
                await ws.send_text(json.dumps(data, ensure_ascii=False))
            except Exception:
                dead.add(ws)  # 记录死连接，稍后统一清理
        if dead:
            async with self._lock:
                if channel in self._connections:
                    self._connections[channel] -= dead

    async def send_to(self, websocket: WebSocket, data: dict):
        """
        向单个连接发送消息。
        
        Args:
            websocket: 目标 WebSocket 对象
            data: 要发送的消息字典（自动转为 JSON）
        """
        try:
            await websocket.send_text(json.dumps(data, ensure_ascii=False))
        except Exception as e:
            logger.debug("WebSocket 发送失败: %s", e)

    @property
    def connection_count(self) -> int:
        """
        所有频道的活跃连接总数。
        
        Returns:
            int: 连接计数
        """
        return sum(len(v) for v in list(self._connections.values()))


# 全局 WebSocket 管理器单例
ws_manager = WebSocketManager()
