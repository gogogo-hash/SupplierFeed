from __future__ import annotations

import argparse
import logging
import sys
import uuid

from .config import load_postgres_config
from .db import fetch_unparsed_staging_rows, get_connection, load_normalized_rows
from parsers.registry import UnknownSupplierError, get_parser


def _configure_logging(run_id: uuid.UUID) -> logging.LoggerAdapter:
    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter("%(asctime)s run_id=%(run_id)s level=%(levelname)s %(message)s")
    )

    logger = logging.getLogger("parse")
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    logger.propagate = False

    return logging.LoggerAdapter(logger, {"run_id": run_id})


def main() -> int:
    argparse.ArgumentParser(
        description="Parse unparsed staging_supplier_feed rows into stg_feed_rows."
    ).parse_args()

    run_id = uuid.uuid4()
    log = _configure_logging(run_id)

    conn = get_connection(load_postgres_config())
    try:
        staging_rows = fetch_unparsed_staging_rows(conn)
        log.info("found %s unparsed staging row(s)", len(staging_rows))

        for staging_row in staging_rows:
            staging_id = staging_row["id"]
            supplier_code = staging_row["supplier_code"]

            try:
                parse_fn = get_parser(supplier_code)
            except UnknownSupplierError:
                log.error(
                    "no parser registered for supplier=%s (staging_id=%s), skipping",
                    supplier_code,
                    staging_id,
                )
                continue

            try:
                normalized_rows = parse_fn(staging_row["raw_content"])
                row_count = load_normalized_rows(
                    conn,
                    staging_id=staging_id,
                    run_id=staging_row["run_id"],
                    supplier_code=supplier_code,
                    rows=normalized_rows,
                )
            except Exception:
                conn.rollback()
                log.exception(
                    "failed to parse/load staging_id=%s for supplier=%s, skipping",
                    staging_id,
                    supplier_code,
                )
                continue

            log.info(
                "parsed %s row(s) from staging_id=%s (supplier=%s)",
                row_count,
                staging_id,
                supplier_code,
            )
    finally:
        conn.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
