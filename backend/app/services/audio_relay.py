import asyncio
from typing import Dict, Set, AsyncGenerator, Optional


class AudioRelayService:
    def __init__(self) -> None:
        self._station_listeners: Dict[str, Set[asyncio.Queue[bytes]]] = {}
        self._station_active_dj: Dict[str, str] = {}
        self._station_headers: Dict[str, bytes] = {}
        self._station_header_accum: Dict[str, bytes] = {}
        self._station_header_events: Dict[str, asyncio.Event] = {}
        self._lock = asyncio.Lock()

    async def register_dj(self, station_slug: str, dj_session_id: str) -> bool:
        async with self._lock:
            self._station_active_dj[station_slug] = dj_session_id
            if station_slug not in self._station_listeners:
                self._station_listeners[station_slug] = set()
            self._station_headers.pop(station_slug, None)
            self._station_header_accum.pop(station_slug, None)
            self._station_header_events[station_slug] = asyncio.Event()
            return True

    async def unregister_dj(self, station_slug: str, dj_session_id: str) -> None:
        async with self._lock:
            if self._station_active_dj.get(station_slug) == dj_session_id:
                self._station_active_dj.pop(station_slug, None)
                self._station_headers.pop(station_slug, None)
                self._station_header_accum.pop(station_slug, None)
                self._station_header_events.pop(station_slug, None)
                listeners = self._station_listeners.get(station_slug, set())
                for q in list(listeners):
                    try:
                        q.put_nowait(b"")
                    except Exception:
                        pass

    async def broadcast_chunk(self, station_slug: str, chunk: bytes) -> None:
        if not chunk:
            return

        if station_slug not in self._station_headers:
            accum = self._station_header_accum.get(station_slug, b"") + chunk
            cluster_idx = accum.find(b"\x1f\x43\xb6\x75")
            if cluster_idx >= 0:
                header = accum[:cluster_idx]
                first_cluster = accum[cluster_idx:]
                self._station_headers[station_slug] = header
                self._station_header_accum.pop(station_slug, None)
                event = self._station_header_events.get(station_slug)
                if event:
                    event.set()
                chunk = first_cluster
            else:
                self._station_header_accum[station_slug] = accum
                return

        listeners = self._station_listeners.get(station_slug)
        if not listeners:
            return

        dead_queues = set()
        for q in list(listeners):
            try:
                if q.qsize() > 200:
                    try:
                        q.get_nowait()
                    except asyncio.QueueEmpty:
                        pass
                q.put_nowait(chunk)
            except Exception:
                dead_queues.add(q)

        if dead_queues:
            async with self._lock:
                for dq in dead_queues:
                    listeners.discard(dq)

    async def subscribe_listener(self, station_slug: str) -> AsyncGenerator[bytes, None]:
        q: asyncio.Queue[bytes] = asyncio.Queue(maxsize=250)
        async with self._lock:
            if station_slug not in self._station_listeners:
                self._station_listeners[station_slug] = set()
            self._station_listeners[station_slug].add(q)

        try:
            if station_slug not in self._station_headers:
                event = self._station_header_events.get(station_slug)
                if event:
                    try:
                        await asyncio.wait_for(event.wait(), timeout=5.0)
                    except asyncio.TimeoutError:
                        pass

            header = self._station_headers.get(station_slug)
            if header:
                yield header

            waiting_for_cluster = True
            while self.is_broadcasting(station_slug):
                try:
                    chunk = await asyncio.wait_for(q.get(), timeout=20.0)
                    if not chunk:
                        break
                    if waiting_for_cluster:
                        c_idx = chunk.find(b"\x1f\x43\xb6\x75")
                        if c_idx >= 0:
                            chunk = chunk[c_idx:]
                            waiting_for_cluster = False
                        else:
                            continue
                    yield chunk
                except asyncio.TimeoutError:
                    if not self.is_broadcasting(station_slug):
                        break
        except asyncio.CancelledError:
            pass
        finally:
            async with self._lock:
                if station_slug in self._station_listeners:
                    self._station_listeners[station_slug].discard(q)
                    if not self._station_listeners[station_slug] and not self.is_broadcasting(station_slug):
                        del self._station_listeners[station_slug]

    def get_listener_count(self, station_slug: str) -> int:
        return len(self._station_listeners.get(station_slug, set()))

    def is_broadcasting(self, station_slug: str) -> bool:
        return station_slug in self._station_active_dj


audio_relay_service = AudioRelayService()
