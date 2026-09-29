from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select
from app.config import get_settings
from app.database import engine, Base, async_session_factory
from app.models.station import Station
from app.models.auth import StationAuth
from app.services.librespot_service import librespot_service
from app.services.audio_mixer import audio_mixer_service
from app.security import hash_passcode
from app.migrations import run_migrations
from app.routers import (
    stations_router,
    auth_router,
    spotify_router,
    stream_router,
    requests_router,
    chat_router,
    websocket_router,
    queue_router,
)

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(run_migrations)

    async with async_session_factory() as db:
        stmt = select(Station.id).limit(1)
        res = await db.execute(stmt)
        if not res.first():
            default_station = Station(
                slug="main-stage",
                name="Main Stage Live",
                description="Default radio broadcast station powered by Spotify Jockey.",
                passcode_hash=hash_passcode("12345678"),
                palette_config={
                    "bg_base": "#0a0c10",
                    "bg_surface": "#13161f",
                    "bg_card": "#1c202b",
                    "border": "#2a3040",
                    "text_main": "#f8fafc",
                    "text_muted": "#94a3b8",
                    "accent": "#10b981",
                    "accent_hover": "#059669",
                    "live": "#ef4444"
                },
                is_live=False,
                current_listeners=0
            )
            db.add(default_station)
            await db.commit()


    yield

    for st_slug in list(librespot_service._processes.keys()):
        try:
            await audio_mixer_service.stop_mixer(st_slug)
            await librespot_service.stop_station_daemon(st_slug)
        except Exception:
            pass

    await engine.dispose()


app = FastAPI(
    title="Spotify Jockey Backend API",
    version="1.0.0",
    lifespan=lifespan
)

origins = [
    settings.FRONTEND_PUBLIC_URL.rstrip("/"),
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "https://localhost",
    "https://127.0.0.1",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

app.include_router(stations_router)
app.include_router(auth_router)
app.include_router(spotify_router)
app.include_router(stream_router)
app.include_router(requests_router)
app.include_router(chat_router)
app.include_router(websocket_router)
app.include_router(queue_router)


@app.get("/api/health")
async def health_check():
    return {"status": "ok", "service": "spotify-jockey-backend"}
