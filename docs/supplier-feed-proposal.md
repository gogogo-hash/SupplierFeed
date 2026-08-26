# Supplier Feed Middleware — Proposal & Roadmap

---

# 1. Proposal

Hi [Client Name],

This proposal is based on the "Connect suppliers FTP Servers with our Shopify" contract posted on Upwork.

**Summary:** I've taken note that supplier feeds are procurement signals, not stock. Writing them into Shopify inventory conflates what a supplier claims to have with what you can actually ship, and a lagging or overstated feed becomes an oversell on your side. Keeping supplier data out of Shopify inventory and treating your own warehouse as the only source of truth for sellable stock is correct.

Please see the body of the proposal for the detailed adjustments and implementation plan for your proposed architecture, along with how I'd handle EAN-less suppliers, scope coverage, and pricing.

## Proposed Architecture Assessment and Adjustments

### Feed Ingestion, Plausibility Checks, Data Loading

- **Per-supplier n8n workflows for fetch, one shared Python registry for parsing.** Each supplier gets its own thin n8n workflow handling schedule, SFTP connection, and pre-checks — n8n's SFTP capabilities handle file existence, size, and modification-time checks natively, so the stability/age validation happens before anything is downloaded. This matches your scope's "one workflow per supplier" directly, keeps each supplier's credentials and thresholds (including which stability check method that supplier supports) in n8n's own credential store where they're easy to view and edit, and gives you a natural template to clone when connecting supplier six. What's shared instead is the parsing logic: a Python package with one parser module per supplier (`parsers/supplier_a.py`, etc.) behind a common interface (`parse(file) -> list[NormalizedRow]`), registered by `file_code`.
- **Two independent schedules, not one.** The 4×/day cadence in your scope governs how often we check the *supplier's* SFTP server — that's respected exactly as specified. Separately, a lightweight internal process checks our own database for any file that's been fetched but not yet parsed, on a much tighter loop (every few minutes) purely for reliability — so a crashed or stuck parse gets caught and retried quickly. This never touches a supplier's server and doesn't change how often we poll them; it's a self-healing mechanism sitting entirely on our side.
- **File size, stability check, marker files.** All of this can be handled natively by n8n with an SFTP node. A checksum can be performed using a Code node in concert with this to verify files are fully downloaded and uncorrupted. If you're self-hosting and configured correctly, file size shouldn't be a concern, but happy to discuss if there's a blocker there.
- **How the downloaded bytes reach Python is worth deciding together.** n8n's SFTP node can download directly. One connection, one place holding credentials in n8n's native vault. It supports files up to 2GB, though cloud memory limits typically make much above ~250MB impractical; since you're self-hosting via Docker, that shouldn't be a blocker if configured properly as mentioned above. From a maintainability standpoint, the native SFTP node is probably easier for the business to manage going forward when connecting supplier six. Let me know if you see it differently. We could instead handle this in a Python node, but that means credentials living outside n8n's vault.

  Once the file is downloaded to a temporary staging area, the Python node picks it up and stores it in PostgreSQL for later parsing. This actually exposes a limitation of using Python: n8n's SFTP node doesn't support file streams to a Python node. They do support file streams from the SFTP node to a JavaScript node. So using Python here, the file would need to land in temporary storage first before Python picks it up. Fine if you'd rather keep one language across the stack. Alternatively, we can switch this bit of work to JavaScript, which lets us stream straight into Postgres with no intermediary storage.

  These are minor implementation details we can navigate during the build.
### Data Model (Postgres)

