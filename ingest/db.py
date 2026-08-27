from __future__ import annotations

import uuid
from datetime import datetime

import psycopg2

from .config import PostgresConfig


def get_connection(config: PostgresConfig):
    return psycopg2.connect(
        host=config.host,
        port=config.port,
        dbname=config.database,
        user=config.user,
        password=config.password,
    )


def insert_staging_row(
    conn,
    *,
    run_id: uuid.UUID,
    supplier_code: str,
    source_filename: str,
    file_checksum: str,
    file_size_bytes: int,
    remote_modified_at: datetime,
    raw_content: str,
) -> bool:
    """Insert a fetched file into staging_supplier_feed.

    Returns False without inserting if this exact file (by checksum) is
    already staged for this supplier -- makes re-running ingestion a no-op
    instead of creating duplicate rows.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO staging_supplier_feed (
                run_id, supplier_code, source_filename, file_checksum,
                file_size_bytes, remote_modified_at, raw_content
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (supplier_code, file_checksum) DO NOTHING
            RETURNING id
            """,
            (
                str(run_id),
                supplier_code,
                source_filename,
                file_checksum,
                file_size_bytes,
                remote_modified_at,
                raw_content,
            ),
        )
        inserted = cur.fetchone() is not None
    conn.commit()
    return inserted
