"""
Database connection and session management

Supports both SQLite (local dev) and Azure SQL Server (production).
The driver is auto-detected from DATABASE_URL:
  - sqlite:///./data/autoapply.db          → SQLite
  - mssql+pyodbc://user:pass@server/db?... → Azure SQL Server
"""
from sqlmodel import SQLModel, create_engine, Session
from typing import Generator
from .config import get_settings

settings = get_settings()


def _is_sqlite(url: str) -> bool:
    """Check if the database URL points to SQLite"""
    return url.startswith("sqlite")


def _build_engine():
    """
    Build the SQLAlchemy engine based on DATABASE_URL.

    - SQLite: uses check_same_thread=False (required for FastAPI)
    - MSSQL: uses pool_pre_ping to handle Azure connection drops
    """
    url = settings.database_url

    if _is_sqlite(url):
        return create_engine(
            url,
            echo=False,
            connect_args={"check_same_thread": False},
        )
    else:
        # Azure SQL Server / MSSQL
        return create_engine(
            url,
            echo=False,
            pool_pre_ping=True,          # reconnect on stale connections
            pool_size=5,                  # connection pool size
            max_overflow=10,              # extra connections under load
            pool_recycle=300,             # recycle connections every 5 min (Azure drops idle)
        )


engine = _build_engine()


def create_db_and_tables():
    """Create all database tables"""
    SQLModel.metadata.create_all(engine)


def get_session() -> Generator[Session, None, None]:
    """Dependency for getting database session"""
    with Session(engine) as session:
        yield session
