from __future__ import annotations

import argparse
import logging
import sys
import uuid

from .config import load_postgres_config, load_sftp_config
from .db import get_connection, insert_staging_row
from .sftp_client import StaleFileError, UnstableFileError, fetch_file

def _configure_logging(run_id: uuid.UUID) -> logging.LoggerAdapter:
    # A dedicated, non-propagating logger/handler -- rather than
    # logging.basicConfig() on the root logger -- so this run_id-tagged
    # format only applies to our own log records. paramiko logs its own
    # SSH/SFTP handshake messages to the root logger, and those records
    # have no run_id field, so attaching this format to root crashes with
    # a KeyError the first time paramiko logs anything.
    logging.getLogger("paramiko").setLevel(logging.WARNING)

    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter("%(asctime)s run_id=%(run_id)s level=%(levelname)s %(message)s")
    )

    logger = logging.getLogger("ingest")
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    logger.propagate = False

    return logging.LoggerAdapter(logger, {"run_id": run_id})


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fetch a supplier feed file over SFTP and land it in Postgres staging."
    )
    parser.add_argument("--supplier", required=True, help="Supplier code, e.g. supplier_a")
    parser.add_argument("--remote-path", required=True, help="Path to the file on the SFTP server")
    args = parser.parse_args()

    run_id = uuid.uuid4()
    log = _configure_logging(run_id)

    sftp_config = load_sftp_config()
    pg_config = load_postgres_config()

    log.info("fetching %s from %s:%s", args.remote_path, sftp_config.host, sftp_config.port)
    try:
        fetched = fetch_file(sftp_config, args.remote_path)
    except (UnstableFileError, StaleFileError) as exc:
        log.error("aborting run: %s", exc)
        return 1

    log.info(
        "fetched %s bytes, checksum=%s, remote_modified_at=%s",
        fetched.size_bytes,
        fetched.checksum,
        fetched.remote_modified_at,
    )

    conn = get_connection(pg_config)
    try:
        inserted = insert_staging_row(
            conn,
            run_id=run_id,
            supplier_code=args.supplier,
            source_filename=args.remote_path.rsplit("/", 1)[-1],
            file_checksum=fetched.checksum,
            file_size_bytes=fetched.size_bytes,
            remote_modified_at=fetched.remote_modified_at,
            raw_content=fetched.content.decode("utf-8"),
        )
    finally:
        conn.close()

    if inserted:
        log.info("staged file for supplier=%s", args.supplier)
    else:
        log.info("skipped: identical file already staged for supplier=%s", args.supplier)

    return 0


if __name__ == "__main__":
    sys.exit(main())
