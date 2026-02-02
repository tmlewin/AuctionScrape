"""
Database connection and session management.

Provides async and sync database access with proper connection pooling
and session lifecycle management.
"""

from __future__ import annotations

from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, AsyncGenerator, Generator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session, sessionmaker

from .models import Base

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine


# =============================================================================
# Global Engine References
# =============================================================================

_sync_engine: Engine | None = None
_async_engine: "AsyncEngine | None" = None
_sync_session_factory: sessionmaker[Session] | None = None
_async_session_factory: async_sessionmaker[AsyncSession] | None = None


# =============================================================================
# SQLite Configuration
# =============================================================================


def _configure_sqlite(engine: Engine) -> None:
    """Configure SQLite for better performance and reliability.
    
    Enables:
    - Foreign key enforcement
    - WAL mode for better concurrency
    - Synchronous mode for durability
    """
    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA cache_size=-64000")  # 64MB cache
        cursor.close()


def _get_async_url(url: str) -> str:
    """Convert sync database URL to async variant.
    
    SQLite: sqlite:/// -> sqlite+aiosqlite:///
    PostgreSQL: postgresql:// -> postgresql+asyncpg://
    """
    if url.startswith("sqlite:///"):
        return url.replace("sqlite:///", "sqlite+aiosqlite:///")
    elif url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://")
    elif url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+asyncpg://")
    return url


# =============================================================================
# Engine Creation
# =============================================================================


def get_engine(
    url: str = "sqlite:///data/procurewatch.db",
    echo: bool = False,
    pool_size: int = 5,
) -> Engine:
    """Get or create the synchronous database engine.
    
    Args:
        url: SQLAlchemy database URL
        echo: Whether to log SQL statements
        pool_size: Connection pool size (ignored for SQLite)
        
    Returns:
        SQLAlchemy Engine instance
    """
    global _sync_engine, _sync_session_factory
    
    if _sync_engine is not None:
        return _sync_engine
    
    # Ensure data directory exists for SQLite
    if url.startswith("sqlite:///"):
        db_path = url.replace("sqlite:///", "")
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    
    # Create engine with appropriate settings
    if url.startswith("sqlite"):
        _sync_engine = create_engine(
            url,
            echo=echo,
            connect_args={"check_same_thread": False},
        )
        _configure_sqlite(_sync_engine)
    else:
        _sync_engine = create_engine(
            url,
            echo=echo,
            pool_size=pool_size,
            max_overflow=10,
            pool_pre_ping=True,
        )
    
    _sync_session_factory = sessionmaker(
        bind=_sync_engine,
        autocommit=False,
        autoflush=False,
        expire_on_commit=False,
    )
    
    return _sync_engine


async def get_async_engine(
    url: str = "sqlite:///data/procurewatch.db",
    echo: bool = False,
    pool_size: int = 5,
) -> "AsyncEngine":
    """Get or create the asynchronous database engine.
    
    Args:
        url: SQLAlchemy database URL (will be converted to async variant)
        echo: Whether to log SQL statements
        pool_size: Connection pool size
        
    Returns:
        SQLAlchemy AsyncEngine instance
    """
    global _async_engine, _async_session_factory
    
    if _async_engine is not None:
        return _async_engine
    
    async_url = _get_async_url(url)
    
    # Ensure data directory exists for SQLite
    if url.startswith("sqlite:///"):
        db_path = url.replace("sqlite:///", "")
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    
    if async_url.startswith("sqlite"):
        _async_engine = create_async_engine(
            async_url,
            echo=echo,
        )
    else:
        _async_engine = create_async_engine(
            async_url,
            echo=echo,
            pool_size=pool_size,
            max_overflow=10,
            pool_pre_ping=True,
        )
    
    _async_session_factory = async_sessionmaker(
        bind=_async_engine,
        class_=AsyncSession,
        autocommit=False,
        autoflush=False,
        expire_on_commit=False,
    )
    
    return _async_engine


# =============================================================================
# Session Management
# =============================================================================


@contextmanager
def get_session() -> Generator[Session, None, None]:
    """Get a synchronous database session.
    
    Usage:
        with get_session() as session:
            session.query(...)
            
    Yields:
        SQLAlchemy Session instance
    """
    if _sync_session_factory is None:
        get_engine()  # Initialize with defaults
    
    assert _sync_session_factory is not None
    session = _sync_session_factory()
    
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_sync_session() -> Session:
    """Get a raw synchronous database session (caller manages lifecycle).
    
    The caller is responsible for committing/rolling back and closing.
    
    Returns:
        SQLAlchemy Session instance
    """
    if _sync_session_factory is None:
        get_engine()  # Initialize with defaults
    
    assert _sync_session_factory is not None
    return _sync_session_factory()


@asynccontextmanager
async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    """Get an asynchronous database session.
    
    Usage:
        async with get_async_session() as session:
            await session.execute(...)
            
    Yields:
        SQLAlchemy AsyncSession instance
    """
    if _async_session_factory is None:
        await get_async_engine()  # Initialize with defaults
    
    assert _async_session_factory is not None
    session = _async_session_factory()
    
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


# =============================================================================
# Database Initialization
# =============================================================================


def init_db(url: str = "sqlite:///data/procurewatch.db", echo: bool = False) -> None:
    """Initialize the database schema.
    
    Creates all tables if they don't exist. For production use,
    prefer Alembic migrations.
    
    Args:
        url: Database URL
        echo: Whether to log SQL
    """
    engine = get_engine(url, echo=echo)
    Base.metadata.create_all(bind=engine)


async def init_db_async(url: str = "sqlite:///data/procurewatch.db", echo: bool = False) -> None:
    """Initialize the database schema asynchronously.
    
    Args:
        url: Database URL
        echo: Whether to log SQL
    """
    engine = await get_async_engine(url, echo=echo)
    
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def drop_db(url: str = "sqlite:///data/procurewatch.db") -> None:
    """Drop all database tables.
    
    WARNING: This will delete all data!
    
    Args:
        url: Database URL
    """
    engine = get_engine(url)
    Base.metadata.drop_all(bind=engine)


# =============================================================================
# Cleanup
# =============================================================================


def dispose_engines() -> None:
    """Dispose of all database engines.
    
    Should be called on application shutdown.
    """
    global _sync_engine, _async_engine, _sync_session_factory, _async_session_factory
    
    if _sync_engine is not None:
        _sync_engine.dispose()
        _sync_engine = None
        _sync_session_factory = None
    
    if _async_engine is not None:
        # Note: For async, you should await this in an async context
        # This is a sync fallback
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(_async_engine.dispose())
            else:
                loop.run_until_complete(_async_engine.dispose())
        except RuntimeError:
            pass
        _async_engine = None
        _async_session_factory = None


async def dispose_engines_async() -> None:
    """Dispose of all database engines asynchronously."""
    global _sync_engine, _async_engine, _sync_session_factory, _async_session_factory
    
    if _sync_engine is not None:
        _sync_engine.dispose()
        _sync_engine = None
        _sync_session_factory = None
    
    if _async_engine is not None:
        await _async_engine.dispose()
        _async_engine = None
        _async_session_factory = None
