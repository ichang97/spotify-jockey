from functools import lru_cache
from typing import Optional
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    APP_DOMAIN: Optional[str] = None
    SECRET_KEY: str = "default_secret_key_change_in_production"
    FERNET_KEY: str = "D7fR1B7T1X7gX0v_B5c3E7H8K9M0P1Q2R3S4T5U6V7W="
    SPOTIFY_CLIENT_ID: str = ""
    SPOTIFY_CLIENT_SECRET: str = ""
    SPOTIFY_REDIRECT_URI: str = "http://localhost:3000/auth/spotify/callback"
    DATABASE_URL: str = "sqlite+aiosqlite:///./data/spotify_jockey.db"
    BACKEND_HOST: str = "0.0.0.0"
    BACKEND_PORT: int = 8000
    FRONTEND_PORT: int = 3000
    BACKEND_INTERNAL_URL: str = "http://backend:8000"
    FRONTEND_PUBLIC_URL: str = "http://localhost:3000"
    BACKEND_PUBLIC_URL: str = "http://localhost:8000"

    @model_validator(mode="after")
    def resolve_redirect_uri(self) -> "Settings":
        base_url = None
        if self.APP_DOMAIN:
            base_url = self.APP_DOMAIN if self.APP_DOMAIN.startswith(("http://", "https://")) else f"https://{self.APP_DOMAIN}"
        elif self.FRONTEND_PUBLIC_URL:
            base_url = self.FRONTEND_PUBLIC_URL if self.FRONTEND_PUBLIC_URL.startswith(("http://", "https://")) else f"https://{self.FRONTEND_PUBLIC_URL}"

        if base_url:
            base_clean = base_url.rstrip("/")
            if not self.SPOTIFY_REDIRECT_URI or self.SPOTIFY_REDIRECT_URI == "http://localhost:3000/auth/spotify/callback" or "spotify-jockey.test" in self.SPOTIFY_REDIRECT_URI:
                if "localhost" not in base_clean and "spotify-jockey.test" not in base_clean:
                    self.SPOTIFY_REDIRECT_URI = f"{base_clean}/auth/spotify/callback"
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
