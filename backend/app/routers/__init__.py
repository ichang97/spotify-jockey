from app.routers.stations import router as stations_router
from app.routers.auth import router as auth_router
from app.routers.spotify import router as spotify_router
from app.routers.stream import router as stream_router
from app.routers.requests import router as requests_router
from app.routers.chat import router as chat_router
from app.routers.websocket import router as websocket_router
from app.routers.queue import router as queue_router

__all__ = [
    "stations_router",
    "auth_router",
    "spotify_router",
    "stream_router",
    "requests_router",
    "chat_router",
    "websocket_router",
    "queue_router",
]