- **Staging table + idempotent upsert, not direct writes.** Each ingestion run lands in a `staging_supplier_feed` table first. Plausibility checks run against staging vs. the last accepted snapshot in `current_state`. Only on pass does it promote to current state and append to history. This makes failed runs a no-op instead of a partial write you have to clean up. History itself can follow a temporal table pattern: rather than updating a row in place, the previous row is marked inactive with a timestamp and the new row is inserted as the current active one — giving a full audit trail of price/stock changes over time without a separate change-log table to maintain.
- **Dead-letter handling for unmatched rows**, not just a report — and worth being precise about the two levels this operates on. Whole-file plausibility checks (row count down >20%, >30% of SKUs at zero stock) abort the *entire* run — nothing promotes, you're notified. Row-level matching is separate and only applies to a run that already passed those checks: each row is matched independently, so a single run can partially succeed — most rows promote to `current_state` normally, while any row that doesn't match lands in `needs_review` with the raw source row preserved, without blocking or rolling back the rows around it. One unmapped SKU shouldn't hold up price/stock updates for the rest of that supplier's catalog.

  This raises a question worth deciding together: how do you want to handle resolving what lands in `needs_review`? Options range from someone manually confirming matches via direct SQL access, to a lightweight internal review screen, to a periodic export you review and feed back in. Also worth deciding: once a match is confirmed, how does that get written back into `sku_mapping` — manually, or through some tooling we build? This is a business-process decision as much as a technical one, so it's best settled with you rather than assumed.

### Handling Suppliers Without EAN/GTIN

Since you've flagged EAN/GTIN as the primary match key, here's the fallback chain I'd implement for suppliers who don't provide it:

1. **Supplier article number**, if you've previously confirmed a mapping (manual one-time crosswalk, stored in the mapping table like any other match — just flagged with `match_method = 'manual'` instead of `'ean'`).
2. **Deterministic fuzzy match** on manufacturer + manufacturer part number (MPN) or normalized title, surfaced as a *suggestion*, never auto-committed.
3. **Manual review queue**: anything that doesn't clear a high-confidence match lands in `needs_review` with your existing product data alongside the supplier's row, so you (or whoever owns purchasing) confirms the match once. Once confirmed, it's written to the mapping table and never needs review again for that pair.

This satisfies your "reporting rather than discarding" requirement and avoids the real risk with fuzzy matching — silently linking the wrong article and corrupting price/stock history for two unrelated SKUs.

### Analytics / Business Value

- **Supplier comparison** — a SQL view joining `sku_mapping` against `current_state`/`price_stock_history`, grouped by article, showing every supplier's current price and stock side by side for the same item. Historical price comes along for free, since the temporal table pattern already preserves every prior price as an inactive row rather than overwriting it.
- **Reorder suggestions** — one view combining three inputs: sales velocity from Shopify order data (Bulk Operations), your own physical stock read directly from Shopify's own inventory levels, and current supplier price/availability from `current_state`. Reading "own stock" straight from Shopify works cleanly here specifically because of your architecture principle — nothing but your warehouse ever writes to it, so it can be trusted as-is rather than reconciled from a second source. The view flags when velocity is outpacing available stock and shows which supplier(s) can currently cover the gap and at what price.
- **Purchase price increase alerts** — a scheduled n8n check comparing each SKU/supplier's newly-promoted price against the previous active record in `price_stock_history`. A jump past a threshold you set (e.g. >5%) fires through the same alert channel already built for feed failures — margin erosion is worth catching as it happens, not discovered later in a P&L review.
- **Delisting detection** — a query against `price_stock_history` flagging any article whose current-active row hasn't been refreshed across the last several runs, or that's been sitting at zero stock beyond a defined window. Either pattern usually means a supplier has quietly dropped the item, which is worth surfacing rather than assuming it's a data glitch.

All four are SQL views/materialized views over data the ingestion pipeline is already landing in Postgres — no separate integration or tooling required to produce them.

### Shopify Integration

- **Shopify's Bulk Operations run in the background, so the workflow needs to check back on them rather than expect an instant answer.** Pulling a large amount of data (e.g. a quarter's worth of orders, or your full product catalog, for the sales-velocity and reorder-suggestion calculations) can't be answered immediately (i.e. it's an asynchronous API call). Shopify starts the export as a background job and hands back a status you check on until it's ready, then a file to download once it is.

  I'd build this as a "check, wait a bit longer each time, check again" loop rather than checking on a fixed timer (this is called a poll-with-backoff), since a fixed interval either wastes time waiting after a fast export is already done, or burns through Shopify's rate limits re-checking a slow one too often. Either way, the workflow picks up the result automatically once it's ready.
- **Structured logging with a run ID** across the n8n → Python → Postgres boundary, so a single feed run can be traced end-to-end when something fails at 3am.

None of this changes your proposed stack — n8n, Postgres, Python, GraphQL Admin API are all sound choices for this job. It's implementation discipline on top of them.

