"""Database configuration from environment variables."""

import os
from dataclasses import dataclass


@dataclass
class DatabaseConfig:
    """Database configuration."""

    db_type: str  # "sqlite" or "postgresql"

    # SQLite
    sqlite_path: str = "./data/knowledge.db"

    # PostgreSQL
    postgresql_host: str = "localhost"
    postgresql_port: int = 5432
    postgresql_user: str = "pa_user"
    postgresql_password: str = ""
    postgresql_database: str = "personal_assistant"
    postgresql_ssl: str = "prefer"
    postgresql_pool_size: int = 10
    postgresql_max_overflow: int = 20

    # Dual-write mode (temporary)
    dual_write: bool = False

    @classmethod
    def from_env(cls) -> "DatabaseConfig":
        """Load configuration from environment variables."""
        db_type = os.getenv("DB_TYPE", "sqlite").lower()

        if db_type == "postgresql":
            return cls(
                db_type="postgresql",
                sqlite_path=os.getenv("DB_SQLITE_PATH", "./data/knowledge.db"),
                postgresql_host=os.getenv("DB_POSTGRESQL_HOST", "localhost"),
                postgresql_port=int(os.getenv("DB_POSTGRESQL_PORT", "5432")),
                postgresql_user=os.getenv("DB_POSTGRESQL_USER", "pa_user"),
                postgresql_password=os.getenv("DB_POSTGRESQL_PASSWORD", ""),
                postgresql_database=os.getenv("DB_POSTGRESQL_DATABASE", "personal_assistant"),
                postgresql_ssl=os.getenv("DB_POSTGRESQL_SSL", "prefer"),
                postgresql_pool_size=int(os.getenv("DB_POSTGRESQL_POOL_SIZE", "10")),
                postgresql_max_overflow=int(os.getenv("DB_POSTGRESQL_MAX_OVERFLOW", "20")),
                dual_write=os.getenv("DB_DUAL_WRITE", "false").lower() == "true",
            )
        else:
            return cls(
                db_type="sqlite",
                sqlite_path=os.getenv("DB_SQLITE_PATH", "./data/knowledge.db"),
                dual_write=os.getenv("DB_DUAL_WRITE", "false").lower() == "true",
            )

    def to_connection_kwargs(self) -> dict:
        """Convert config to database connection kwargs."""
        if self.db_type == "postgresql":
            return {
                "host": self.postgresql_host,
                "port": self.postgresql_port,
                "user": self.postgresql_user,
                "password": self.postgresql_password,
                "database": self.postgresql_database,
                "ssl": self.postgresql_ssl,
                "pool_size": self.postgresql_pool_size,
                "max_overflow": self.postgresql_max_overflow,
            }
        else:
            return {"db_path": self.sqlite_path}
