"""
Pydantic schemas for the Customer Ingestion API.
"""
from typing import Annotated

from pydantic import BaseModel, EmailStr, Field, StringConstraints


# ── Inbound record (one element inside the payload list) ─────────────────────

class CustomerRecord(BaseModel):
    external_id: Annotated[str, StringConstraints(min_length=1, max_length=255)]
    name: Annotated[str, StringConstraints(min_length=1, max_length=255)]
    email: EmailStr | None = None
    country_code: Annotated[str, StringConstraints(min_length=1, max_length=10)]
    status_code: Annotated[str, StringConstraints(min_length=1, max_length=50)]


# ── Top-level request body ────────────────────────────────────────────────────

class IngestRequest(BaseModel):
    customers: list[CustomerRecord] = Field(
        ...,
        min_length=1,
        description="List of customer records to ingest (up to 10 M).",
    )


# ── Per-batch failure detail ──────────────────────────────────────────────────

class FailedRecord(BaseModel):
    external_id: str
    reason: str


# ── API response ──────────────────────────────────────────────────────────────

class IngestResponse(BaseModel):
    received: int = Field(..., description="Total records received in the request.")
    inserted: int = Field(..., description="New records successfully written to DB.")
    skipped_existing: int = Field(..., description="Records skipped because external_id already exists.")
    failed: int = Field(..., description="Records that could not be inserted (validation / missing lookup).")
    failed_records: list[FailedRecord] = Field(
        default_factory=list,
        description="Details of failed records (external_id + reason).",
    )