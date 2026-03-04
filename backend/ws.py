from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from typing import Dict, List
router = APIRouter()
class ConnectionManager:
    def __init__(self):
        self.active: Dict[int, List[WebSocket]] = {}
    async def connect(self, rid: int, websocket: WebSocket):
        await websocket.accept()
        self.active.setdefault(rid, []).append(websocket)
    def _cleanup(self, rid: int, websocket: WebSocket):
        if rid in self.active:
            try:
                self.active[rid].remove(websocket)
                if not self.active[rid]:
                    del self.active[rid]
            except ValueError:
                pass
    async def disconnect(self, rid: int, websocket: WebSocket):
        self._cleanup(rid, websocket)
    async def broadcast(self, rid: int, message: dict):
        for ws in list(self.active.get(rid, [])):
            try:
                await ws.send_json(message)
            except Exception:
                self._cleanup(rid, ws)
manager = ConnectionManager()
@router.websocket("/ws/restaurants/{rid}")
async def ws_restaurant(websocket: WebSocket, rid: int):
    await manager.connect(rid, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        await manager.disconnect(rid, websocket)