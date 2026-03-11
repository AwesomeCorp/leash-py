"""Hook management endpoints — install, uninstall, enforce, status."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)
router = APIRouter()

VALID_ENFORCEMENT_MODES = {"observe", "approve-only", "enforce"}


def _get_hook_installer(request: Request) -> Any:
    return getattr(request.app.state, "hook_installer", None)


def _get_copilot_hook_installer(request: Request) -> Any:
    return getattr(request.app.state, "copilot_hook_installer", None)


def _get_enforcement_service(request: Request) -> Any:
    return getattr(request.app.state, "enforcement_service", None)


@router.get("/api/hooks/status")
async def get_status(request: Request) -> JSONResponse:
    """Return hook installation and enforcement status."""
    hook_installer = _get_hook_installer(request)
    copilot_installer = _get_copilot_hook_installer(request)
    enforcement_svc = _get_enforcement_service(request)

    installed = False
    if hook_installer is not None:
        try:
            installed = hook_installer.is_installed()
        except Exception:
            logger.warning("Failed to check hook installation status", exc_info=True)

    enforced = False
    enforcement_mode = "observe"
    if enforcement_svc is not None:
        enforced = getattr(enforcement_svc, "is_enforced", False)
        enforcement_mode = getattr(enforcement_svc, "mode", "observe")

    copilot_user_installed = False
    if copilot_installer is not None:
        try:
            copilot_user_installed = copilot_installer.is_user_installed()
        except Exception:
            logger.warning("Failed to check copilot installation status", exc_info=True)

    hooks_user_uninstalled = False
    copilot_hooks_user_uninstalled = False
    config_mgr = getattr(request.app.state, "config_manager", None)
    if config_mgr is not None:
        try:
            app_config = config_mgr.get_configuration()
            hooks_user_uninstalled = app_config.hooks_user_uninstalled
            copilot_hooks_user_uninstalled = app_config.copilot_hooks_user_uninstalled
        except Exception:
            logger.warning("Failed to read config for hook status", exc_info=True)

    return JSONResponse(
        content={
            "installed": installed,
            "enforced": enforced,
            "enforcementMode": enforcement_mode,
            "hooksUserUninstalled": hooks_user_uninstalled,
            "copilot": {
                "userInstalled": copilot_user_installed,
                "hooksUserUninstalled": copilot_hooks_user_uninstalled,
            },
        }
    )


@router.post("/api/hooks/enforce")
async def toggle_enforcement(
    request: Request,
    mode: str | None = Query(default=None, description="Enforcement mode to set"),
) -> JSONResponse:
    """Toggle or set enforcement mode."""
    enforcement_svc = _get_enforcement_service(request)
    if enforcement_svc is None:
        return JSONResponse(status_code=503, content={"error": "Enforcement service not available"})

    if mode is not None and mode.strip():
        if mode not in VALID_ENFORCEMENT_MODES:
            return JSONResponse(
                status_code=400,
                content={"error": f"Invalid mode: {mode}. Valid: {', '.join(sorted(VALID_ENFORCEMENT_MODES))}"},
            )
        await enforcement_svc.set_mode(mode)
    else:
        await enforcement_svc.cycle_mode()

    current_mode = getattr(enforcement_svc, "mode", "observe")
    logger.info("Enforcement mode set to %s", current_mode)

    messages = {
        "observe": "Observe-only mode - hooks log but do not decide",
        "approve-only": "Approve-only mode - safe requests auto-approved, uncertain ones fall through to user",
        "enforce": "Full enforcement - hooks return approve/deny decisions",
    }
    message = messages.get(current_mode, f"Mode: {current_mode}")

    return JSONResponse(
        content={
            "enforced": getattr(enforcement_svc, "is_enforced", False),
            "enforcementMode": current_mode,
            "message": message,
        }
    )


@router.post("/api/hooks/install")
async def install_hooks(request: Request) -> JSONResponse:
    """Install Claude hooks to settings.json."""
    hook_installer = _get_hook_installer(request)
    if hook_installer is None:
        return JSONResponse(status_code=503, content={"error": "Hook installer not available"})

    try:
        hook_installer.install()

        # Clear the user-uninstalled flag so hooks auto-install on next startup
        config_mgr = getattr(request.app.state, "config_manager", None)
        if config_mgr is not None:
            config = config_mgr.get_configuration()
            if config.hooks_user_uninstalled:
                config.hooks_user_uninstalled = False
                await config_mgr.update(config)

        return JSONResponse(content={"installed": True, "message": "Hooks installed successfully"})
    except Exception as exc:
        logger.error("Failed to install hooks: %s", exc)
        return JSONResponse(status_code=500, content={"error": f"Failed to install hooks: {exc}"})


@router.post("/api/hooks/uninstall")
async def uninstall_hooks(request: Request) -> JSONResponse:
    """Remove Claude hooks from settings.json."""
    hook_installer = _get_hook_installer(request)
    if hook_installer is None:
        return JSONResponse(status_code=503, content={"error": "Hook installer not available"})

    try:
        hook_installer.uninstall()

        # Remember the user's decision so hooks stay uninstalled on next startup
        config_mgr = getattr(request.app.state, "config_manager", None)
        if config_mgr is not None:
            config = config_mgr.get_configuration()
            config.hooks_user_uninstalled = True
            await config_mgr.update(config)

        return JSONResponse(content={"installed": False, "message": "Hooks uninstalled successfully"})
    except Exception as exc:
        logger.error("Failed to uninstall hooks: %s", exc)
        return JSONResponse(status_code=500, content={"error": f"Failed to uninstall hooks: {exc}"})


@router.get("/api/hooks/session-start/status")
async def session_start_status(request: Request) -> JSONResponse:
    """Check if SessionStart hooks are installed."""
    hook_installer = _get_hook_installer(request)
    if hook_installer is None:
        return JSONResponse(content={"installed": False})
    try:
        installed = hook_installer.is_session_start_installed()
        return JSONResponse(content={"installed": installed})
    except Exception:
        logger.warning("Failed to check SessionStart status", exc_info=True)
        return JSONResponse(content={"installed": False})


@router.post("/api/hooks/session-start/install")
async def install_session_start(request: Request) -> JSONResponse:
    """Install only the SessionStart hook."""
    hook_installer = _get_hook_installer(request)
    if hook_installer is None:
        return JSONResponse(status_code=503, content={"error": "Hook installer not available"})
    try:
        hook_installer.install_session_start_only()
        return JSONResponse(content={"installed": True, "message": "SessionStart hook installed"})
    except Exception as exc:
        logger.error("Failed to install SessionStart hook: %s", exc)
        return JSONResponse(status_code=500, content={"error": f"Failed: {exc}"})


@router.post("/api/hooks/session-start/uninstall")
async def uninstall_session_start(request: Request) -> JSONResponse:
    """Remove only the SessionStart hook."""
    hook_installer = _get_hook_installer(request)
    if hook_installer is None:
        return JSONResponse(status_code=503, content={"error": "Hook installer not available"})
    try:
        hook_installer.uninstall_session_start_only()
        return JSONResponse(content={"installed": False, "message": "SessionStart hook removed"})
    except Exception as exc:
        logger.error("Failed to uninstall SessionStart hook: %s", exc)
        return JSONResponse(status_code=500, content={"error": f"Failed: {exc}"})


@router.post("/api/hooks/copilot/install")
async def install_copilot_hooks(request: Request) -> JSONResponse:
    """Install Copilot hooks at user level."""
    copilot_installer = _get_copilot_hook_installer(request)
    if copilot_installer is None:
        return JSONResponse(status_code=503, content={"error": "Copilot hook installer not available"})

    try:
        copilot_installer.install_user()

        # Clear the user-uninstalled flag
        config_mgr = getattr(request.app.state, "config_manager", None)
        if config_mgr is not None:
            config = config_mgr.get_configuration()
            if config.copilot_hooks_user_uninstalled:
                config.copilot_hooks_user_uninstalled = False
                await config_mgr.update(config)

        return JSONResponse(
            content={"installed": True, "message": "Copilot hooks installed successfully"}
        )
    except Exception as exc:
        logger.error("Failed to install Copilot hooks: %s", exc)
        return JSONResponse(status_code=500, content={"error": f"Failed to install Copilot hooks: {exc}"})


@router.post("/api/hooks/copilot/uninstall")
async def uninstall_copilot_hooks(request: Request) -> JSONResponse:
    """Uninstall Copilot hooks from user level."""
    copilot_installer = _get_copilot_hook_installer(request)
    if copilot_installer is None:
        return JSONResponse(status_code=503, content={"error": "Copilot hook installer not available"})

    try:
        copilot_installer.uninstall_user()

        # Remember the user's decision
        config_mgr = getattr(request.app.state, "config_manager", None)
        if config_mgr is not None:
            config = config_mgr.get_configuration()
            config.copilot_hooks_user_uninstalled = True
            await config_mgr.update(config)

        return JSONResponse(
            content={"installed": False, "message": "Copilot hooks uninstalled successfully"}
        )
    except Exception as exc:
        logger.error("Failed to uninstall Copilot hooks: %s", exc)
        return JSONResponse(status_code=500, content={"error": f"Failed to uninstall Copilot hooks: {exc}"})
