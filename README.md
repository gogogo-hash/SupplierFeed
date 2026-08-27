# Supplier Feed Middleware — Ingestion POC

Proof of concept for the ingestion half of the pipeline: connect to a
supplier's SFTP server, confirm the file is stable and not stale, then land
it in a Postgres staging table. This is the "shadow stack" testing setup
described in `docs/supplier-feed-proposal.md` — a mock SFTP server
(`atmoz/sftp`) and Postgres, both run locally via Docker, standing in for a
real supplier server so the ingestion mechanics can be exercised without
live credentials.

Parsing, plausibility checks, matching, and promotion to `current_state`
are out of scope for this POC — it only proves the fetch → stability/age
checks → checksum → staging load path.

## Setup

```bash
cp .env.example .env
docker compose up -d
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
```

## Run

```bash
python -m ingest.run --supplier supplier_a --remote-path /upload/supplier_a_sample.csv
```

Re-running the same command is a no-op — the file's checksum is already
staged, so the row is skipped rather than duplicated.

Verify the result:

```bash
docker compose exec postgres psql -U supplierfeed -c \
  "select id, supplier_code, source_filename, file_size_bytes, fetched_at from staging_supplier_feed;"
```

## Tests

The stability/staleness checks are pure logic and covered without needing
Docker or a live SFTP connection:

```bash
pytest tests/
```

## Layout

- `ingest/sftp_client.py` — connects over SFTP, confirms the file isn't
  still mid-upload (two `stat()` calls compared) and isn't older than a
  configurable threshold, then downloads it and computes a checksum.
- `ingest/db.py` — inserts the fetched file into `staging_supplier_feed`,
  idempotent on `(supplier_code, file_checksum)`.
- `ingest/run.py` — CLI entry point tying fetch + stage together under a
  single run ID for traceable logging.
- `db/schema.sql` — applied automatically on first `docker compose up` via
  Postgres's init-scripts mechanism.
- `fixtures/supplier_a_sample.csv` — sample feed (includes one row with no
  EAN, matching the EAN-less supplier case in the proposal) served by the
  mock SFTP container.
