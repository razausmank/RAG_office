"""
database.py
-----------
SQLAlchemy engine and session management.

Swap-out guide for production:
  PostgreSQL : DATABASE_URL = "postgresql+asyncpg://user:pass@host/dbname"
  SQL Server : DATABASE_URL = "mssql+pyodbc://user:pass@host/dbname?driver=ODBC+Driver+17+for+SQL+Server"

Just set the DATABASE_URL environment variable and install the matching async driver.
"""

import os
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

# Load variables from .env file
load_dotenv()

# ---------------------------------------------------------------------------
# Connection URL
# Read from environment so the value can be overridden in production without
# touching source code.  Falls back to a local SQLite file for development.
# ---------------------------------------------------------------------------
DATABASE_URL: str = os.getenv(
    "DATABASE_URL",
    "sqlite:///./orders.db",   # SQLite dev default
)

# ---------------------------------------------------------------------------
# Engine
# check_same_thread is SQLite-only; it is ignored by other drivers.
# ---------------------------------------------------------------------------
connect_args: dict = (
    {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
)

engine = create_engine(
    DATABASE_URL,
    connect_args=connect_args,
    echo=False,           # Set True to log all SQL statements during debugging
    pool_pre_ping=True,   # Detect stale connections automatically
)

# ---------------------------------------------------------------------------
# Session factory
# autocommit=False  → explicit commits required (safer default)
# autoflush=False   → prevents implicit flushes that can cause surprises
# ---------------------------------------------------------------------------
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)


# ---------------------------------------------------------------------------
# Declarative base  (shared by all ORM models)
# ---------------------------------------------------------------------------
class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# FastAPI dependency – yields a DB session and ensures it is closed afterward
# ---------------------------------------------------------------------------
def get_db():
    """
    Dependency that provides a SQLAlchemy session per request.
    Use with FastAPI's Depends() system.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
