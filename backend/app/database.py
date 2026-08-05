import os
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from app.config import get_settings

settings = get_settings()

# Fallback to local SQLite file for development if Postgres is not accessible
db_url = os.environ.get("DATABASE_URL", settings.DATABASE_URL)
if "sqlite" in db_url or not db_url:
    db_url = "sqlite+aiosqlite:///./propel.db"

is_sqlite = "sqlite" in db_url

connect_args = {"check_same_thread": False, "timeout": 30.0} if is_sqlite else {}

engine = create_async_engine(
    db_url,
    echo=False,
    connect_args=connect_args,
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncSession:
    """FastAPI dependency — yields a database session."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
