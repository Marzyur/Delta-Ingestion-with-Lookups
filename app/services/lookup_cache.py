"""
Lookup Cache
════════════
Loads all `countries` and `customer_status` rows once per batch (or on
service startup) into plain Python dicts so every code → id resolution is O(1)
— completely eliminating N+1 queries across large batches.

Refresh strategy
────────────────
• The cache is refreshed at the start of each ingestion request.
  This ensures newly seeded lookups are visible without restarting the process.
• For very high-throughput deployments a TTL-based refresh (e.g. 5 min) can be
  used instead by calling `refresh_if_stale()`.
"""
import time
from dataclasses import dataclass, field

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass
class LookupCache:
    countries: dict[str, int] = field(default_factory=dict)   # code -> id
    statuses: dict[str, int] = field(default_factory=dict)    # code -> id
    _loaded_at: float = field(default=0.0, repr=False)

    # ── Public API ────────────────────────────────────────────────────────────

    async def load(self, session: AsyncSession) -> None:
        """(Re)load all lookup tables from DB."""
        countries_rows = await session.execute(text("SELECT id, code FROM countries"))
        self.countries = {str(row.code).upper(): row.id for row in countries_rows}

        status_rows = await session.execute(text("SELECT id, code FROM customer_status"))
        self.statuses = {str(row.code).upper(): row.id for row in status_rows}

        self._loaded_at = time.monotonic()

    def resolve_country(self, code: str) -> int | None:
        return self.countries.get(code.upper())

    def resolve_status(self, code: str) -> int | None:
        return self.statuses.get(code.upper())

    @property
    def is_empty(self) -> bool:
        return not self.countries and not self.statuses
