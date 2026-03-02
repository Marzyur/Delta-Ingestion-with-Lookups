"""
Delta Ingestion Engine
══════════════════════

Algorithm (per 100 k batch)
────────────────────────────
1. VALIDATE   — Pydantic already ran; here we resolve lookup codes → IDs.
                Records with unknown country/status are moved to `failed`.
2. DIFF       — Bulk-fetch existing external_ids from DB using a single IN query.
                Build a Python set for O(1) membership test.
3. INSERT     — asyncpg copy_records_to_table for maximum write throughput.
4. TRANSACTION— Each batch is wrapped in its own transaction so a single bad
                batch doesn't poison the whole request.

Complexity
──────────
• Lookup resolution:  O(1) per record  (dict lookup, no DB round trip)
• Diff computation:   O(B)             (one IN query + Python set ops per batch)
• Insertion:          O(N log N) → near-linear via COPY protocol
  Total:              O(N)  where N = total records
"""
import asyncio
import logging
from itertools import islice
from typing import AsyncGenerator, Sequence

import asyncpg
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, AsyncConnection

from app.core.config import get_settings
from app.db.engine import engine
from app.schemas.customer import CustomerRecord, FailedRecord, IngestResponse
from app.services.lookup_cache import LookupCache

logger = logging.getLogger("customer_ingestion.engine")
settings = get_settings()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _chunked(iterable, size: int):
    """Yield successive `size`-sized chunks from an iterable."""
    it = iter(iterable)
    while chunk := list(islice(it, size)):
        yield chunk


# ── Per-batch processing ──────────────────────────────────────────────────────

async def _process_batch(
    batch: list[CustomerRecord],
    cache: LookupCache,
    raw_conn: asyncpg.Connection,
    session: AsyncSession,
) -> tuple[int, int, list[FailedRecord]]:
    """
    Process a single batch of ≤ BATCH_SIZE records.

    Returns (inserted, skipped_existing, failed_records).
    """
    inserted = 0
    skipped = 0
    failed: list[FailedRecord] = []

    # ── Step 1: Resolve lookup codes → IDs (O(1) per record) ─────────────────
    resolved: list[tuple[str, str, str | None, int, int]] = []  # (ext_id, name, email, country_id, status_id)
    seen_external_ids: set[str] = set()

    for rec in batch:
        ext_id = rec.external_id
        if ext_id in seen_external_ids:
            failed.append(FailedRecord(external_id=ext_id, reason="Duplicate external_id in payload"))
            continue
        seen_external_ids.add(ext_id)

        country_id = cache.resolve_country(rec.country_code)
        status_id = cache.resolve_status(rec.status_code)

        if country_id is None:
            failed.append(FailedRecord(external_id=rec.external_id, reason=f"Unknown country_code '{rec.country_code}'"))
            continue
        if status_id is None:
            failed.append(FailedRecord(external_id=rec.external_id, reason=f"Unknown status_code '{rec.status_code}'"))
            continue

        resolved.append((rec.external_id, rec.name, rec.email, country_id, status_id))

    if not resolved:
        return inserted, skipped, failed

    # ── Step 2: Diff — one IN query, then Python set subtraction ─────────────
    batch_external_ids = [r[0] for r in resolved]

    # Use raw asyncpg for maximum throughput on large IN clauses
    existing_rows = await raw_conn.fetch(
        "SELECT external_id FROM customers WHERE external_id = ANY($1::text[])",
        batch_external_ids,
    )
    existing_ids: set[str] = {row["external_id"] for row in existing_rows}
    skipped = len(existing_ids)

    # Delta = records whose external_id is NOT already in DB
    delta = [r for r in resolved if r[0] not in existing_ids]

    if not delta:
        return inserted, skipped, failed

    # ── Step 3: Bulk insert via COPY protocol (asyncpg) ───────────────────────
    try:
        async with raw_conn.transaction():
            inserted_count = await raw_conn.copy_records_to_table(
                "customers",
                records=delta,
                columns=["external_id", "name", "email", "country_id", "status_id"],
            )
            inserted = len(delta)
            logger.debug("Batch inserted %d records via COPY", inserted)
    except asyncpg.UniqueViolationError as exc:
        # Race condition: another request inserted some of these between our
        # diff query and our COPY. Fall back to row-by-row with ON CONFLICT DO NOTHING.
        logger.warning("UniqueViolation during COPY, falling back to upsert: %s", exc)
        inserted, failed_records = await _fallback_upsert(delta, raw_conn)
        failed.extend(failed_records)
    except Exception as exc:
        logger.error("Batch failed: %s", exc, exc_info=True)
        for ext_id, *_ in delta:
            failed.append(FailedRecord(external_id=ext_id, reason=str(exc)))

    return inserted, skipped, failed


