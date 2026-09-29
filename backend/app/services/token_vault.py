from datetime import datetime, timezone
from typing import Optional, Tuple
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.auth import StationAuth
from app.security import encrypt_token, decrypt_token


class TokenVaultService:
    @staticmethod
    async def get_station_tokens(
        db: AsyncSession,
        station_id: int
    ) -> Optional[Tuple[str, str, Optional[datetime]]]:
        stmt = (
            select(
                StationAuth.encrypted_access_token,
                StationAuth.encrypted_refresh_token,
                StationAuth.token_expires_at
            )
            .where(StationAuth.station_id == station_id)
        )
        result = await db.execute(stmt)
        row = result.first()
        if not row:
            return None

        access_token = decrypt_token(row[0])
        refresh_token = decrypt_token(row[1])
        expires_at = row[2]
        return access_token, refresh_token, expires_at

    @staticmethod
    async def save_station_tokens(
        db: AsyncSession,
        station_id: int,
        access_token: str,
        refresh_token: str,
        expires_at: Optional[datetime] = None,
        spotify_user_id: Optional[str] = None
    ) -> None:
        stmt = select(StationAuth).where(StationAuth.station_id == station_id)
        result = await db.execute(stmt)
        auth_record = result.scalar_one_or_none()

        encrypted_access = encrypt_token(access_token)
        encrypted_refresh = encrypt_token(refresh_token)

        if auth_record:
            auth_record.encrypted_access_token = encrypted_access
            if refresh_token:
                auth_record.encrypted_refresh_token = encrypted_refresh
            auth_record.token_expires_at = expires_at
            if spotify_user_id:
                auth_record.spotify_user_id = spotify_user_id
            auth_record.updated_at = datetime.now(timezone.utc)
        else:
            new_auth = StationAuth(
                station_id=station_id,
                encrypted_access_token=encrypted_access,
                encrypted_refresh_token=encrypted_refresh,
                token_expires_at=expires_at,
                spotify_user_id=spotify_user_id,
                updated_at=datetime.now(timezone.utc)
            )
            db.add(new_auth)

        await db.commit()

    @staticmethod
    async def delete_station_tokens(db: AsyncSession, station_id: int) -> None:
        stmt = select(StationAuth).where(StationAuth.station_id == station_id)
        result = await db.execute(stmt)
        auth_record = result.scalar_one_or_none()
        if auth_record:
            await db.delete(auth_record)
            await db.commit()
