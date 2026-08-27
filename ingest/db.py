from __future__ import annotations

import uuid
from datetime import datetime

import psycopg2
import psycopg2.extras

from .config import PostgresConfig
from parsers.base import NormalizedRow


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


def fetch_unparsed_staging_rows(conn) -> list[dict]:
    """Return staging_supplier_feed rows not yet processed by ingest/parse.py."""
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
            SELECT id, run_id, supplier_code, source_filename, raw_content
            FROM staging_supplier_feed
            WHERE parsed_at IS NULL
            ORDER BY id
            """
        )
        return cur.fetchall()


def load_normalized_rows(
    conn,
    *,
    staging_id: int,
    run_id: uuid.UUID,
    supplier_code: str,
    rows: list[NormalizedRow],
) -> int:
    """Insert normalized rows into stg_feed_rows and mark the staging row parsed.

    Runs as a single transaction -- callers should roll back on failure
    rather than leave a staging row half-loaded and marked parsed.
    """
    with conn.cursor() as cur:
        for row in rows:
            cur.execute(
                """
                INSERT INTO stg_feed_rows (
                    staging_id, run_id, supplier_code, sku, ean, description, price, stock
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    staging_id,
                    str(run_id),
                    supplier_code,
                    row.sku,
                    row.ean,
                    row.description,
                    row.price,
                    row.stock,
                ),
            )
        cur.execute(
            "UPDATE staging_supplier_feed SET parsed_at = now() WHERE id = %s",
            (staging_id,),
        )
    conn.commit()
    return len(rows)
