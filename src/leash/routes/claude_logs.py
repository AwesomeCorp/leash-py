"""Claude transcript browsing and SSE streaming."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)
router = APIRouter()


def _get_transcript_watcher(request: Request) -> Any:
    return getattr(request.app.state, "transcript_watcher", None)


def _validate_session_id(session_id: str) -> str | None:
    """Validate transcript session ID for path traversal. Returns error message or None."""
    if not session_id or not session_id.strip():
        return "SessionId is required"
    if ".." in session_id or "/" in session_id or "\\" in session_id:
        return "Invalid session ID"
    return None


@router.get("/api/claude-logs/projects")
async def get_projects(request: Request) -> JSONResponse:
    """List available Claude projects with transcripts."""
    watcher = _get_transcript_watcher(request)
    if watcher is None:
        return JSONResponse(content=[])

    try:
        projects = watcher.get_projects()
        return JSONResponse(content=projects)
    except Exception as exc:
        logger.error("Failed to list projects: %s", exc)
        return JSONResponse(status_code=500, content={"error": "Failed to list projects"})


@router.get("/api/claude-logs/transcript/{session_id}")
async def get_transcript(request: Request, session_id: str) -> JSONResponse:
    """Get transcript entries for a specific session."""
    error = _validate_session_id(session_id)
    if error:
        return JSONResponse(status_code=400, content={"error": error})

    watcher = _get_transcript_watcher(request)
    if watcher is None:
        return JSONResponse(content=[])

    try:
        entries = watcher.get_transcript(session_id)
        return JSONResponse(content=entries)
    except Exception as exc:
        logger.error("Failed to get transcript for session %s: %s", session_id, exc)
        return JSONResponse(status_code=500, content={"error": "Failed to get transcript"})


@router.get("/api/claude-logs/transcript/{session_id}/stream")
async def stream_transcript(request: Request, session_id: str):
    """SSE live transcript stream for a specific session."""
    error = _validate_session_id(session_id)
    if error:
        return JSONResponse(status_code=400, content={"error": error})

    watcher = _get_transcript_watcher(request)
    if watcher is None:
        return JSONResponse(status_code=503, content={"error": "Transcript watcher not available"})

    try:
        from sse_starlette.sse import EventSourceResponse

        queue: asyncio.Queue = asyncio.Queue()

        def on_transcript_updated(sender, args):
            if getattr(args, "session_id", None) != session_id:
                return
            for entry in getattr(args, "new_entries", []):
                try:
                    queue.put_nowait(entry)
                except Exception:
                    pass

        watcher.transcript_updated += on_transcript_updated

        async def event_generator():
            try:
                yield {"event": "connected", "data": ""}
                while True:
                    try:
                        entry = await asyncio.wait_for(queue.get(), timeout=30.0)
                        yield {"data": json.dumps(entry)}
                    except asyncio.TimeoutError:
                        # Send keepalive
                        yield {"comment": "keepalive"}
            except asyncio.CancelledError:
                pass
            finally:
                try:
                    watcher.transcript_updated -= on_transcript_updated
                except Exception:
                    pass

        return EventSourceResponse(event_generator())
    except ImportError:
        return JSONResponse(status_code=503, content={"error": "SSE not available"})
