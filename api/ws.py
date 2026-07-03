"""WebSocket连接管理器：按任务ID分组推送进度"""

import asyncio
import json
from collections import defaultdict

from fastapi import WebSocket


class WSManager:
    """管理WebSocket连接，支持按任务ID推送消息"""

    def __init__(self) -> None:
        self._connections: dict[str, set[WebSocket]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def connect(self, task_id: str, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self._connections[task_id].add(ws)

    async def disconnect(self, task_id: str, ws: WebSocket) -> None:
        async with self._lock:
            self._connections[task_id].discard(ws)
            if not self._connections[task_id]:
                self._connections.pop(task_id, None)

    async def broadcast(self, task_id: str, message: dict) -> None:
        """向指定任务的所有连接推送消息"""
        conns = list(self._connections.get(task_id, set()))
        text = json.dumps(message, ensure_ascii=False)
        for ws in conns:
            try:
                await ws.send_text(text)
            except Exception:
                await self.disconnect(task_id, ws)


ws_manager = WSManager()
