"""FastAPI application factory with lifespan, middleware, and auto-router discovery."""

from __future__ import annotations

import asyncio
import importlib
import logging
import os
import pkgutil
import signal
import sys
import sysconfig
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from leash.config import ConfigurationManager
from leash.middleware.security_headers import SecurityHeadersMiddleware

logger = logging.getLogger(__name__)


def _find_data_dir(name: str) -> Path:
    """Locate a shared-data directory (e.g. 'static', 'prompts').

    Search order:
    1. Repo root (development with ``uv run``)
    2. Venv/install prefix via sysconfig (``uvx``, ``pip install``)
    3. ~/.local/share/leash/ (legacy fallback)
    """
    pkg_dir = Path(__file__).resolve().parent
    candidates = [
        pkg_dir.parent.parent / name,
        Path(sysconfig.get_path("data")) / "share" / "leash" / name,
        Path.home() / ".local" / "share" / "leash" / name,
    ]
    for d in candidates:
        if d.is_dir():
            return d
    return candidates[0]


def _find_static_dir() -> Path:
    """Locate the static files directory."""
    return _find_data_dir("static")


def _find_prompts_dir() -> Path:
    """Locate the prompts directory."""
    return _find_data_dir("prompts")


def _discover_routers(app: FastAPI) -> None:
    """Auto-discover and include all routers from leash.routes package."""
    import leash.routes as routes_pkg

    for module_info in pkgutil.iter_modules(routes_pkg.__path__):
        if module_info.name.startswith("_"):
            continue
        try:
            mod = importlib.import_module(f"leash.routes.{module_info.name}")
            if hasattr(mod, "router"):
                app.include_router(mod.router)
                logger.debug("Registered router: leash.routes.%s", module_info.name)
        except Exception:
            logger.exception("Failed to load router module: leash.routes.%s", module_info.name)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan — initialize services on startup, clean up on shutdown."""
    config_path = getattr(app.state, "config_path", None)
    config_mgr = ConfigurationManager(config_path=config_path)
    config = await config_mgr.load()
    app.state.config_manager = config_mgr
    app.state.configuration = config

    prompts_dir = str(_find_prompts_dir())
    app.state.prompts_dir = prompts_dir

    # --- Initialize all services ---
    from leash.services.session_manager import SessionManager
    from leash.services.enforcement_service import EnforcementService
    from leash.services.hook_installer import HookInstaller
    from leash.services.copilot_hook_installer import CopilotHookInstaller
    from leash.services.prompt_template_service import PromptTemplateService
    from leash.services.prompt_builder import PromptBuilder
    from leash.services.profile_service import ProfileService
    from leash.services.adaptive_threshold_service import AdaptiveThresholdService
    from leash.services.insights_engine import InsightsEngine
    from leash.services.audit_report_generator import AuditReportGenerator
    from leash.services.trigger_service import TriggerService
    from leash.services.console_status_service import ConsoleStatusService
    from leash.services.terminal_output_service import TerminalOutputService
    from leash.services.transcript_watcher import TranscriptWatcher
    from leash.services.llm_client_provider import LLMClientProvider
    from leash.services.hook_handler_factory import HookHandlerFactory
    from leash.services.tray.null_services import NullTrayService, NullNotificationService
    from leash.services.tray.pending_decision import PendingDecisionService
    from leash.services.harness.claude import ClaudeHarnessClient
    from leash.services.harness.copilot import CopilotHarnessClient
    from leash.services.harness.registry import HarnessClientRegistry

    # Core services — use actual constructor signatures
    storage_dir = config.session.storage_dir
    session_mgr = SessionManager(storage_dir=storage_dir, max_history_size=config.session.max_history_per_session)
    enforcement_svc = EnforcementService(config_manager=config_mgr)
    service_url = f"http://{config.server.host}:{config.server.port}"
    hook_installer = HookInstaller(config_manager=config_mgr, service_url=service_url)
    copilot_hook_installer = CopilotHookInstaller(service_url=service_url, config_manager=config_mgr)
    prompt_template_svc = PromptTemplateService(prompts_dir=prompts_dir)
    profile_svc = ProfileService(config_manager=config_mgr)
    await profile_svc.initialize()
    adaptive_threshold_svc = AdaptiveThresholdService()
    insights_engine = InsightsEngine(adaptive_service=adaptive_threshold_svc, session_manager=session_mgr)
    audit_report_gen = AuditReportGenerator(session_manager=session_mgr, adaptive_service=adaptive_threshold_svc, profile_service=profile_svc)
    trigger_svc = TriggerService(config_manager=config_mgr)
    console_status_svc = ConsoleStatusService(enforcement_service=enforcement_svc)
    terminal_output_svc = TerminalOutputService()
    llm_client_provider = LLMClientProvider(config_manager=config_mgr, terminal_output=terminal_output_svc)

    # Harness clients
    claude_client = ClaudeHarnessClient()
    copilot_client = CopilotHarnessClient()
    harness_registry = HarnessClientRegistry([claude_client, copilot_client])

    # Transcript watcher
    transcript_watcher = TranscriptWatcher()
    transcript_watcher.set_harness_clients([claude_client, copilot_client])

    # Tray services — use platform-specific services when available
    pending_decision_svc = PendingDecisionService()
    tray_svc = NullTrayService()
    notification_svc = NullNotificationService()
    if config.tray.enabled and sys.platform == "win32":
        try:
            from leash.services.tray.windows import WindowsTrayService, WindowsNotificationService
            tray_svc = WindowsTrayService(dashboard_url=service_url)
            notification_svc = WindowsNotificationService(
                tray_service=tray_svc,
                use_large_popup=config.tray.use_large_popup,
            )
            logger.info("Windows tray service enabled")
        except Exception:
            logger.warning(
                "Failed to initialize Windows tray services (tray.enabled=true), "
                "falling back to null services. Install pystray and Pillow for tray support.",
                exc_info=True,
            )

    # Handler factory
    handler_factory = HookHandlerFactory(
        llm_client_provider=llm_client_provider,
        prompt_template_service=prompt_template_svc,
        session_manager=session_mgr,
    )

    # Store all services on app.state for route access
    app.state.session_manager = session_mgr
    app.state.enforcement_service = enforcement_svc
    app.state.hook_installer = hook_installer
    app.state.copilot_hook_installer = copilot_hook_installer
    app.state.prompt_template_service = prompt_template_svc
    app.state.prompt_builder = PromptBuilder
    app.state.profile_service = profile_svc
    app.state.adaptive_threshold_service = adaptive_threshold_svc
    app.state.insights_engine = insights_engine
    app.state.audit_report_generator = audit_report_gen
    app.state.trigger_service = trigger_svc
    app.state.console_status_service = console_status_svc
    app.state.terminal_output_service = terminal_output_svc
    app.state.llm_client_provider = llm_client_provider
    app.state.harness_client_registry = harness_registry
    app.state.claude_harness_client = claude_client
    app.state.copilot_harness_client = copilot_client
    app.state.transcript_watcher = transcript_watcher
    app.state.tray_service = tray_svc
    app.state.notification_service = notification_svc
    app.state.pending_decision_service = pending_decision_svc
    app.state.handler_factory = handler_factory

    # Start transcript watcher and preload project list in background
    transcript_watcher.start()
    asyncio.create_task(transcript_watcher.preload_projects())

    # Start tray service
    try:
        await tray_svc.start()
    except Exception:
        logger.warning("Failed to start tray service, continuing without tray", exc_info=True)
        tray_svc = NullTrayService()
        notification_svc = NullNotificationService()
        app.state.tray_service = tray_svc
        app.state.notification_service = notification_svc

    # Apply CLI args
    if getattr(app.state, "cli_enforce", False):
        await enforcement_svc.set_mode("enforce")

    # Install a force-exit handler: second Ctrl+C kills immediately.
    # On Windows, uvicorn's signal handling can fail to trigger lifespan
    # shutdown, leaving the process stuck.  This ensures a way out.
    _shutting_down = False

    def _force_exit_handler(sig: int, frame: Any) -> None:
        nonlocal _shutting_down
        if _shutting_down:
            logger.warning("Force exit (second signal received)")
            os._exit(1)
        _shutting_down = True
        logger.info("Shutdown signal received — press Ctrl+C again to force exit")
        raise KeyboardInterrupt

    if sys.platform == "win32":
        signal.signal(signal.SIGINT, _force_exit_handler)
        signal.signal(signal.SIGBREAK, _force_exit_handler)
    else:
        signal.signal(signal.SIGINT, _force_exit_handler)
        signal.signal(signal.SIGTERM, _force_exit_handler)

    logger.info("Leash started - port %d, enforcement: %s",
                config.server.port, enforcement_svc.mode)
    yield

    _shutting_down = True

    # Cleanup — force exit after 5 seconds if graceful shutdown stalls
    logger.info("Leash shutting down")

    async def _graceful_cleanup() -> None:
        # Uninstall hooks so they don't point to a dead server
        try:
            hook_installer.uninstall()
            logger.debug("Claude hooks uninstalled")
        except Exception:
            logger.debug("Error uninstalling Claude hooks during shutdown", exc_info=True)
        try:
            copilot_hook_installer.uninstall_user()
            logger.debug("Copilot hooks uninstalled")
        except Exception:
            logger.debug("Error uninstalling Copilot hooks during shutdown", exc_info=True)

        # Stop tray (unblocks its message loop thread)
        try:
            tray_svc.stop()
        except Exception:
            logger.debug("Error stopping tray service during shutdown", exc_info=True)

        # Dispose LLM clients (kills persistent subprocesses)
        try:
            await llm_client_provider.dispose()
        except Exception:
            logger.debug("Error disposing LLM client provider", exc_info=True)

        # Stop transcript watcher
        try:
            transcript_watcher.stop()
        except Exception:
            logger.debug("Error stopping transcript watcher", exc_info=True)

    try:
        await asyncio.wait_for(_graceful_cleanup(), timeout=5.0)
        logger.info("Graceful shutdown complete")
    except asyncio.TimeoutError:
        logger.error("Graceful shutdown timed out after 5s, forcing exit")
        os._exit(1)


def create_app(config_path: str | None = None) -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="Leash",
        description="Observe and enforce Claude Code permission requests",
        version="0.1.0",
        lifespan=lifespan,
    )

    if config_path:
        app.state.config_path = config_path

    # Security headers (no-cache, CSP, X-Frame-Options, etc.) on all responses
    app.add_middleware(SecurityHeadersMiddleware)

    # Auto-discover and register route modules
    _discover_routers(app)

    # Mount static files (HTML dashboard)
    static_dir = _find_static_dir()
    if static_dir.is_dir():
        app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")

    return app
