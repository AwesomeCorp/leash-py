"""Windows tray and notification services using pystray (optional dependency).

If pystray / Pillow are not installed the module still imports cleanly;
``WindowsTrayService.is_available`` will simply be ``False``.
"""

from __future__ import annotations

import asyncio
import logging
import sys
import threading
from typing import Any

from leash.models.tray_models import NotificationInfo, TrayDecision

logger = logging.getLogger(__name__)

try:
    import pystray
    from PIL import Image, ImageDraw

    HAS_PYSTRAY = True
except ImportError:
    HAS_PYSTRAY = False


def _create_default_icon() -> Any:
    """Create a small blue circle icon with a white checkmark."""
    if not HAS_PYSTRAY:
        return None
    img = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse([1, 1, 14, 14], fill=(59, 130, 246, 255))
    draw.line([(4, 8), (7, 11), (12, 5)], fill="white", width=2)
    return img


class WindowsTrayService:
    """Windows system tray icon using pystray on a background thread.

    Requires ``pystray`` and ``Pillow`` optional dependencies.
    """

    def __init__(self, dashboard_url: str = "http://localhost:5050") -> None:
        self._dashboard_url = dashboard_url
        self._icon: Any | None = None
        self._thread: threading.Thread | None = None
        self._started = False
        self._disposed = False

    @property
    def is_available(self) -> bool:
        return HAS_PYSTRAY and self._started and not self._disposed and self._icon is not None

    async def start(self) -> None:
        if not HAS_PYSTRAY or self._started or self._disposed:
            return
        if sys.platform != "win32":
            return

        loop = asyncio.get_running_loop()
        ready = asyncio.Event()

        def _run_tray() -> None:
            try:
                image = _create_default_icon()
                menu = pystray.Menu(
                    pystray.MenuItem("Open Dashboard", self._open_dashboard),
                    pystray.Menu.SEPARATOR,
                    pystray.MenuItem("Exit", self._exit_tray),
                )
                self._icon = pystray.Icon("leash", image, "Leash", menu)
                self._started = True
                loop.call_soon_threadsafe(ready.set)
                self._icon.run()
            except Exception:
                logger.debug("Failed to start Windows tray icon", exc_info=True)
                loop.call_soon_threadsafe(ready.set)

        self._thread = threading.Thread(target=_run_tray, daemon=True, name="TrayIconThread")
        self._thread.start()
        await ready.wait()

    def update_status(self, status: str) -> None:
        if not self.is_available:
            return
        try:
            text = f"Leash - {status}"
            self._icon.title = text[:63] if len(text) > 63 else text
        except Exception:
            pass

    def _open_dashboard(self) -> None:
        import webbrowser

        try:
            webbrowser.open(self._dashboard_url)
        except Exception:
            pass

    def _exit_tray(self) -> None:
        if self._icon:
            try:
                self._icon.stop()
            except Exception:
                pass

    def stop(self) -> None:
        """Stop the tray icon and clean up."""
        if self._disposed:
            return
        self._disposed = True
        self._exit_tray()


class WindowsNotificationService:
    """Windows notification service using pystray balloon/notify.

    For interactive decisions, delegates to the ``PendingDecisionService``
    (web dashboard fallback) since pystray notifications are passive.
    """

    def __init__(self, tray_service: WindowsTrayService) -> None:
        self._tray = tray_service

    @property
    def supports_interactive(self) -> bool:
        # pystray's notify is passive only; interactive decisions use the web dashboard
        return False

    async def show_alert(self, info: NotificationInfo) -> None:
        if not self._tray.is_available or self._tray._icon is None:
            return
        try:
            self._tray._icon.notify(
                title=info.title[:63],
                message=info.body[:255],
            )
        except Exception:
            logger.debug("Failed to show Windows notification", exc_info=True)

    async def show_interactive(self, info: NotificationInfo, timeout: float) -> TrayDecision | None:
        # Passive-only on Windows via pystray; fall through to pending decision / dashboard
        return None
