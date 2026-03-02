"""
API Routes
══════════
POST /ingest  — Main ingestion endpoint.
GET  /health  — Liveness probe (Vercel + uptime monitors).
GET  /lookups — Returns current countries and statuses (useful for debugging).
"""
import logging

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import text

from app.db.engine import engine
from app.schemas.customer import IngestRequest, IngestResponse
from app.services.ingestion import ingest_customers

logger = logging.getLogger("customer_ingestion.api")
router = APIRouter()


@router.get("/health", tags=["ops"])
async def health_check():
    """Vercel liveness probe — also pings the DB."""
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return {"status": "ok", "db": "reachable"}
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Database unreachable: {exc}",
        )


@router.get("/lookups", tags=["ops"])
async def get_lookups():
    """Return all valid country and status codes (handy for clients)."""
    async with engine.connect() as conn:
        countries = await conn.execute(text("SELECT code, name FROM countries ORDER BY code"))
        statuses = await conn.execute(text("SELECT code, label FROM customer_status ORDER BY code"))
    return {
        "countries": [{"code": r.code, "name": r.name} for r in countries],
        "statuses": [{"code": r.code, "label": r.label} for r in statuses],
    }


@router.post(
    "/ingest",
    response_model=IngestResponse,
    status_code=status.HTTP_200_OK,
    tags=["ingestion"],
    summary="Bulk-ingest customer records",
    description=(
        "Accepts up to 10 M customer records. "
        "Applies idempotency via `external_id` — existing records are skipped, not updated. "
        "Processing is chunked into 100 k batches internally."
    ),
)
async def ingest(body: IngestRequest) -> IngestResponse:
    logger.info("Received ingest request: %d records", len(body.customers))
    try:
        result = await ingest_customers(body.customers)
    except Exception as exc:
        logger.error("Unhandled ingestion error: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Ingestion failed. Check server logs.",
        )
    logger.info(
        "Ingestion complete — received=%d inserted=%d skipped=%d failed=%d",
        result.received, result.inserted, result.skipped_existing, result.failed,
    )
    return result