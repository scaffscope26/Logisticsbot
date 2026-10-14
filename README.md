# Florida Logistics Control Tower — v0.1

A working local prototype for importing Avontus Quantify Excel/CSV exports, viewing a 30-day material forecast, matching part-level supply against reservations, and recording proposed decisions. **No Supabase connection or Quantify write-back yet.**

## Start

1. Install Python 3.10+ and `pip install -r requirements.txt`.
2. Run `python generate_sample.py` to create four illustrative CSV files.
3. Run `python server.py`.
4. Open http://127.0.0.1:8765 in your browser.
5. Use **Import spreadsheets** to upload the four files from `sample_data/`, or your own Quantify exports. Map the required columns before import.

Data persists in a local SQLite file `logistics.db` beside the source code. The database is created on first run. Delete it only if you intend to reset all imports and decisions.

## Limitations / next iteration

## Verification

Run `python -m unittest discover -s tests -v` after installing dependencies.
Tests use a temporary SQLite database and cover CSV snapshot validation, Excel
dates and text part numbers, sample matching, supply allocation limits, inspection
timing, and persisted decisions. Sample dates are shifted during tests so the
matching check remains useful after the original sample horizon expires.

## Vercel deployment prerequisite

This ZIP is a local Python/SQLite prototype, not a Vercel-ready application.
Its long-running HTTP server and local database must be adapted before deployment.
Keep Excel/CSV parsing and deterministic matching; introduce authenticated API
routes and a durable storage adapter (future Supabase), with approval-aware
allocation locking. Do not rely on a function's local SQLite file for shared,
persistent production data. No Vercel deployment configuration is included yet.

## Known persistence limitation

Opportunity IDs currently include positional supply identifiers. Replacing or
reordering a snapshot can associate a saved decision with a different source.
Internal approval statuses are annotations, not durable inventory reservations.
Use this version for synthetic workflow testing; stable source identities and
approval-aware allocations are prerequisites for operational use.

## Prototype limitations

- Single-user local-only development server, **not secure for public deployment**. Do not expose to the internet or upload sensitive company data to an untrusted computer.
- Exact part matching only; no approved substitution rules yet.
- The engine reserves candidate supply for proposals during each calculation to prevent duplicate suggested allocations. It does not create actual Quantify reservations.
- Cross-branch matches do not yet calculate travel time, freight, load capacity, or landed cost; all require manual validation.
- Returns use a configurable-in-code two-day inspection allowance; project forecasts are never considered confirmed inventory.
- Imports replace the complete snapshot of a single report type. Upload full report extracts, not incremental deltas.
- Import mappings are manual and should be refined once real Quantify report headings are known.
- Current prototype uses today's system date to define the 30-day horizon.
- No production auth, background refresh, audit-grade version history, concurrency controls, or Supabase integration yet.

## Future Supabase migration

The `records`, `imports`, and `decisions` persistence layer is isolated in `engine.py`. Move these to normalized PostgreSQL tables with row-level security and audit logs, then deploy the UI/API behind authenticated server routes. Preserve the matching engine's deterministic rules and add approval-aware reservation locks.