### Operations

Docker Compose deployment on your own server, n8n's error-workflow feature wired to email/messenger for feed-failure alerting, and documentation covering the architecture, schema, and a step-by-step guide for connecting a new supplier — all as specified, with nothing here I'd change.

## Testing Strategy

The contract doesn't mention a test environment. Do you already have any test access set up — a spare SFTP login, a Shopify dev store — or should I assume there isn't one and build the testing setup as part of the project rather than depending on your infrastructure?

**Unit tests (no infrastructure required)**
Parsers, plausibility checks, and matching logic (EAN match, fuzzy fallback) are written as pure functions wherever possible — given a row or file, return a result. These are the cheapest and most valuable tests: they catch logic bugs (threshold math on the 20%/30% checks, matching edge cases) independent of any live environment, and run against fixture files rather than production data.

**Local "shadow" stack**
The same Docker Compose setup used for deployment doubles as a disposable local environment (n8n + Postgres + Python worker, spun up on my machine or a scratch VPS, no cost to the client). A mock SFTP container (e.g. `atmoz/sftp`) seeded with sample files stands in for the real supplier servers, which lets me construct edge cases on demand rather than waiting for them to occur naturally:
- Partially-uploaded / truncated file
- Stale file (backdated timestamp)
- Row count down >20% vs. previous run
- >30% of SKUs hit zero stock simultaneously
- Malformed CSV/XML

**Real sample files — requested up front**
Mock data catches logic bugs but won't catch real-world quirks (semicolon-delimited CSV, unexpected encoding, differently-nested XML). I'd ask for a handful of real or anonymized feed exports from each supplier as a Phase 0 dependency, before writing the pilot parser — estimating the pilot without at least one real file is guesswork.

**Shopify — testing against the live store carries no write risk**
Since the integration is read-only, there's no risk of corrupting the client's catalog or inventory during testing — no mutations are ever called. A scoped read-only custom app token is sufficient. A free Shopify Partner development store is useful for testing API mechanics (pagination, Bulk Operations polling) in isolation, but has no real sales history, so it can't validate the reorder-suggestion logic — that needs the real store's data.

**Dry-run mode built into the pipeline**
Beyond testing during development, I'd add a flag to the Python worker that runs the full ingest → parse → validate → match pipeline but stops short of promoting to `current_state`, logging what *would* have happened instead. This is useful for testing new suppliers safely against production infrastructure without a separate environment — including after handover, when the client onboards supplier six themselves.

**Lightweight CI**
A basic GitHub Actions workflow running the Python unit tests on every push, catching regressions before they reach the client's server. Low setup cost, worth including even at this project size.

## Ongoing support & maintenance (optional — flagging this either way)

The scope above (Pilot, then Rollout) doesn't include ongoing maintenance, and that's a reasonable way to structure the engagement — but I want to flag two maintenance realities now, before contract signature, rather than let them surface as surprises later. Even if you don't take me up on ongoing support, this is worth knowing:

- **Shopify's GraphQL API version has a hard 12-month clock.** Shopify ships a new API version every quarter, and each version stops working entirely — a hard `404`, not a warning — about a year after release. This isn't a "someday" risk; it's scheduled. Left untouched, the integration *will* break on a predictable date.
- **Python dependencies drift more quietly.** Libraries like pandas and lxml are actively maintained and low-risk by design, but security patches and version updates still need to be reviewed and applied periodically — nobody gets an error message the day this is neglected, which paradoxically makes it easier to ignore.

**What I'll build in regardless of whether you take ongoing support:**
- Dependency versions pinned in a lockfile, so nothing updates silently or breaks unexpectedly
- Automated update alerts configured on the repository (e.g. Dependabot or Renovate — free, no ongoing cost to you) that open a pull request when a library has a new version or a known vulnerability, so it's visible even without a formal support arrangement
- A short "maintenance checklist" in the documentation: what to check, roughly how often, and what a Shopify API version bump involves

**Optional add-on, if useful:** a light retainer (e.g. **[X] hours/quarter**) covering the Shopify version bump, reviewing and merging dependency update PRs, and a quick health check on the plausibility-check alerting. Entirely your call — the system is handed over either way in a state where your own team (or another developer) can maintain it without me.

