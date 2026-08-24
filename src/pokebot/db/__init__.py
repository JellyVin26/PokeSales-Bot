"""Database session management for the pokebot application."""

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from .models import Base


# Create engine
engine = None
SessionLocal = None


def init_db(db_url: str) -> None:
    """Initialize the database engine and session factory."""
    global engine, SessionLocal

    engine = create_async_engine(
        db_url,
        echo=False,
        future=True,
    )

    SessionLocal = sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )


async def create_session(db_url: str) -> AsyncSession:
    """Create a new database session."""
    if engine is None or engine.url != db_url:
        init_db(db_url)

    async_session = SessionLocal()
    return async_session


async def get_session() -> AsyncSession:
    """Get the current session (for dependency injection)."""
    if SessionLocal is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")
    return SessionLocal()


async def close_session(session: AsyncSession) -> None:
    """Close a database session."""
    await session.close()


async def create_all_tables() -> None:
    """Create all database tables."""
    if engine is None:
        raise RuntimeError("Database not initialized.")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def drop_all_tables() -> None:
    """Drop all database tables (for testing)."""
    if engine is None:
        raise RuntimeError("Database not initialized.")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)