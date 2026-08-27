from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class PostgresConfig:
    host: str
    port: int
    database: str
    user: str
    password: str


@dataclass(frozen=True)
class SftpConfig:
    host: str
    port: int
    username: str
    password: str
    stability_check_interval_seconds: float
    max_file_age_hours: float | None


def load_postgres_config() -> PostgresConfig:
    return PostgresConfig(
        host=os.environ.get("PGHOST", "localhost"),
        port=int(os.environ.get("PGPORT", "5432")),
        database=os.environ.get("PGDATABASE", "supplierfeed"),
        user=os.environ.get("PGUSER", "supplierfeed"),
        password=os.environ.get("PGPASSWORD", "supplierfeed"),
    )


def load_sftp_config() -> SftpConfig:
    max_age = os.environ.get("SFTP_MAX_FILE_AGE_HOURS", "").strip()
    return SftpConfig(
        host=os.environ.get("SFTP_HOST", "localhost"),
        port=int(os.environ.get("SFTP_PORT", "2222")),
        username=os.environ.get("SFTP_USERNAME", "feeduser"),
        password=os.environ.get("SFTP_PASSWORD", "feedpass"),
        stability_check_interval_seconds=float(
            os.environ.get("SFTP_STABILITY_CHECK_INTERVAL_SECONDS", "2")
        ),
        max_file_age_hours=float(max_age) if max_age else None,
    )
