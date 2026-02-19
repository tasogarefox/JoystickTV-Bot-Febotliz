import sqlite3
from contextlib import asynccontextmanager

from sqlalchemy import event
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.orm import declarative_base
from sqlalchemy.pool import NullPool

from app import settings


# ==============================================================================
# Config

Base = declarative_base()

engine = create_async_engine(
    settings.DATABASE_URL,
    future=True,
    poolclass=NullPool,  # Fix process not exiting when using AsyncEngine.begin() with SQLAlchemy>=2.0.38
)
AsyncSessionMaker = async_sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)

@event.listens_for(engine.sync_engine, "connect")
def enable_foreign_keys(dbapi_connection, connection_record):
    if isinstance(dbapi_connection, sqlite3.Connection):  # only for SQLite
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON;")
        cursor.close()


# ==============================================================================
# Functions

async def async_setup_database():
    # Import models to have them registered
    from . import models

    # Create database directory
    if not settings.DATABASE_DIR.exists():
        settings.DATABASE_DIR.mkdir(parents=True)

    # Create database tables if they don't exist yet
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

async def depend_async_db():
    """
    FastAPI dependency to get a database session.
    Transactions have to be started manually.
    """
    async with AsyncSessionMaker() as db:
        yield db

async def depend_async_db_transaction():
    """
    FastAPI dependency to get a database session.
    Transactions are started and committed automatically.
    """
    async with AsyncSessionMaker.begin() as db:
        yield db
