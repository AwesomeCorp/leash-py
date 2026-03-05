"""Configuration CRUD endpoints — GET/PUT /api/config."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from leash.exceptions import ConfigurationException

logger = logging.getLogger(__name__)
router = APIRouter()


def _get_config_manager(request: Request) -> Any:
    return getattr(request.app.state, "config_manager", None)


def _get_hook_installer(request: Request) -> Any:
    return getattr(request.app.state, "hook_installer", None)


def _get_copilot_hook_installer(request: Request) -> Any:
    return getattr(request.app.state, "copilot_hook_installer", None)


@router.get("/api/config")
async def get_config(request: Request) -> JSONResponse:
    """Return the current configuration."""
    config_manager = _get_config_manager(request)
    if config_manager is None:
        return JSONResponse(status_code=503, content={"error": "Configuration manager not available"})

    try:
        config = await config_manager.load()
        return JSONResponse(content=config.model_dump(by_alias=True))
    except Exception as exc:
        logger.error("Failed to load configuration: %s", exc)
        return JSONResponse(status_code=500, content={"error": "Failed to load configuration"})


@router.put("/api/config")
async def update_config(request: Request) -> JSONResponse:
    """Update the configuration. Auto-reinstalls hooks after save."""
    config_manager = _get_config_manager(request)
    if config_manager is None:
        return JSONResponse(status_code=503, content={"error": "Configuration manager not available"})

    try:
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"error": "Invalid JSON body"})

    if not body:
        return JSONResponse(status_code=400, content={"error": "Configuration body is required"})

    try:
        from leash.models.configuration import Configuration

        config = Configuration.model_validate(body)
        await config_manager.update(config)
        logger.info("Configuration updated via API")

        # Auto-reinstall hooks after config change (both Claude and Copilot)
        hook_installer = _get_hook_installer(request)
        if hook_installer is not None:
            try:
                hook_installer.install()
            except Exception as hook_exc:
                logger.warning("Failed to reinstall Claude hooks after config update: %s", hook_exc)

        copilot_installer = _get_copilot_hook_installer(request)
        if copilot_installer is not None:
            try:
                copilot_installer.install_user()
            except Exception as hook_exc:
                logger.warning("Failed to reinstall Copilot hooks after config update: %s", hook_exc)

        return JSONResponse(content={"message": "Configuration updated successfully"})
    except ConfigurationException as exc:
        logger.error("Failed to save configuration: %s", exc)
        return JSONResponse(status_code=500, content={"error": str(exc)})
    except Exception as exc:
        logger.error("Unexpected error updating configuration: %s", exc)
        return JSONResponse(status_code=500, content={"error": "Failed to update configuration"})


@router.get("/api/config/analyze-in-observe")
async def get_analyze_in_observe(request: Request) -> JSONResponse:
    """Return whether LLM analysis is enabled in observe mode."""
    config_manager = _get_config_manager(request)
    if config_manager is None:
        return JSONResponse(status_code=503, content={"error": "Configuration manager not available"})
    config = config_manager.get_configuration()
    return JSONResponse(content={"analyzeInObserveMode": config.analyze_in_observe_mode})


@router.put("/api/config/analyze-in-observe")
async def set_analyze_in_observe(request: Request) -> JSONResponse:
    """Toggle LLM analysis in observe mode."""
    config_manager = _get_config_manager(request)
    if config_manager is None:
        return JSONResponse(status_code=503, content={"error": "Configuration manager not available"})

    try:
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"error": "Invalid JSON body"})

    enabled = body.get("analyzeInObserveMode")
    if not isinstance(enabled, bool):
        return JSONResponse(status_code=400, content={"error": "analyzeInObserveMode must be a boolean"})

    try:
        config = config_manager.get_configuration()
        config.analyze_in_observe_mode = enabled
        await config_manager.update(config)
        return JSONResponse(content={"analyzeInObserveMode": enabled})
    except Exception as exc:
        logger.error("Failed to update analyze_in_observe_mode: %s", exc)
        return JSONResponse(status_code=500, content={"error": "Failed to update setting"})


@router.get("/api/config/handlers/{hook_event_name}")
async def get_handlers(request: Request, hook_event_name: str) -> JSONResponse:
    """Return handlers for a specific hook event."""
    if not hook_event_name or not hook_event_name.strip():
        return JSONResponse(status_code=400, content={"error": "Hook event name is required"})

    config_manager = _get_config_manager(request)
    if config_manager is None:
        return JSONResponse(status_code=503, content={"error": "Configuration manager not available"})

    handlers = config_manager.get_handlers_for_hook(hook_event_name)
    return JSONResponse(content=[h.model_dump(by_alias=True) for h in handlers])
