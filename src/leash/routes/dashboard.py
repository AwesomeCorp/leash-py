"""Dashboard endpoints — stats, sessions, activity, trends, health."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)
router = APIRouter()


def _get_session_manager(request: Request) -> Any:
    return getattr(request.app.state, "session_manager", None)


@router.get("/api/dashboard/stats")
async def get_stats(request: Request) -> JSONResponse:
    """Return dashboard statistics: approvals, denials, active sessions, average score."""
    session_manager = _get_session_manager(request)
    if session_manager is None:
        return JSONResponse(
            content={
                "autoApprovedToday": 0,
                "deniedToday": 0,
                "activeSessions": 0,
                "avgSafetyScore": 0,
                "totalEventsToday": 0,
            }
        )

    try:
        sessions = await session_manager.get_all_sessions()
        today = datetime.now(timezone.utc).date()

        all_events = []
        active_count = 0
        one_hour_ago = datetime.now(timezone.utc).timestamp() - 3600

        for s in sessions:
            history = getattr(s, "conversation_history", [])
            all_events.extend(history)
            last_activity = getattr(s, "last_activity", None)
            if last_activity is not None and last_activity.timestamp() > one_hour_ago:
                active_count += 1

        today_events = [e for e in all_events if getattr(e, "timestamp", datetime.min).date() == today]
        auto_approved = sum(1 for e in today_events if getattr(e, "decision", "") == "auto-approved")
        denied = sum(1 for e in today_events if getattr(e, "decision", "") == "denied")

        scored = [e for e in today_events if getattr(e, "safety_score", None) is not None]
        avg_score = round(sum(e.safety_score for e in scored) / len(scored)) if scored else 0

        return JSONResponse(
            content={
                "autoApprovedToday": auto_approved,
                "deniedToday": denied,
                "activeSessions": active_count,
                "avgSafetyScore": avg_score,
                "totalEventsToday": len(today_events),
            }
        )
    except Exception as exc:
        logger.error("Failed to retrieve dashboard stats: %s", exc)
        return JSONResponse(status_code=500, content={"error": "Failed to load dashboard statistics"})


@router.get("/api/dashboard/sessions")
async def get_sessions(request: Request) -> JSONResponse:
    """Return session list with event counts."""
    session_manager = _get_session_manager(request)
    if session_manager is None:
        return JSONResponse(content=[])

    try:
        sessions = await session_manager.get_all_sessions()

        result = []
        for s in sessions:
            history = getattr(s, "conversation_history", [])
            approved_count = sum(1 for e in history if getattr(e, "decision", "") == "auto-approved")
            denied_count = sum(1 for e in history if getattr(e, "decision", "") == "denied")
            last_tool = getattr(history[-1], "tool_name", None) if history else None

            result.append(
                {
                    "sessionId": getattr(s, "session_id", ""),
                    "startTime": getattr(s, "start_time", datetime.now(timezone.utc)).isoformat(),
                    "lastActivity": getattr(s, "last_activity", datetime.now(timezone.utc)).isoformat(),
                    "workingDirectory": getattr(s, "working_directory", None),
                    "eventCount": len(history),
                    "approvedCount": approved_count,
                    "deniedCount": denied_count,
                    "lastTool": last_tool,
                }
            )

        # Sort by last activity descending
        result.sort(key=lambda x: x["lastActivity"], reverse=True)
        return JSONResponse(content=result)
    except Exception as exc:
        logger.error("Failed to retrieve sessions: %s", exc)
        return JSONResponse(status_code=500, content={"error": "Failed to load sessions"})


@router.get("/api/dashboard/activity")
async def get_recent_activity(
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
) -> JSONResponse:
    """Return recent events across all sessions."""
    session_manager = _get_session_manager(request)
    if session_manager is None:
        return JSONResponse(content=[])

    try:
        sessions = await session_manager.get_all_sessions()

        events = []
        for s in sessions:
            session_id = getattr(s, "session_id", "")
            for e in getattr(s, "conversation_history", []):
                events.append(
                    {
                        "timestamp": getattr(e, "timestamp", datetime.now(timezone.utc)).isoformat(),
                        "type": getattr(e, "type", ""),
                        "toolName": getattr(e, "tool_name", None),
                        "toolInput": getattr(e, "tool_input", None),
                        "decision": getattr(e, "decision", None),
                        "safetyScore": getattr(e, "safety_score", None),
                        "reasoning": getattr(e, "reasoning", None),
                        "category": getattr(e, "category", None),
                        "content": getattr(e, "content", None),
                        "handlerName": getattr(e, "handler_name", None),
                        "promptTemplate": getattr(e, "prompt_template", None),
                        "threshold": getattr(e, "threshold", None),
                        "sessionId": session_id,
                    }
                )

        # Sort by timestamp descending and take limit
        events.sort(key=lambda x: x["timestamp"], reverse=True)
        return JSONResponse(content=events[:limit])
    except Exception as exc:
        logger.error("Failed to retrieve recent activity: %s", exc)
        return JSONResponse(status_code=500, content={"error": "Failed to load activity feed"})


@router.get("/api/dashboard/trends")
async def get_trends(
    request: Request,
    days: int = Query(default=7, ge=1, le=30),
) -> JSONResponse:
    """Return per-day approved/denied/total trends."""
    session_manager = _get_session_manager(request)
    if session_manager is None:
        return JSONResponse(content=[])

    try:
        sessions = await session_manager.get_all_sessions()
        all_events = []
        for s in sessions:
            all_events.extend(getattr(s, "conversation_history", []))

        from datetime import timedelta

        today = datetime.now(timezone.utc).date()
        trends = []
        for i in range(days - 1, -1, -1):
            day = today - timedelta(days=i)
            day_events = [e for e in all_events if getattr(e, "timestamp", datetime.min).date() == day]
            trends.append(
                {
                    "date": day.isoformat(),
                    "approved": sum(1 for e in day_events if getattr(e, "decision", "") == "auto-approved"),
                    "denied": sum(1 for e in day_events if getattr(e, "decision", "") == "denied"),
                    "total": len(day_events),
                }
            )

        return JSONResponse(content=trends)
    except Exception as exc:
        logger.error("Failed to retrieve trends data: %s", exc)
        return JSONResponse(status_code=500, content={"error": "Failed to load trends"})


@router.get("/api/dashboard/health")
async def get_dashboard_health() -> JSONResponse:
    """Simple health check for the dashboard."""
    return JSONResponse(
        content={
            "status": "healthy",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "uptime": int(time.monotonic() * 1000),
        }
    )
