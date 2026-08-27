-- Landing zone for raw ingestion runs, before parsing/validation/matching.
-- One row per successfully fetched file. Idempotent per (supplier_code,
-- file_checksum) so re-running ingestion against an unchanged file is a
-- no-op rather than a duplicate row.
--
-- TODO: checksum is over file content only, so a supplier re-sending
-- byte-identical data (e.g. "nothing changed today") is silently treated
-- as a no-op with no persisted record that the check happened. Confirm
-- with the client whether that's acceptable or whether a separate
-- run-log table is needed to record every check, not just new data.
CREATE TABLE IF NOT EXISTS staging_supplier_feed (
    id BIGSERIAL PRIMARY KEY,
    run_id UUID NOT NULL,
    supplier_code TEXT NOT NULL,
    source_filename TEXT NOT NULL,
    file_checksum TEXT NOT NULL,
    file_size_bytes BIGINT NOT NULL,
    remote_modified_at TIMESTAMPTZ,
    raw_content TEXT NOT NULL,
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- NULL until ingest/parse.py has processed this row. Lets the parse
    -- step (its own, tighter schedule) query "not yet parsed" directly
    -- instead of inferring it.
    parsed_at TIMESTAMPTZ,
    UNIQUE (supplier_code, file_checksum)
);

-- Warehouse-style staging layer (the "L" in ELT): one row per normalized
-- line item, typed but not yet validated, matched, or promoted. Populated
-- by ingest/parse.py from staging_supplier_feed rows where parsed_at IS
-- NULL, via the shared per-supplier parser interface in parsers/.
CREATE TABLE IF NOT EXISTS stg_feed_rows (
    id BIGSERIAL PRIMARY KEY,
    staging_id BIGINT NOT NULL REFERENCES staging_supplier_feed (id),
    -- Denormalized from staging_supplier_feed.run_id (the original fetch
    -- run), not the parse invocation's own run -- fetch and parse run on
    -- independent schedules, so there's no single run_id spanning both.
    run_id UUID NOT NULL,
    supplier_code TEXT NOT NULL,
    sku TEXT NOT NULL,
    ean TEXT,
    description TEXT,
    price NUMERIC(12, 2) NOT NULL,
    stock INTEGER NOT NULL,
    parsed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
