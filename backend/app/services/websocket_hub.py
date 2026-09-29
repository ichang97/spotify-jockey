import asyncio
from typing import Dict, Set, Any
from fastapi import WebSocket


class WebSocketHub:
    def __init__(self) -> None:
        self._rooms: Dict[str, Set[WebSocket]] = {}
        self._now_playing: Dict[str, Dict[str, Any]] = {}
        self._ip_counts: Dict[str, int] = {}
        self._lock = asyncio.Lock()

    async def can_connect_ip(self, ip: str, max_connections: int = 100) -> bool:
        if not ip or ip in ("127.0.0.1", "localhost", "::1") or ip.startswith("172.") or ip.startswith("10.") or ip.startswith("192.168."):
            return True
        async with self._lock:
            return self._ip_counts.get(ip, 0) < max_connections

    async def connect(self, station_slug: str, websocket: WebSocket, client_ip: str = "127.0.0.1") -> None:
        await websocket.accept()
        async with self._lock:
            self._ip_counts[client_ip] = self._ip_counts.get(client_ip, 0) + 1
            if station_slug not in self._rooms:
                self._rooms[station_slug] = set()
            self._rooms[station_slug].add(websocket)

        if station_slug in self._now_playing:
            try:
                await websocket.send_json({
                    "type": "now_playing",
                    "data": self._now_playing[station_slug]
                })
            except Exception:
                pass

    async def disconnect(self, station_slug: str, websocket: WebSocket, client_ip: str = "127.0.0.1") -> None:
        async with self._lock:
            if client_ip in self._ip_counts:
                self._ip_counts[client_ip] -= 1
                if self._ip_counts[client_ip] <= 0:
                    del self._ip_counts[client_ip]

            if station_slug in self._rooms:
                self._rooms[station_slug].discard(websocket)
                if not self._rooms[station_slug]:
                    del self._rooms[station_slug]

    async def broadcast_to_station(self, station_slug: str, message: Dict[str, Any]) -> None:
        if message.get("type") == "now_playing":
            self._now_playing[station_slug] = message.get("data", {})

        connections = self._rooms.get(station_slug, set())
        if not connections:
            return

        dead_sockets = set()
        for ws in list(connections):
            try:
                await ws.send_json(message)
            except Exception:
                dead_sockets.add(ws)

        if dead_sockets:
            async with self._lock:
                for ds in dead_sockets:
                    connections.discard(ds)
                if not connections and station_slug in self._rooms:
                    del self._rooms[station_slug]

    def get_now_playing(self, station_slug: str) -> Dict[str, Any]:
        return self._now_playing.get(station_slug, {})


websocket_hub = WebSocketHub()