## Comparable experience

- **[Project name]** — [1–2 sentences: what it did, stack used, scale (e.g. "X feeds, Y SKUs")]. [Repo link if shareable, or "code sample available on request" if under NDA.]
- **[Project name]** — ...
- **[Project name]** — ...

## Pricing & availability

- Pilot (Supplier 1, fixed price): **$1,240–$1,960** (~62–98 hrs across Phase 0 setup + Phase 1 pilot, at $20/hr), covering feed ingestion, data model, plausibility checks, Shopify read-only integration, Docker Compose deployment, documentation, and one handover session.
- Rollout (Suppliers 2–5 + analytics): **$1,080-$1,780**, estimated at **~7–12 hours per additional supplier** (~28–48 hrs total for Suppliers 2–5), **~18–28 hours** for the analytics layer, billed after pilot sign-off and **8–13 hours** for hardening/handoff.
- Availability: **[30 - 40 hours/week]**, start date **[immediate]**.

## Next step

Happy to hop on a short call to look at one real sample feed from your least-standard supplier — that's usually the fastest way to firm up the pilot estimate before either of us commits to a number.

Cory Christiansen

---

# 2. Development Roadmap

## Phase 0 — Setup (pre-pilot, 2–3 days / ~12–18 hrs)
- Repository, Docker Compose skeleton, environment/secrets handling
- Postgres schema migration tooling in place
- Credentials received and SFTP connectivity confirmed for Supplier 1
- Shopify app/API access confirmed, read-only scopes verified

## Phase 1 — Pilot: Supplier 1 (fixed price, 2–3 weeks / ~50–80 hrs)
1. **Ingestion** — SFTP fetch workflow in n8n; file stability check (checksum-based) and file-age validation; handoff to Python worker
2. **Parsing** — Supplier 1 parser module built against the shared interface; normalized rows written to staging
3. **Data model** — `current_state`, `price_stock_history`, `sku_mapping`, `needs_review` created and populated from Supplier 1's first successful run
4. **Plausibility checks** — row-count delta and zero-stock-spike checks implemented; failure path wired to n8n error workflow → email/messenger alert; no silent imports
5. **Matching logic** — EAN/GTIN primary match; fallback chain for unmatched rows (article number → fuzzy suggestion → manual review) feeding `needs_review`
6. **Shopify read-only integration** — GraphQL queries for product master data and sales history validated end-to-end (needed later for analytics, tested now so Phase 2 isn't blocked)
7. **Logging & alerting** — run-ID based structured logs across n8n → Python → Postgres; failure alerting confirmed with a deliberately broken test feed
8. **Documentation** — architecture overview, schema documentation, and a step-by-step "add a new supplier" guide, written against the parser interface so it's usable before Supplier 2 starts
9. **Handover session** — walkthrough of the running system, the mapping/review workflow, and the documentation

**Milestone:** Supplier 1 fully live, plausibility checks proven against at least one real failure scenario, client sign-off on pilot.

## Phase 2 — Rollout: Suppliers 2–5 (hourly, 1–2 weeks / ~28–48 hrs total)
Each additional supplier reuses the orchestration workflow, schema, and matching logic — only a new parser module and config entry are needed, so effort should drop sharply after Supplier 1:
- Supplier 2–5: parser module + format-specific edge cases + validation against real feed samples
- Any supplier-specific EAN gaps handled via the fallback chain already built in Phase 1

## Phase 3 — Analytics layer (~1 week / ~18–28 hrs, can run partly in parallel with late Phase 2)
- Supplier comparison view (article × supplier × price, current + historical)
- Reorder suggestion logic: sales velocity (Shopify) × own warehouse stock × supplier availability
- Purchase price increase alerts (threshold-based, feeding the existing alert channel)
- Delisting detection (article missing from feed N runs in a row, or zero stock sustained)
- *(If included)* Metabase dashboard wired to the above views

## Phase 4 — Hardening & final handover (1–2 days / ~8–13 hrs)
- Review of alerting thresholds with client based on real operating data
- Final documentation pass, including the "connect a new supplier" guide validated against Suppliers 2–5's onboarding
- Final handover session covering the full system and analytics layer
