"""FastAPI dependencies: database session, auth, rate limits."""

from . import database as db


def get_db():
    """Dependency that provides the DuckDB connection."""
    return db.get_connection()
