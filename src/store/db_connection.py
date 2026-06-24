"""Database connection abstraction for SQLite and PostgreSQL."""

import asyncio
import json
import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


class DBConnection(ABC):
    """Abstract database connection interface."""

    @abstractmethod
    async def initialize(self) -> None:
        """Initialize database connection and create tables if needed."""
        pass

    @abstractmethod
    async def execute(self, query: str, params: tuple = ()) -> None:
        """Execute a query without returning results."""
        pass

    @abstractmethod
    async def fetchone(self, query: str, params: tuple = ()) -> Optional[dict]:
        """Fetch a single row as a dictionary."""
        pass

    @abstractmethod
    async def fetchall(self, query: str, params: tuple = ()) -> list[dict]:
        """Fetch all rows as list of dictionaries."""
        pass

    @abstractmethod
    async def commit(self) -> None:
        """Commit transaction."""
        pass

    @abstractmethod
    async def close(self) -> None:
        """Close database connection."""
        pass

    @abstractmethod
    async def begin_transaction(self) -> None:
        """Begin transaction."""
        pass

    @abstractmethod
    async def rollback(self) -> None:
        """Rollback transaction."""
        pass


class SQLiteConnection(DBConnection):
    """SQLite connection wrapper."""

    def __init__(self, db_path: str = "./data/knowledge.db"):
        self.db_path = db_path
        self._db: Optional[Any] = None

    async def initialize(self) -> None:
        """Initialize SQLite connection."""
        import aiosqlite

        logger.info(f"Initializing SQLite: {self.db_path}")
        db_dir = Path(self.db_path).parent
        db_dir.mkdir(parents=True, exist_ok=True)

        self._db = await aiosqlite.connect(self.db_path)
        self._db.row_factory = aiosqlite.Row
        await self._db.execute("PRAGMA foreign_keys = ON")
        await self._db.commit()

    async def execute(self, query: str, params: tuple = ()) -> None:
        """Execute query without returning results."""
        await self._db.execute(query, params)

    async def fetchone(self, query: str, params: tuple = ()) -> Optional[dict]:
        """Fetch single row."""
        cursor = await self._db.execute(query, params)
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def fetchall(self, query: str, params: tuple = ()) -> list[dict]:
        """Fetch all rows."""
        cursor = await self._db.execute(query, params)
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def commit(self) -> None:
        """Commit transaction."""
        await self._db.commit()

    async def close(self) -> None:
        """Close connection."""
        await self._db.close()

    async def begin_transaction(self) -> None:
        """SQLite doesn't require explicit begin."""
        pass

    async def rollback(self) -> None:
        """Rollback transaction."""
        await self._db.rollback()


class PostgreSQLConnection(DBConnection):
    """PostgreSQL connection wrapper."""

    def __init__(
        self,
        host: str = "localhost",
        port: int = 5432,
        user: str = "pa_user",
        password: str = "",
        database: str = "personal_assistant",
        ssl: str = "prefer",
        pool_size: int = 10,
        max_overflow: int = 20,
    ):
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.database = database
        self.ssl = ssl
        self.pool_size = pool_size
        self.max_overflow = max_overflow
        self._pool: Optional[Any] = None
        self._connection: Optional[Any] = None

    async def initialize(self) -> None:
        """Initialize PostgreSQL connection pool."""
        import asyncpg

        logger.info(f"Initializing PostgreSQL: {self.user}@{self.host}:{self.port}/{self.database}")

        try:
            # Convert ssl string to asyncpg ssl mode
            # asyncpg accepts: False (no SSL), True (require SSL), or ssl.SSLContext
            if self.ssl == "require":
                ssl_mode = True
            elif self.ssl == "disable":
                ssl_mode = False
            elif self.ssl == "prefer":
                # Try SSL but fall back to no SSL - use False for local dev
                ssl_mode = False
            else:
                ssl_mode = False

            logger.info(f"PostgreSQL SSL mode: {self.ssl} → asyncpg ssl={ssl_mode}")

            self._pool = await asyncpg.create_pool(
                host=self.host,
                port=self.port,
                user=self.user,
                password=self.password,
                database=self.database,
                min_size=1,
                max_size=self.pool_size,
                ssl=ssl_mode,
            )
            logger.info("PostgreSQL connection pool created successfully")
        except Exception as e:
            logger.error(f"Failed to connect to PostgreSQL: {e}")
            raise

    async def _get_connection(self) -> Any:
        """Get connection from pool."""
        if self._pool is None:
            raise RuntimeError("Connection pool not initialized")
        return await self._pool.acquire()

    def _convert_sqlite_to_postgres(self, query: str) -> str:
        """Convert SQLite-style ? placeholders to PostgreSQL $1, $2, etc."""
        import re
        counter = 0
        def replace_placeholder(match):
            nonlocal counter
            counter += 1
            return f"${counter}"
        return re.sub(r"\?", replace_placeholder, query)

    async def execute(self, query: str, params: tuple = ()) -> None:
        """Execute query without returning results."""
        conn = await self._get_connection()
        try:
            query = self._convert_sqlite_to_postgres(query)
            await conn.execute(query, *params)
        finally:
            await self._pool.release(conn)

    async def fetchone(self, query: str, params: tuple = ()) -> Optional[dict]:
        """Fetch single row."""
        conn = await self._get_connection()
        try:
            query = self._convert_sqlite_to_postgres(query)
            row = await conn.fetchrow(query, *params)
            return dict(row) if row else None
        finally:
            await self._pool.release(conn)

    async def fetchall(self, query: str, params: tuple = ()) -> list[dict]:
        """Fetch all rows."""
        conn = await self._get_connection()
        try:
            query = self._convert_sqlite_to_postgres(query)
            rows = await conn.fetch(query, *params)
            return [dict(row) for row in rows]
        finally:
            await self._pool.release(conn)

    async def commit(self) -> None:
        """PostgreSQL auto-commits."""
        pass

    async def close(self) -> None:
        """Close connection pool."""
        if self._pool:
            await self._pool.close()
            logger.info("PostgreSQL connection pool closed")

    async def begin_transaction(self) -> None:
        """Begin transaction."""
        if self._connection is None:
            self._connection = await self._get_connection()
        await self._connection.execute("BEGIN")

    async def rollback(self) -> None:
        """Rollback transaction."""
        if self._connection:
            await self._connection.execute("ROLLBACK")
            await self._pool.release(self._connection)
            self._connection = None


def create_connection(db_type: str = "sqlite", **kwargs) -> DBConnection:
    """Factory function to create appropriate database connection.

    Args:
        db_type: "sqlite" or "postgresql"
        **kwargs: Connection-specific parameters

    Returns:
        DBConnection instance
    """
    if db_type == "postgresql":
        return PostgreSQLConnection(**kwargs)
    elif db_type == "sqlite":
        return SQLiteConnection(**kwargs)
    else:
        raise ValueError(f"Unknown database type: {db_type}")
