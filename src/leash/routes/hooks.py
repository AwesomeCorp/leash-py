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
            pass

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
            pass

    return JSONResponse(
        content={
            "installed": installed,
            "enforced": enforced,
            "enforcementMode": enforcement_mode,
            "copilot": {"userInstalled": copilot_user_installed},
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
        return JSONResponse(content={"installed": False, "message": "Hooks uninstalled successfully"})
    except Exception as exc:
        logger.error("Failed to uninstall hooks: %s", exc)
        return JSONResponse(status_code=500, content={"error": f"Failed to uninstall hooks: {exc}"})


@router.post("/api/hooks/copilot/install")
async def install_copilot_hooks(
    request: Request,
    level: str = Query(default="user", description="Installation level: user or repo"),
    repo_path: str | None = Query(default=None, alias="repoPath", description="Repository path for repo-level install"),
) -> JSONResponse:
    """Install Copilot hooks at user or repo level."""
    copilot_installer = _get_copilot_hook_installer(request)
    if copilot_installer is None:
        return JSONResponse(status_code=503, content={"error": "Copilot hook installer not available"})

    try:
        if level.lower() == "repo":
            if not repo_path or not repo_path.strip():
                return JSONResponse(
                    status_code=400,
                    content={"error": "repoPath query parameter is required for repo-level installation"},
                )
            copilot_installer.install_repo(repo_path)
            return JSONResponse(
                content={"installed": True, "level": "repo", "message": "Copilot hooks installed at repo level"}
            )
        else:
            copilot_installer.install_user()
            return JSONResponse(
                content={"installed": True, "level": "user", "message": "Copilot hooks installed at user level"}
            )
    except Exception as exc:
        logger.error("Failed to install Copilot hooks: %s", exc)
        return JSONResponse(status_code=500, content={"error": f"Failed to install Copilot hooks: {exc}"})


@router.post("/api/hooks/copilot/uninstall")
async def uninstall_copilot_hooks(
    request: Request,
    level: str = Query(default="user", description="Uninstall level: user or repo"),
    repo_path: str | None = Query(
        default=None, alias="repoPath", description="Repository path for repo-level uninstall"
    ),
) -> JSONResponse:
    """Uninstall Copilot hooks at user or repo level."""
    copilot_installer = _get_copilot_hook_installer(request)
    if copilot_installer is None:
        return JSONResponse(status_code=503, content={"error": "Copilot hook installer not available"})

    try:
        if level.lower() == "repo":
            if not repo_path or not repo_path.strip():
                return JSONResponse(
                    status_code=400,
                    content={"error": "repoPath query parameter is required for repo-level uninstall"},
                )
            copilot_installer.uninstall_repo(repo_path)
            return JSONResponse(
                content={"installed": False, "level": "repo", "message": "Copilot hooks uninstalled from repo level"}
            )
        else:
            copilot_installer.uninstall_user()
            return JSONResponse(
                content={"installed": False, "level": "user", "message": "Copilot hooks uninstalled from user level"}
            )
    except Exception as exc:
        logger.error("Failed to uninstall Copilot hooks: %s", exc)
        return JSONResponse(status_code=500, content={"error": f"Failed to uninstall Copilot hooks: {exc}"})
