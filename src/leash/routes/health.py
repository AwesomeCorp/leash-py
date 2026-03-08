"""Health check and shutdown endpoints."""

from __future__ import annotations

import asyncio
import logging
import signal
from datetime import datetime, timezone

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from starlette.background import BackgroundTask

from leash import __version__

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/health")
@router.get("/api/health")
async def get_health() -> JSONResponse:
    """Return service health status."""
    return JSONResponse(
        content={
            "status": "healthy",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "version": __version__,
        }
    )


async def _deferred_shutdown() -> None:
    """Send SIGINT after a brief delay, executed as a background task
    so the HTTP response is fully sent first."""
    await asyncio.sleep(0.3)
    signal.raise_signal(signal.SIGINT)


@router.post("/api/shutdown")
async def shutdown() -> JSONResponse:
    """Initiate graceful server shutdown.

    Uses a BackgroundTask so the HTTP response is fully sent before
    the signal fires.  ``signal.raise_signal`` is used instead of
    ``os.kill`` for correct cross-platform behavior.
    """
    logger.info("Shutdown requested via API")
    return JSONResponse(
        content={"status": "shutting_down"},
        background=BackgroundTask(_deferred_shutdown),
    )
