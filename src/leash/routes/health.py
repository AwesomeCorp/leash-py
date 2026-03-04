"""Health check endpoints."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter()


@router.get("/health")
@router.get("/api/health")
async def get_health() -> JSONResponse:
    """Return service health status."""
    return JSONResponse(
        content={
            "status": "healthy",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "version": "0.1.0",
        }
    )
