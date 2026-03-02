"""
Application entry point.
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.core.logging import setup_logging

setup_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup — nothing special; connection pool is lazy-initialized by SQLAlchemy
    yield
    # Shutdown — dispose connection pool gracefully
    from app.db.engine import engine
    await engine.dispose()


app = FastAPI(
    title="Customer Ingestion API",
    version="1.0.0",
    description=(
        "High-throughput bulk ingestion API for customer records. "
        "Supports up to 10 M records per request via chunked delta processing."
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api/v1")