"""
ORM models.

Design decisions
────────────────
• countries.code   — UNIQUE + B-tree index  → O(1) lookup by code
• customer_status.code — same as above
• customers.external_id — UNIQUE + B-tree index → O(1) diff computation
  for up to 10 M records via IN-clause batch queries
"""
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.engine import Base


class Country(Base):
    __tablename__ = "countries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(10), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)

    __table_args__ = (
        UniqueConstraint("code", name="uq_countries_code"),
        Index("ix_countries_code", "code"),  # explicit B-tree
    )


class CustomerStatus(Base):
    __tablename__ = "customer_status"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    label: Mapped[str] = mapped_column(String(100), nullable=False)

    __table_args__ = (
        UniqueConstraint("code", name="uq_customer_status_code"),
        Index("ix_customer_status_code", "code"),
    )


class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(320), nullable=True)

    country_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("countries.id", ondelete="RESTRICT"), nullable=False
    )
    status_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("customer_status.id", ondelete="RESTRICT"), nullable=False
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    country: Mapped["Country"] = relationship("Country", lazy="noload")
    status: Mapped["CustomerStatus"] = relationship("CustomerStatus", lazy="noload")

    __table_args__ = (
        UniqueConstraint("external_id", name="uq_customers_external_id"),
        # Primary diff-lookup index — critical for 10 M-row performance
        Index("ix_customers_external_id", "external_id"),
    )