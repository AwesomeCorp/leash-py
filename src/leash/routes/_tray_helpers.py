"""Shared tray notification helpers for hook endpoints.

Tray behavior by mode:
- **Enforce**: No tray at all. LLM result is enforced silently.
- **Observe**: Tray only if ``show_in_observe`` is True (default False).
  Only fires when LLM analysis is enabled. Informational only.
- **Approve-only**: Can only approve safe requests. Unsafe requests are
  silently ignored (empty response) so the CLI asks the user normally.
  Tray shows informational alerts if enabled but never denies.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from fastapi.responses import JSONResponse

from leash.models.tray_models import NotificationInfo, NotificationLevel, TrayDecision

if TYPE_CHECKING:
    from leash.models.configuration import TrayConfig
    from leash.services.tray.base import NotificationService
    from leash.services.tray.pending_decision import PendingDecisionService

# Empty JSON = no opinion; the AI assistant asks the user as normal
_NO_OPINION = JSONResponse(content={})

logger = logging.getLogger(__name__)


def _build_info(
    tool_name: str | None,
    output: Any,
    cwd: str | None,
    provider: str,
    timeout: int | None,
    level: NotificationLevel,
    sound: bool = False,
) -> NotificationInfo:
    """Build a rich NotificationInfo from an LLM output."""
    score = getattr(output, "safety_score", None)
    threshold = getattr(output, "threshold", None)
    reasoning = getattr(output, "reasoning", None)
    category = getattr(output, "category", None)

    # Build tool input summary
    tool_input_summary: str | None = None
    hook_input = getattr(output, "_hook_input", None)
    if hook_input is not None:
        ti = getattr(hook_input, "tool_input", None)
        if isinstance(ti, dict):
            cmd = ti.get("command")
            fp = ti.get("file_path")
            if cmd:
                tool_input_summary = cmd[:200]
            elif fp:
                tool_input_summary = fp

    # Suggested action based on score
    suggested_action = None
    if score is not None and threshold is not None:
        if score >= threshold:
            suggested_action = "approve"
        elif score <= 0:
            suggested_action = "deny"
        else:
            suggested_action = "review"

    title = f"Leash: {tool_name or 'unknown'}"
    body = reasoning or f"Score: {score}"

    return NotificationInfo(
        title=title,
        body=body,
        tool_name=tool_name,
        safety_score=score,
        threshold=threshold,
        reasoning=reasoning,
        suggested_action=suggested_action,
        category=category,
        provider=provider,
        cwd=cwd,
        tool_input_summary=tool_input_summary,
        sound=sound,
        timeout_seconds=timeout,
        level=level,
    )


async def make_tray_decision(
    mode: str,
    output: Any,
    harness_client: Any,
    event: str,
    tool_name: str,
    notification_svc: NotificationService | None,
    pending_decision_svc: PendingDecisionService | None,
    tray_config: TrayConfig | None,
    provider: str,
    cwd: str | None = None,
) -> JSONResponse:
    """Apply enforcement mode decision logic with tray integration."""

    score = getattr(output, "safety_score", None) or 0
    threshold = getattr(output, "threshold", None) or 85
    auto_approved = getattr(output, "auto_approve", False)
    timeout = getattr(tray_config, "interactive_timeout_seconds", 10) if tray_config else 10
    sound = getattr(tray_config, "sound", False) if tray_config else False

    # ── Enforce mode: no tray, just enforce ──
    if mode == "enforce":
        if auto_approved and harness_client is not None:
            return JSONResponse(content=harness_client.format_response(event, output))
        # Deny
        if harness_client is not None:
            return JSONResponse(content=harness_client.format_response(event, output))
        return _NO_OPINION

    # ── Determine if tray is enabled for this mode ──
    tray_active = False
    if tray_config and getattr(tray_config, "enabled", False):
        if mode == "observe" and getattr(tray_config, "show_in_observe", False):
            tray_active = True
        elif mode == "approve-only" and getattr(tray_config, "show_in_approve_only", True):
            tray_active = True

    # ── Approved (score >= threshold): silent ──
    if auto_approved:
        if harness_client is not None:
            return JSONResponse(content=harness_client.format_response(event, output))
        return _NO_OPINION

    # ── Approve-only: never deny, return no response for unsafe requests ──
    if mode == "approve-only":
        # Show informational tray alert so the user knows, but never deny
        if tray_active and notification_svc is not None:
            level = NotificationLevel.DANGER if score <= 0 else NotificationLevel.WARNING
            info = _build_info(tool_name, output, cwd, provider, None, level, sound)
            info.title = f"Leash: {tool_name or 'unknown'} (score {score})"
            try:
                await notification_svc.show_alert(info)
            except Exception:
                logger.debug("Failed to show alert for %s", tool_name, exc_info=True)
        return _NO_OPINION

    # ── Not approved: decide based on score (observe / enforce fallthrough) ──

    if score <= 0:
        # Clearly dangerous: informational alert (no buttons)
        if tray_active and notification_svc is not None:
            info = _build_info(tool_name, output, cwd, provider, None, NotificationLevel.DANGER, sound)
            info.title = f"Leash: {tool_name or 'unknown'} DENIED"
            try:
                await notification_svc.show_alert(info)
            except Exception:
                logger.debug("Failed to show denial alert for %s", tool_name, exc_info=True)

        # Observe: do nothing
        return _NO_OPINION

    # Score > 0 and < threshold: uncertain — interactive toast
    if tray_active and notification_svc is not None and pending_decision_svc is not None:
        info = _build_info(tool_name, output, cwd, provider, timeout, NotificationLevel.WARNING, sound)
        info.title = f"Leash: {tool_name or 'unknown'} needs review"

        try:
            decision_id, future = pending_decision_svc.create_pending(info, timeout)
        except Exception:
            logger.warning("Failed to create pending decision for %s", tool_name, exc_info=True)
            return _NO_OPINION

        # Try interactive toast — shows one toast with Approve/Deny/Ignore buttons
        interactive_handled = False
        if getattr(notification_svc, "supports_interactive", False):
            try:
                result = await notification_svc.show_interactive(info, timeout)
                interactive_handled = True
                if result is not None:
                    pending_decision_svc.try_resolve(decision_id, result)
                else:
                    pending_decision_svc.cancel(decision_id)

                result = _apply_tray_result(result, output, harness_client, event, mode)
                if result is not None:
                    return result
            except Exception:
                logger.debug("Interactive toast failed for %s", tool_name, exc_info=True)

        # Fall back only if interactive toast was not shown (e.g. not supported)
        if not interactive_handled:
            try:
                await notification_svc.show_alert(info)
            except Exception:
                pass

            try:
                result = await future
                applied = _apply_tray_result(result, output, harness_client, event, mode)
                if applied is not None:
                    return applied
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pending_decision_svc.cancel(decision_id)
            except Exception:
                pending_decision_svc.cancel(decision_id)

    # No tray or tray not available: fall through, let Claude ask the user
    logger.debug("%s mode - %s (score=%s) falling through to user", mode, tool_name, score)
    return _NO_OPINION


def _apply_tray_result(
    result: TrayDecision | None,
    output: Any,
    harness_client: Any,
    event: str,
    mode: str,
) -> JSONResponse | None:
    """Convert a tray decision into a response. Returns None if no action taken."""
    if result == TrayDecision.APPROVE and harness_client is not None:
        output.auto_approve = True
        output.tray_decision = "tray-approved"
        return JSONResponse(content=harness_client.format_response(event, output))

    if result == TrayDecision.DENY and harness_client is not None:
        output.tray_decision = "tray-denied"
        return JSONResponse(content=harness_client.format_response(event, output))

    if result == TrayDecision.IGNORE:
        # Ignore = ask the user directly (not auto-allow, not deny)
        output.tray_decision = "tray-ignored"
        if harness_client is not None:
            return JSONResponse(content=harness_client.format_response(event, output))
        return _NO_OPINION

    # None (timeout/dismissed) — ask the user directly
    output.tray_decision = "tray-timeout"
    if harness_client is not None:
        return JSONResponse(content=harness_client.format_response(event, output))
    return _NO_OPINION
