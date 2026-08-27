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
    UNIQUE (supplier_code, file_checksum)
);
