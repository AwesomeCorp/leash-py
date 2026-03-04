"""Install/uninstall curl hooks in ~/.claude/settings.json."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from leash.config import ConfigurationManager

logger = logging.getLogger(__name__)

# Marker used to identify our hooks vs user's own hooks
HOOK_MARKER = "# leash"


class HookInstaller:
    """Manages Claude hook installation in ~/.claude/settings.json."""

    def __init__(
        self,
        config_manager: ConfigurationManager,
        service_url: str = "http://localhost:5050",
    ) -> None:
        self._config_manager = config_manager
        self._service_url = service_url
        self._settings_path = Path.home() / ".claude" / "settings.json"

    def is_installed(self) -> bool:
        """Check if any leash hooks exist in Claude settings."""
        try:
            if not self._settings_path.exists():
                return False

            doc = self._load_settings()
            hooks = doc.get("hooks")
            if not hooks:
                return False

            return self._contains_our_hooks(hooks)
        except Exception as e:
            logger.warning("Failed to check hook installation status: %s", e)
            return False

    def install(self) -> None:
        """Install hooks derived from the app's hookHandlers config.

        Always removes our old hooks first to prevent duplication.
        User's own hooks (without our marker) are preserved.
        """
        app_config = self._config_manager.get_configuration()
        logger.debug("Syncing Claude hooks from app config (%d event types)", len(app_config.hook_handlers))

        doc = self._load_or_create_settings()
        hooks: dict[str, Any] = doc.get("hooks", {})

        # Step 1: Remove ALL our old hooks (by marker) to prevent duplication
        self._remove_our_hooks(hooks)

        # Step 2: Add hooks derived from the app's hookHandlers config
        for event_name, event_config in app_config.hook_handlers.items():
            if not event_config.enabled or not event_config.handlers:
                continue

            # Get or create the array for this event type
            arr: list[Any] = hooks.get(event_name, [])

            for handler in event_config.handlers:
                matcher = handler.matcher
                command = (
                    f'curl -sS -X POST "{self._service_url}/api/hooks/claude?event={event_name}" '
                    f'-H "Content-Type: application/json" -d @- {HOOK_MARKER}'
                )

                hook_obj: dict[str, Any] = {
                    "hooks": [{"type": "command", "command": command}],
                }

                if matcher and matcher != "*":
                    hook_obj["matcher"] = matcher

                arr.append(hook_obj)

            hooks[event_name] = arr

        doc["hooks"] = hooks
        self._cleanup_empty_hooks(doc)

        self._write_settings(doc)
        logger.debug("Claude hooks synced successfully")

    def uninstall(self) -> None:
        """Remove hooks marked with the leash marker."""
        logger.debug("Uninstalling Claude hooks")

        if not self._settings_path.exists():
            logger.debug("Settings file not found, nothing to uninstall")
            return

        try:
            doc = self._load_settings()
            hooks = doc.get("hooks")
            if not hooks:
                return

            self._remove_our_hooks(hooks)
            self._cleanup_empty_hooks(doc)

            self._write_settings(doc)
            logger.debug("Claude hooks uninstalled successfully")
        except Exception as e:
            logger.error("Failed to uninstall hooks from %s: %s", self._settings_path, e)
            raise

    def _load_settings(self) -> dict[str, Any]:
        """Load settings.json from disk."""
        raw = self._settings_path.read_text(encoding="utf-8")
        return json.loads(raw)  # type: ignore[no-any-return]

    def _load_or_create_settings(self) -> dict[str, Any]:
        """Load settings.json or return an empty dict."""
        if self._settings_path.exists():
            raw = self._settings_path.read_text(encoding="utf-8")
            result = json.loads(raw)
            return result if isinstance(result, dict) else {}

        # Create parent directory if needed
        self._settings_path.parent.mkdir(parents=True, exist_ok=True)
        return {}

    def _write_settings(self, doc: dict[str, Any]) -> None:
        """Write settings.json to disk."""
        self._settings_path.parent.mkdir(parents=True, exist_ok=True)
        raw = json.dumps(doc, indent=2)
        self._settings_path.write_text(raw, encoding="utf-8")

    def _contains_our_hooks(self, hooks: dict[str, Any]) -> bool:
        """Check if any hook entry contains our marker."""
        for entries in hooks.values():
            if not isinstance(entries, list):
                continue
            for entry in entries:
                if self._is_our_hook_entry(entry):
                    return True
        return False

    def _remove_our_hooks(self, hooks: dict[str, Any]) -> None:
        """Remove all hook entries containing our marker."""
        for key in list(hooks.keys()):
            entries = hooks[key]
            if not isinstance(entries, list):
                continue

            hooks[key] = [entry for entry in entries if not self._is_our_hook_entry(entry)]

    @staticmethod
    def _is_our_hook_entry(entry: Any) -> bool:
        """Check if a hook entry was installed by us."""
        if not isinstance(entry, dict):
            return False
        inner_hooks = entry.get("hooks")
        if not isinstance(inner_hooks, list):
            return False
        for h in inner_hooks:
            if isinstance(h, dict):
                cmd = h.get("command", "")
                if isinstance(cmd, str) and HOOK_MARKER in cmd:
                    return True
        return False

    @staticmethod
    def _cleanup_empty_hooks(doc: dict[str, Any]) -> None:
        """Remove empty hook arrays and the hooks key if empty."""
        hooks = doc.get("hooks")
        if not isinstance(hooks, dict):
            return

        empty_keys = [k for k, v in hooks.items() if isinstance(v, list) and len(v) == 0]
        for key in empty_keys:
            del hooks[key]

        if not hooks:
            doc.pop("hooks", None)
