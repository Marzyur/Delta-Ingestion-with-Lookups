"""
Unit tests for the ingestion service.
Run with: pytest tests/ -v
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.schemas.customer import CustomerRecord, FailedRecord
from app.services.lookup_cache import LookupCache
from app.services.ingestion import _chunked


# ── Helper fixtures ───────────────────────────────────────────────────────────

def make_record(**kwargs) -> CustomerRecord:
    defaults = {
        "external_id": "ext-001",
        "name": "Alice",
        "email": "alice@example.com",
        "country_code": "US",
        "status_code": "active",
    }
    defaults.update(kwargs)
    return CustomerRecord(**defaults)


@pytest.fixture
def cache() -> LookupCache:
    c = LookupCache()
    c.countries = {"US": 1, "GB": 2}
    c.statuses = {"ACTIVE": 1, "INACTIVE": 2}
    return c


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestChunking:
    def test_exact_multiple(self):
        data = list(range(6))
        chunks = list(_chunked(data, 2))
        assert chunks == [[0, 1], [2, 3], [4, 5]]

    def test_remainder(self):
        data = list(range(5))
        chunks = list(_chunked(data, 3))
        assert chunks == [[0, 1, 2], [3, 4]]

    def test_empty(self):
        assert list(_chunked([], 100)) == []

    def test_larger_than_data(self):
        data = [1, 2]
        assert list(_chunked(data, 100)) == [[1, 2]]


class TestLookupCache:
    def test_resolve_existing(self, cache):
        assert cache.resolve_country("US") == 1
        assert cache.resolve_status("active") == 1

    def test_resolve_missing_returns_none(self, cache):
        assert cache.resolve_country("ZZ") is None
        assert cache.resolve_status("vip") is None

    def test_is_empty_false_when_loaded(self, cache):
        assert not cache.is_empty

    def test_is_empty_true_on_fresh(self):
        assert LookupCache().is_empty


class TestPydanticValidation:
    def test_valid_record(self):
        r = make_record()
        assert r.external_id == "ext-001"

    def test_missing_external_id_raises(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            CustomerRecord(name="Bob", country_code="US", status_code="active")

    def test_empty_external_id_raises(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            make_record(external_id="")

    def test_invalid_email_raises(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            make_record(email="not-an-email")

    def test_none_email_is_ok(self):
        r = make_record(email=None)
        assert r.email is None


class TestIngestResponse:
    def test_response_fields(self):
        from app.schemas.customer import IngestResponse
        resp = IngestResponse(
            received=100,
            inserted=80,
            skipped_existing=15,
            failed=5,
            failed_records=[FailedRecord(external_id="x", reason="bad code")],
        )
        assert resp.received == 100
        assert resp.inserted == 80
        assert resp.skipped_existing == 15
        assert resp.failed == 5
        assert len(resp.failed_records) == 1
