"""Database setup and session management."""

import os
from pathlib import Path
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, declarative_base

# Database file location
# Use /data on Render (persistent disk), local data/ for development
if os.path.exists("/data") and os.path.isdir("/data"):
    DB_PATH = Path("/data/rentals.db")
else:
    DB_PATH = Path(__file__).parent.parent.parent / "data" / "rentals.db"

DATABASE_URL = f"sqlite:///{DB_PATH}"

# Create engine with better concurrency settings
engine = create_engine(
    DATABASE_URL,
    echo=False,
    connect_args={
        "check_same_thread": False,  # Allow multi-threaded access
        "timeout": 30,  # Wait up to 30 seconds for locks
    }
)


# Enable WAL mode for better concurrent read/write performance
@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.execute("PRAGMA busy_timeout=30000")  # 30 second timeout
    cursor.close()


# Session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base class for models
Base = declarative_base()


def get_session():
    """Get a database session."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def init_db():
    """Initialize the database (create all tables)."""
    # Ensure data directory exists
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    # Import models to register them
    from . import listing  # noqa

    # Create all tables
    Base.metadata.create_all(bind=engine)
