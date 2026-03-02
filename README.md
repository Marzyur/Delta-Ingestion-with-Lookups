# Customer Ingestion API

A high-throughput bulk-ingestion API for customer records built with FastAPI, asyncpg, and PostgreSQL.
Handles **up to 10 M records per request** via a chunked delta engine that only writes net-new rows.

---

## API Contract

### `POST /api/v1/ingest`

Accepts a JSON body with a list of customer records and returns a summary.

**Request**

```json
{
  "customers": [
    {
      "external_id": "cust-001",
      "name": "Alice Smith",
      "email": "alice@example.com",
      "country_code": "US",
      "status_code": "active"
    }
  ]
}
```

| Field          | Type   | Required | Notes                              |
|----------------|--------|----------|------------------------------------|
| `external_id`  | string | ✅        | Natural key; 1–255 chars           |
| `name`         | string | ✅        | 1–255 chars                        |
| `email`        | string | ❌        | Must be valid email format if set  |
| `country_code` | string | ✅        | Must exist in `countries` table    |
| `status_code`  | string | ✅        | Must exist in `customer_status`    |

**Response — `200 OK`**

```json
{
  "received": 1000,
  "inserted": 850,
  "skipped_existing": 130,
  "failed": 20,
  "failed_records": [
    { "external_id": "cust-999", "reason": "Unknown country_code 'XX'" }
  ]
}
```

| Field              | Description                                             |
|--------------------|---------------------------------------------------------|
| `received`         | Total records in the request body                       |
| `inserted`         | Rows successfully written to the DB (net-new only)      |
| `skipped_existing` | Records whose `external_id` already existed in DB       |
| `failed`           | Records that could not be inserted                      |
| `failed_records`   | Per-record details for failed rows                      |

### `GET /api/v1/health`

Returns `{ "status": "ok", "db": "reachable" }` or `503` if the DB is down.

### `GET /api/v1/lookups`

Returns all valid `country_code` and `status_code` values.

---

## Idempotency Strategy

**Natural key**: `external_id`

Every ingest request runs a **diff** before writing:

1. Extract all `external_id` values from the current batch.
2. Query: `SELECT external_id FROM customers WHERE external_id = ANY($1)`.
3. Use a Python `set` to compute the delta: `incoming − existing`.
4. Only insert the delta.

This means the same payload can be sent multiple times safely — duplicates are counted as `skipped_existing`, not errors.

**Race condition handling**: if two concurrent requests try to insert the same `external_id`, the `UNIQUE` constraint on `customers.external_id` fires. The engine catches `UniqueViolationError` and falls back to `INSERT … ON CONFLICT DO NOTHING`, so no data is lost and no error is surfaced.

---

## Architecture & Complexity

```
POST /ingest
     │
     ▼
Pydantic validation  O(N)   — field-level checks before any DB I/O
     │
     ▼
Load lookup cache    O(L)   — one query each for countries + statuses (L << N)
     │
     ▼
┌─── For each 100k batch ────────────────────────────────────────────────┐
│  Resolve codes → IDs    O(B)   — dict lookup, zero DB round-trips      │
│  Diff (IN query + set)  O(B)   — one query per batch                   │
│  COPY bulk insert        O(D)   — asyncpg COPY protocol (fastest path) │
└────────────────────────────────────────────────────────────────────────┘
     │
     ▼
Aggregate & return summary
```

**Total time complexity: O(N)** where N = number of input records.
**Space complexity: O(B)** per batch (B = 100 000), never O(N) all at once.

### Key design decisions

| Concern | Solution |
|---|---|
| N+1 queries | In-memory lookup cache loaded once; O(1) per record |
| Large payloads | Chunked 100k batches; bounded memory regardless of N |
| Duplicate prevention | `UNIQUE` on `external_id` + Python diff before insert |
| Write throughput | `asyncpg.copy_records_to_table` (PostgreSQL COPY protocol) |
| Batch atomicity | Each 100k batch is its own SQL transaction; failures are isolated |
| Connection exhaustion on Vercel | `pool_size=2, max_overflow=3`; use PgBouncer/Neon pooler |
| Concurrent race conditions | Fallback to `INSERT … ON CONFLICT DO NOTHING` |

