from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, scoped_session
import os
import contextlib

from .models import Base

class SQLiteManager:
    """SQLAlchemy Manager"""
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._engine = None
        self._session_factory = None

    def init_db(self):
        """Initialize database tables"""
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._engine = create_engine(f"sqlite:///{self.db_path}", connect_args={"check_same_thread": False})
        Base.metadata.create_all(self._engine)
        self._session_factory = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=self._engine))

    @contextlib.contextmanager
    def session_scope(self):
        """Provide a transactional scope around a series of operations."""
        if not self._session_factory:
            raise RuntimeError("Database not initialized")
            
        session = self._session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

# Global singleton or context managed later?
# For now, expose class.
