"""WebSocket 连接管理器 —— 实时数据推送"""

import asyncio
import json
import logging
from typing import Dict, Set
from fastapi import WebSocket

logger = logging.getLogger(__name__)


class WebSocketManager:
    def __init__(self):
        self._connections: Dict[str, Set[WebSocket]] = {}
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket, channel: str = "broadcast"):
        await websocket.accept()
        async with self._lock:
            if channel not in self._connections:
                self._connections[channel] = set()
            self._connections[channel].add(websocket)
        logger.info("WebSocket 连接: channel=%s, total=%d", channel, len(self._connections.get(channel, set())))

    async def disconnect(self, websocket: WebSocket, channel: str = "broadcast"):
        async with self._lock:
            if channel in self._connections:
                self._connections[channel].discard(websocket)
                if not self._connections[channel]:
                    del self._connections[channel]
        logger.info("WebSocket 断开: channel=%s", channel)

    async def broadcast(self, data: dict, channel: str = "broadcast"):
        connections = self._connections.get(channel, set()).copy()
        dead: Set[WebSocket] = set()
        for ws in connections:
            try:
                await ws.send_text(json.dumps(data, ensure_ascii=False))
            except Exception:
                dead.add(ws)
        if dead:
            async with self._lock:
                if channel in self._connections:
                    self._connections[channel] -= dead

    async def send_to(self, websocket: WebSocket, data: dict):
        try:
            await websocket.send_text(json.dumps(data, ensure_ascii=False))
        except Exception as e:
            logger.debug("WebSocket 发送失败: %s", e)

    @property
    def connection_count(self) -> int:
        return sum(len(v) for v in list(self._connections.values()))


ws_manager = WebSocketManager()
