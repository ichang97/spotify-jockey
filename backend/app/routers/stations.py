import secrets
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Header, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.models.station import Station
from app.models.auth import StationAuth
from app.schemas.station import (
    StationCreate,
    StationUpdate,
    StationResponse,
    StationAuthVerify,
    StationAuthToken,
)
from app.security import (
    hash_passcode,
    verify_passcode,
    create_dj_session_token,
    verify_dj_session_token,
)
from app.services.rate_limiter import rate_limit
from app.services.websocket_hub import websocket_hub

router = APIRouter(prefix="/api/stations", tags=["Stations"])

RESERVED_SLUGS = {
    "admin",
    "api",
    "auth",
    "login",
    "studio",
    "live",
    "settings",
    "stations",
    "static",
    "ws",
    "stream",
    "public",
    "health"
}


async def verify_dj_session(slug: str, authorization: Optional[str] = Header(None)) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid DJ session token"
        )
    token = authorization.split(" ", 1)[1].strip()
    if not verify_dj_session_token(token, slug):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired DJ session token"
        )
    return slug


@router.get("", response_model=List[StationResponse])
async def list_stations(db: AsyncSession = Depends(get_db)):
    stmt = (
        select(
            Station.id,
            Station.slug,
            Station.name,
            Station.description,
            Station.palette_config,
            Station.is_live,
            Station.current_listeners,
            Station.created_at,
            Station.passcode_hash,
            StationAuth.id.label("auth_id")
        )
        .outerjoin(StationAuth, Station.id == StationAuth.station_id)
        .order_by(Station.created_at.desc())
    )
    result = await db.execute(stmt)
    rows = result.all()

    stations_list = []
    for row in rows:
        stations_list.append(
            StationResponse(
                id=row.id,
                slug=row.slug,
                name=row.name,
                description=row.description,
                palette_config=row.palette_config,
                is_live=row.is_live,
                current_listeners=row.current_listeners,
                created_at=row.created_at,
                is_spotify_connected=bool(row.auth_id),
                has_passcode=bool(row.passcode_hash)
            )
        )
    return stations_list


@router.get("/{slug}", response_model=StationResponse)
async def get_station(slug: str, db: AsyncSession = Depends(get_db)):
    stmt = (
        select(
            Station.id,
            Station.slug,
            Station.name,
            Station.description,
            Station.palette_config,
            Station.is_live,
            Station.current_listeners,
            Station.created_at,
            Station.passcode_hash,
            StationAuth.id.label("auth_id")
        )
        .outerjoin(StationAuth, Station.id == StationAuth.station_id)
        .where(Station.slug == slug)
    )
    result = await db.execute(stmt)
    row = result.first()
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Station not found"
        )

    return StationResponse(
        id=row.id,
        slug=row.slug,
        name=row.name,
        description=row.description,
        palette_config=row.palette_config,
        is_live=row.is_live,
        current_listeners=row.current_listeners,
        created_at=row.created_at,
        is_spotify_connected=bool(row.auth_id),
        has_passcode=bool(row.passcode_hash)
    )


@router.post(
    "",
    response_model=StationResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit(max_requests=5, window_seconds=3600))]
)
async def create_station(station_in: StationCreate, db: AsyncSession = Depends(get_db)):
    clean_slug = station_in.slug.lower().strip()
    if clean_slug in RESERVED_SLUGS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"The slug '{clean_slug}' is reserved by the system."
        )

    check_stmt = select(Station.id).where(Station.slug == clean_slug)
    existing = await db.execute(check_stmt)
    if existing.first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Station slug already exists"
        )

    passcode = station_in.passcode if station_in.passcode else secrets.token_hex(4)
    hashed_passcode = hash_passcode(passcode)

    new_station = Station(
        slug=clean_slug,
        name=station_in.name,
        description=station_in.description,
        passcode_hash=hashed_passcode,
        palette_config=station_in.palette_config.model_dump(),
        is_live=False,
        current_listeners=0
    )
    db.add(new_station)
    await db.commit()
    await db.refresh(new_station)

    return StationResponse(
        id=new_station.id,
        slug=new_station.slug,
        name=new_station.name,
        description=new_station.description,
        palette_config=new_station.palette_config,
        is_live=new_station.is_live,
        current_listeners=new_station.current_listeners,
        created_at=new_station.created_at,
        is_spotify_connected=False,
        has_passcode=True
    )


@router.post(
    "/{slug}/auth/verify",
    response_model=StationAuthToken,
    dependencies=[Depends(rate_limit(max_requests=5, window_seconds=60))]
)
async def verify_station_passcode(
    slug: str,
    auth_in: StationAuthVerify,
    db: AsyncSession = Depends(get_db)
):
    stmt = select(Station.passcode_hash).where(Station.slug == slug)
    res = await db.execute(stmt)
    row = res.first()
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Station not found"
        )

    stored_hash = row[0]
    if not verify_passcode(auth_in.passcode, stored_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid station passcode"
        )

    token = create_dj_session_token(slug, expires_in_seconds=86400)
    return StationAuthToken(token=token, expires_in=86400)


@router.patch("/{slug}", response_model=StationResponse)
async def update_station(
    slug: str,
    station_in: StationUpdate,
    _=Depends(verify_dj_session),
    db: AsyncSession = Depends(get_db)
):
    stmt = select(Station).where(Station.slug == slug)
    result = await db.execute(stmt)
    station = result.scalar_one_or_none()
    if not station:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Station not found"
        )

    if station_in.name is not None:
        station.name = station_in.name
    if station_in.description is not None:
        station.description = station_in.description
    if station_in.palette_config is not None:
        station.palette_config = station_in.palette_config.model_dump()
    if station_in.is_live is not None:
        station.is_live = station_in.is_live
    if station_in.passcode is not None:
        station.passcode_hash = hash_passcode(station_in.passcode)

    await db.commit()
    await db.refresh(station)

    auth_stmt = select(StationAuth.id).where(StationAuth.station_id == station.id)
    auth_res = await db.execute(auth_stmt)
    is_connected = bool(auth_res.first())

    return StationResponse(
        id=station.id,
        slug=station.slug,
        name=station.name,
        description=station.description,
        palette_config=station.palette_config,
        is_live=station.is_live,
        current_listeners=station.current_listeners,
        created_at=station.created_at,
        is_spotify_connected=is_connected,
        has_passcode=bool(station.passcode_hash)
    )


@router.delete("/{slug}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_station(
    slug: str,
    _=Depends(verify_dj_session),
    db: AsyncSession = Depends(get_db)
):
    stmt = select(Station).where(Station.slug == slug)
    result = await db.execute(stmt)
    station = result.scalar_one_or_none()
    if not station:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Station not found"
        )

    await db.delete(station)
    await db.commit()
    await websocket_hub.broadcast_to_station(
        slug,
        {"type": "station_status", "data": {"is_live": False, "deleted": True}}
    )
    return None
