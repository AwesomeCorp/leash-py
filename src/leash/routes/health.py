"""Health check and shutdown endpoints."""

from __future__ import annotations

import logging
import os
import signal
import threading
from datetime import datetime, timezone

from fastapi import APIRouter
from fastapi.responses import JSONResponse

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


def _send_shutdown_signal() -> None:
    """Send SIGINT to the current process from a non-event-loop thread.

    This runs on a ``threading.Timer`` so the HTTP response is fully sent
    before the signal fires.  Sending from a separate thread ensures the
    ``KeyboardInterrupt`` raised by the signal handler interrupts the main
    event loop from the outside, triggering proper uvicorn shutdown.
    """
    os.kill(os.getpid(), signal.SIGINT)


@router.post("/api/shutdown")
async def shutdown() -> JSONResponse:
    """Initiate graceful server shutdown.

    Schedules a SIGINT via ``threading.Timer`` so the signal arrives from
    outside the asyncio event loop.  This lets the ``KeyboardInterrupt``
    properly interrupt uvicorn's main loop and trigger lifespan shutdown.
    """
    logger.info("Shutdown requested via API")
    timer = threading.Timer(0.5, _send_shutdown_signal)
    timer.daemon = True
    timer.start()
    return JSONResponse(content={"status": "shutting_down"})
