"""Database setup and session management."""

from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

# Database file location
DB_PATH = Path(__file__).parent.parent.parent / "data" / "rentals.db"
DATABASE_URL = f"sqlite:///{DB_PATH}"

# Create engine
engine = create_engine(DATABASE_URL, echo=False)

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