---

## Setup

### Prerequisites

- Python 3.11+
- PostgreSQL 14+ (or Neon / Supabase)

### Local Development

```bash
# 1. Clone & create venv
git clone <repo-url>
cd customer-ingestion-api
python -m venv venv && source venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure environment
cp .env.example .env
# Edit .env and set DATABASE_URL

# 4. Run migrations
alembic upgrade head

# 5. Start the server
uvicorn app.main:app --reload --port 8000
```

### Run Tests

```bash
pytest tests/ -v
```

---

## Deployment (Vercel)

### One-time setup

1. Push repo to GitHub (private repository recommended).
2. Import project in [Vercel Dashboard](https://vercel.com/new).
3. Set environment variable `DATABASE_URL` in Vercel project settings.
   - Use a **pooled** connection string from Neon or Supabase to avoid exhausting
     PostgreSQL connections across serverless invocations.
4. Run migrations once from your local machine or a CI step:
   ```bash
   DATABASE_URL=<prod-url> alembic upgrade head
   ```

### CI/CD

Every push to `main` triggers an automatic Vercel production deployment.
For branch previews, Vercel creates isolated preview URLs per PR.

### `vercel.json` highlights

```json
{
  "functions": {
    "app/main.py": { "maxDuration": 300 }
  }
}
```

`maxDuration: 300` requires Vercel **Pro** tier. On the free tier (max 60s),
the 100k chunk size keeps each batch well within the timeout.

---

## Database Schema

```sql
-- Lookup tables (small, cached in memory)
CREATE TABLE countries (
    id   SERIAL PRIMARY KEY,
    code VARCHAR(10)  NOT NULL,
    name VARCHAR(100) NOT NULL,
    CONSTRAINT uq_countries_code UNIQUE (code)
);
CREATE INDEX ix_countries_code ON countries (code);

CREATE TABLE customer_status (
    id    SERIAL PRIMARY KEY,
    code  VARCHAR(50)  NOT NULL,
    label VARCHAR(100) NOT NULL,
    CONSTRAINT uq_customer_status_code UNIQUE (code)
);
CREATE INDEX ix_customer_status_code ON customer_status (code);

-- Main table (up to 10M+ rows)
CREATE TABLE customers (
    id          BIGSERIAL PRIMARY KEY,
    external_id VARCHAR(255) NOT NULL,
    name        VARCHAR(255) NOT NULL,
    email       VARCHAR(320),
    country_id  INTEGER NOT NULL REFERENCES countries(id),
    status_id   INTEGER NOT NULL REFERENCES customer_status(id),
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT uq_customers_external_id UNIQUE (external_id)
);
-- B-tree index for O(log N) diff lookups across 10M rows
CREATE INDEX ix_customers_external_id ON customers (external_id);
```

---

## Project Structure

```
customer-ingestion-api/
├── app/
│   ├── api/
│   │   └── routes.py          # FastAPI endpoints
│   ├── core/
│   │   ├── config.py          # Pydantic settings from .env
│   │   └── logging.py         # Structured logging setup
│   ├── db/
│   │   └── engine.py          # Async SQLAlchemy engine + session factory
│   ├── models/
│   │   └── models.py          # ORM models with indexes & constraints
│   ├── schemas/
│   │   └── customer.py        # Pydantic request/response models
│   ├── services/
│   │   ├── ingestion.py       # Delta engine (core business logic)
│   │   └── lookup_cache.py    # O(1) in-memory lookup cache
│   └── main.py                # FastAPI app factory
├── alembic/
│   ├── versions/
│   │   └── 0001_initial.py    # Initial schema migration
│   └── env.py
├── tests/
│   └── test_ingestion.py      # Unit tests
├── .env.example
├── .gitignore
├── alembic.ini
├── requirements.txt
├── vercel.json
└── README.md
```