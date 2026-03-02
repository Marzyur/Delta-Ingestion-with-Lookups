"""Initial schema: countries, customer_status, customers

Revision ID: 0001_initial
Revises:
Create Date: 2024-01-01 00:00:00
"""
from alembic import op
import sqlalchemy as sa

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── countries ─────────────────────────────────────────────────────────────
    op.create_table(
        "countries",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("code", sa.String(10), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
    )
    op.create_unique_constraint("uq_countries_code", "countries", ["code"])
    op.create_index("ix_countries_code", "countries", ["code"])

    # ── customer_status ───────────────────────────────────────────────────────
    op.create_table(
        "customer_status",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("code", sa.String(50), nullable=False),
        sa.Column("label", sa.String(100), nullable=False),
    )
    op.create_unique_constraint("uq_customer_status_code", "customer_status", ["code"])
    op.create_index("ix_customer_status_code", "customer_status", ["code"])

    # ── customers ─────────────────────────────────────────────────────────────
    op.create_table(
        "customers",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("external_id", sa.String(255), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("email", sa.String(320), nullable=True),
        sa.Column("country_id", sa.Integer(), sa.ForeignKey("countries.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("status_id", sa.Integer(), sa.ForeignKey("customer_status.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_unique_constraint("uq_customers_external_id", "customers", ["external_id"])
    op.create_index("ix_customers_external_id", "customers", ["external_id"])

    # Seed reference data
    op.execute("""
        INSERT INTO countries (code, name) VALUES
        ('US', 'United States'),
        ('GB', 'United Kingdom'),
        ('DE', 'Germany'),
        ('FR', 'France'),
        ('IN', 'India'),
        ('AU', 'Australia'),
        ('CA', 'Canada'),
        ('JP', 'Japan'),
        ('BR', 'Brazil'),
        ('MX', 'Mexico')
    """)
    op.execute("""
        INSERT INTO customer_status (code, label) VALUES
        ('active',    'Active'),
        ('inactive',  'Inactive'),
        ('pending',   'Pending Verification'),
        ('suspended', 'Suspended'),
        ('churned',   'Churned')
    """)


def downgrade() -> None:
    op.drop_table("customers")
    op.drop_table("customer_status")
    op.drop_table("countries")