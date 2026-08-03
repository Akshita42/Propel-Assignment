from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # Database
    DATABASE_URL: str = "postgresql+asyncpg://propel:propel@db:5432/propeldb"
    DATABASE_URL_SYNC: str = "postgresql+psycopg2://propel:propel@db:5432/propeldb"

    # Gemini AI
    GEMINI_API_KEY: str = ""

    # App
    APP_ENV: str = "development"
    CORS_ORIGINS: str = "http://localhost:5173,http://localhost:3000"

    # Fault Detection Tuning
    HEARTBEAT_TIMEOUT_SECONDS: int = 1080       # 2 missed heartbeats (15min each) + 3min grace
    FAULT_GROUPING_WINDOW_SECONDS: int = 30     # Group signals within this window
    MIN_SPAN_CONFIDENCE: float = 0.50           # Below this → DT-level fallback in UI
    RESTORATION_THRESHOLD: float = 0.80         # % poles restored before auto-verify

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",")]

    class Config:
        env_file = ".env"
        extra = "ignore"


@lru_cache()
def get_settings() -> Settings:
    return Settings()