async def _fallback_upsert(
    delta: list[tuple],
    conn: asyncpg.Connection,
) -> tuple[int, list[FailedRecord]]:
    """
    Row-by-row fallback when bulk COPY hits a race-condition unique violation.
    Uses INSERT … ON CONFLICT DO NOTHING so duplicates are silently skipped.
    """
    inserted = 0
    failed: list[FailedRecord] = []

    stmt = """
        INSERT INTO customers (external_id, name, email, country_id, status_id)
        VALUES ($1, $2, $3, $4, $5)
        ON CONFLICT (external_id) DO NOTHING
    """
    for row in delta:
        try:
            result = await conn.execute(stmt, *row)
            # asyncpg returns "INSERT 0 N" — parse N
            count = int(result.split()[-1])
            inserted += count
        except Exception as exc:
            failed.append(FailedRecord(external_id=row[0], reason=str(exc)))

    return inserted, failed


# ── Public entry point ────────────────────────────────────────────────────────

async def ingest_customers(records: list[CustomerRecord]) -> IngestResponse:
    """
    Orchestrate the full ingestion pipeline.

    1. Acquire a raw asyncpg connection (bypass SQLAlchemy ORM overhead).
    2. Load lookup cache once for the entire request.
    3. Process in BATCH_SIZE chunks — each chunk is an independent transaction.
    4. Aggregate and return the summary response.
    """
    total_received = len(records)
    total_inserted = 0
    total_skipped = 0
    all_failed: list[FailedRecord] = []

    # Acquire raw asyncpg connection from SQLAlchemy's pool
    async with engine.connect() as sa_conn:
        raw_conn: asyncpg.Connection = await sa_conn.get_raw_connection()
        # SQLAlchemy wraps asyncpg — unwrap to reach the real asyncpg connection
        raw_conn = raw_conn.driver_connection  # type: ignore[attr-defined]

        # ── Load lookup cache once ────────────────────────────────────────────
        cache = LookupCache()
        # Use a fresh session just for the cache load
        async with engine.connect() as cache_conn:
            result_countries = await cache_conn.execute(text("SELECT id, code FROM countries"))
            cache.countries = {str(row.code).upper(): row.id for row in result_countries}

            result_statuses = await cache_conn.execute(text("SELECT id, code FROM customer_status"))
            cache.statuses = {str(row.code).upper(): row.id for row in result_statuses}

        logger.info(
            "Lookup cache loaded: %d countries, %d statuses",
            len(cache.countries), len(cache.statuses),
        )

        # ── Process in batches ────────────────────────────────────────────────
        batch_num = 0
        for batch in _chunked(records, settings.BATCH_SIZE):
            batch_num += 1
            logger.info(
                "Processing batch %d (%d records)…", batch_num, len(batch)
            )
            try:
                b_inserted, b_skipped, b_failed = await _process_batch(
                    batch, cache, raw_conn, sa_conn  # type: ignore[arg-type]
                )
            except Exception as exc:
                # Catastrophic batch failure — mark entire batch as failed
                logger.error("Catastrophic failure in batch %d: %s", batch_num, exc, exc_info=True)
                b_inserted, b_skipped = 0, 0
                b_failed = [
                    FailedRecord(external_id=r.external_id, reason=f"Batch error: {exc}")
                    for r in batch
                ]

            total_inserted += b_inserted
            total_skipped += b_skipped
            all_failed.extend(b_failed)

            logger.info(
                "Batch %d done — inserted=%d skipped=%d failed=%d",
                batch_num, b_inserted, b_skipped, len(b_failed),
            )

    return IngestResponse(
        received=total_received,
        inserted=total_inserted,
        skipped_existing=total_skipped,
        failed=len(all_failed),
        failed_records=all_failed,
    )