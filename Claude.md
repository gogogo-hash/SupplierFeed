# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Current state

This repository is pre-implementation. It contains only planning documents in `docs/`:

- `docs/supplier-feed-proposal.md` — the client proposal and development roadmap for this project (architecture decisions, phased plan, pricing, testing strategy).
- `docs/contract.md` — currently empty.

No source code, build tooling, package manifests, or tests exist yet. There are no build/lint/test commands to run. When implementation begins, this file should be updated with real commands (Docker Compose invocation, Python test runner, n8n workflow locations, etc.) and this section should be replaced.

## Project intent

This is a supplier-feed middleware system that pulls inventory/price feeds from multiple suppliers' SFTP servers and syncs read-only data into Shopify analytics — without ever writing supplier data into Shopify inventory. The client's own warehouse stock is the sole source of truth for sellable inventory; supplier feeds are treated as procurement signals only.

### Planned architecture (from `docs/supplier-feed-proposal.md`)

- **Ingestion**: one thin n8n workflow per supplier, handling SFTP schedule/connection/pre-checks (file existence, size, modification-time, stability/checksum). Supplier credentials and thresholds live in n8n's credential store.
- **Parsing**: shared Python package with one parser module per supplier (`parsers/supplier_a.py`, etc.) behind a common interface — `parse(file) -> list[NormalizedRow]` — registered by `file_code`. New suppliers only need a new parser module, not a new pipeline.
- **Two independent schedules**: the supplier-facing poll (4x/day per contract scope) is separate from an internal, tight-loop (minutes) self-healing check for files fetched-but-not-yet-parsed. The internal loop never touches supplier servers.
- **Data model (Postgres)**:
  - `staging_supplier_feed` — landing zone for each ingestion run.
  - `current_state` — promoted, currently-active rows only (temporal table pattern: old rows marked inactive with a timestamp rather than updated in place).
  - `price_stock_history` — full audit trail, derived for free from the temporal pattern.
  - `sku_mapping` — supplier SKU/EAN → internal article mapping, with `match_method` (`ean`, `manual`, fuzzy, etc.).
  - `needs_review` — unmatched or low-confidence rows, holding the raw source row; resolved independently without blocking the rest of a run.
  - Whole-file plausibility checks (e.g. row count down >20%, >30% of SKUs at zero stock) abort promotion of the *entire* run. Row-level match failures are independent and only quarantine the affected row(s) to `needs_review`.
- **Matching fallback chain for suppliers without EAN/GTIN**: supplier article number (if previously mapped) → deterministic fuzzy match on manufacturer + MPN/title (surfaced as suggestion only, never auto-committed) → manual review queue.
- **Shopify integration**: read-only GraphQL Admin API only — never writes to Shopify inventory. Bulk Operations (sales history, product catalog) are asynchronous; use poll-with-backoff, not fixed-interval polling.
- **Analytics**: SQL views/materialized views over the ingestion data — supplier comparison, reorder suggestions (velocity × own Shopify stock × supplier price/availability), purchase price increase alerts, delisting detection. No separate tooling needed beyond what the pipeline already lands in Postgres.
- **Cross-cutting**: structured logging with a run ID spanning n8n → Python → Postgres, so a single feed run is traceable end-to-end.
- **Ops**: Docker Compose deployment, n8n's error-workflow feature wired to email/messenger for feed-failure alerts.
- **Testing strategy**: pure-function unit tests for parsers/plausibility/matching logic (no infra); a disposable local "shadow" stack (Docker Compose + a mock SFTP container seeded with edge-case fixture files); real anonymized sample files from each supplier requested before writing a pilot parser; read-only Shopify testing (no mutation risk); a dry-run pipeline mode that runs ingest → parse → validate → match but stops short of promoting; basic CI running Python unit tests on push.

### Build order (roadmap phases)

Phase 0 (setup) → Phase 1 (pilot: Supplier 1, full pipeline end-to-end) → Phase 2 (rollout: Suppliers 2–5, reusing the pipeline, adding only parser modules) → Phase 3 (analytics layer) → Phase 4 (hardening/handoff). Supplier 1 is meant to prove out the entire pipeline; later suppliers should only require a new parser + config entry.
