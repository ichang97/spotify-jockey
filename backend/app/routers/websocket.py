import uuid
import json
from typing import Optional
from urllib.parse import urlparse
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query, status
from sqlalchemy import select
from app.config import get_settings
from app.database import async_session_factory
from app.models.station import Station
from app.services.audio_relay import audio_relay_service
from app.services.audio_mixer import audio_mixer_service
from app.services.websocket_hub import websocket_hub
from app.security import verify_dj_session_token

settings = get_settings()
router = APIRouter(tags=["WebSockets"])

ALLOWED_ORIGINS = {
    settings.FRONTEND_PUBLIC_URL.rstrip("/").lower(),
    settings.BACKEND_PUBLIC_URL.rstrip("/").lower(),
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost",
    "http://127.0.0.1",
    "https://localhost",
    "https://127.0.0.1",
}


def is_origin_allowed(origin: Optional[str], host: Optional[str]) -> bool:
    if not origin:
        return True
    clean_origin = origin.rstrip("/").lower()
    if clean_origin in ALLOWED_ORIGINS:
        return True
    if host:
        clean_host = host.lower()
        if clean_origin in (f"http://{clean_host}", f"https://{clean_host}"):
            return True
        if ":" in clean_host:
            host_without_port = clean_host.split(":")[0]
            if clean_origin in (f"http://{host_without_port}", f"https://{host_without_port}"):
                return True
    parsed = urlparse(clean_origin)
    if parsed.hostname in ("localhost", "127.0.0.1", "0.0.0.0"):
        return True
    if parsed.hostname and (
        parsed.hostname.startswith("192.168.")
        or parsed.hostname.startswith("10.")
        or parsed.hostname.startswith("172.")
    ):
        return True
    return False


@router.websocket("/ws/stations/{slug}")
async def station_events_websocket(websocket: WebSocket, slug: str):
    origin = websocket.headers.get("origin")
    host = websocket.headers.get("host")
    if not is_origin_allowed(origin, host):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Origin not allowed")
        return

    forwarded = websocket.headers.get("x-forwarded-for")
    if forwarded:
        client_ip = forwarded.split(",")[0].strip()
    elif websocket.client:
        client_ip = websocket.client.host
    else:
        client_ip = "127.0.0.1"

    if not await websocket_hub.can_connect_ip(client_ip):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Too many connections")
        return

    try:
        await websocket_hub.connect(slug, websocket, client_ip)
        while True:
            raw_data = await websocket.receive_text()
            try:
                msg = json.loads(raw_data)
                msg_type = msg.get("type")
                if msg_type == "now_playing":
                    token = msg.get("token")
                    if token and verify_dj_session_token(token, slug):
                        broadcast_payload = {
                            "type": "now_playing",
                            "data": msg.get("data", {})
                        }
                        await websocket_hub.broadcast_to_station(slug, broadcast_payload)
                elif msg_type == "ping":
                    await websocket.send_json({"type": "pong"})
            except json.JSONDecodeError:
                pass
    except (WebSocketDisconnect, Exception):
        pass
    finally:
        await websocket_hub.disconnect(slug, websocket, client_ip)


@router.websocket("/ws/audio/{slug}")
async def dj_audio_stream_websocket(
    websocket: WebSocket,
    slug: str,
    token: Optional[str] = Query(None)
):
    origin = websocket.headers.get("origin")
    host = websocket.headers.get("host")
    if not is_origin_allowed(origin, host):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Origin not allowed")
        return

    if not token or not verify_dj_session_token(token, slug):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Unauthorized DJ token")
        return

    await websocket.accept()
    dj_session_id = str(uuid.uuid4())
    await audio_relay_service.register_dj(slug, dj_session_id)

    async with async_session_factory() as db:
        stmt = select(Station).where(Station.slug == slug)
        res = await db.execute(stmt)
        station = res.scalar_one_or_none()
        if station:
            station.is_live = True
            await db.commit()

    await websocket_hub.broadcast_to_station(
        slug,
        {"type": "station_status", "data": {"is_live": True}}
    )

    try:
        while True:
            chunk = await websocket.receive_bytes()
            if chunk:
                if len(chunk) > 256 * 1024:
                    await websocket.close(code=status.WS_1009_MESSAGE_TOO_BIG, reason="Audio chunk too large")
                    break
                await audio_relay_service.broadcast_chunk(slug, chunk)
    except WebSocketDisconnect:
        pass
    finally:
        await audio_relay_service.unregister_dj(slug, dj_session_id)
        async with async_session_factory() as db:
            stmt = select(Station).where(Station.slug == slug)
            res = await db.execute(stmt)
            station = res.scalar_one_or_none()
            if station:
                station.is_live = False
                await db.commit()

        await websocket_hub.broadcast_to_station(
            slug,
            {"type": "station_status", "data": {"is_live": False}}
        )
