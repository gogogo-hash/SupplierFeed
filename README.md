# Supplier Feed Middleware — Ingestion & Parsing POC

Proof of concept for the Extract and Load halves of the pipeline:

1. **Extract** (`ingest/run.py`) — connect to a supplier's SFTP server,
   confirm the file is stable and not stale, then land the raw content in
   `staging_supplier_feed`.
2. **Load** (`ingest/parse.py`) — pick up staging rows not yet parsed, run
   them through the shared per-supplier parser interface (`parsers/`), and
   load normalized rows into the warehouse-style `stg_feed_rows` staging
   table.

This is the "shadow stack" testing setup described in
`docs/supplier-feed-proposal.md` — a mock SFTP server (`atmoz/sftp`) and
Postgres, both run locally via Docker, standing in for a real supplier
server so the pipeline can be exercised without live credentials.

Extract and Load run as **separate entry points on separate schedules**,
matching the proposal's design: the supplier-facing fetch is throttled by
contract (4x/day), while parsing runs on its own tight internal loop
against whatever's landed in staging. They only share the database and the
parser registry, not a process or a schedule.

Plausibility checks, matching/`sku_mapping`, and promotion to
`current_state` are still out of scope for this POC.

## Setup

```bash
cp .env.example .env
docker compose up -d
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
```

## Run

```bash
# Extract: fetch the file and land it in staging
python -m ingest.run --supplier supplier_a --remote-path /upload/supplier_a_sample.csv

# Load: parse whatever's landed in staging but not yet parsed
python -m ingest.parse
```

Both are idempotent no-ops on a second run: `ingest.run` skips a file
whose checksum is already staged; `ingest.parse` finds nothing left where
`parsed_at IS NULL`.

A staging row whose `supplier_code` has no registered parser is logged and
skipped (left unparsed for retry/inspection) rather than aborting the rest
of the batch.

Verify the result:

```bash
docker compose exec postgres psql -U supplierfeed -c \
  "select id, supplier_code, source_filename, parsed_at from staging_supplier_feed;"
docker compose exec postgres psql -U supplierfeed -c \
  "select staging_id, supplier_code, sku, ean, price, stock from stg_feed_rows order by id;"
```

## Tests

The stability/staleness checks and the parser/registry logic are pure
functions, covered without needing Docker or a live SFTP connection:

```bash
pytest tests/
```

## Layout

- `ingest/sftp_client.py` — connects over SFTP, confirms the file isn't
  still mid-upload (two `stat()` calls compared) and isn't older than a
  configurable threshold, then downloads it and computes a checksum.
- `ingest/db.py` — staging/parsing persistence: inserting fetched files
  (idempotent on `(supplier_code, file_checksum)`), fetching unparsed
  staging rows, and loading normalized rows into `stg_feed_rows`.
- `ingest/run.py` — Extract CLI entry point: fetch + stage under a single
  run ID for traceable logging.
- `ingest/parse.py` — Load CLI entry point: parse unparsed staging rows
  into `stg_feed_rows`, one independent transaction per staging row.
- `parsers/base.py` — the shared `NormalizedRow` shape and `Parser`
  interface (`parse(raw_content: str) -> list[NormalizedRow]`) every
  supplier parser implements.
- `parsers/registry.py` — maps `supplier_code -> parser`. Onboarding a new
  supplier means adding a module here, not touching the pipeline.
- `parsers/supplier_a.py` — first parser implementation (CSV).
- `db/schema.sql` — applied automatically on first `docker compose up` via
  Postgres's init-scripts mechanism. Since this only runs once against an
  empty data directory, a schema change during development means either
  `docker compose down -v && docker compose up -d` (wipes local POC data)
  or a real migration tool once there's data worth preserving.
- `fixtures/supplier_a_sample.csv` — sample feed (includes one row with no
  EAN, matching the EAN-less supplier case in the proposal) served by the
  mock SFTP container.
