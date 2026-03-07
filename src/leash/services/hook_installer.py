"""Install/uninstall curl hooks in ~/.claude/settings.json."""

from __future__ import annotations

import json
import logging
import os
import shlex
import stat
from pathlib import Path
from typing import TYPE_CHECKING, Any

from leash.session_start_hook import build_session_hook_command

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

        session_start_installed = False

        # Step 2: Add one curl hook per enabled event type
        # Server-side routing handles handler matching, so we only need
        # one hook entry per event type that pipes stdin JSON to our API.
        for event_name, event_config in app_config.hook_handlers.items():
            if not event_config.enabled:
                continue

            # Check if there are any enabled handlers for this event
            has_enabled = any(h.enabled for h in event_config.handlers)
            if not has_enabled:
                continue

            arr: list[Any] = hooks.get(event_name, [])
            if event_name == "SessionStart":
                command = self._build_session_start_command()
                session_start_installed = True
            else:
                command = (
                    f'curl -sS -X POST "{self._service_url}/api/hooks/claude?event={event_name}" '
                    f'-H "Content-Type: application/json" -d @- {HOOK_MARKER}'
                )

            arr.append({
                "hooks": [{"type": "command", "command": command}],
            })

            hooks[event_name] = arr

        if not session_start_installed:
            self._remove_session_start_script()

        doc["hooks"] = hooks
        self._cleanup_empty_hooks(doc)

        self._write_settings(doc)
        logger.debug("Claude hooks synced successfully")

    def uninstall(self) -> None:
        """Remove hooks marked with the leash marker."""
        logger.debug("Uninstalling Claude hooks")
        self._remove_session_start_script()

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

    def _build_session_start_command(self) -> str:
        script_path = self._write_session_start_script()
        if os.name == "nt":
            return (
                f'powershell -ExecutionPolicy Bypass -NoProfile -File "{script_path}" '
                f"{HOOK_MARKER}"
            )
        return f"bash {shlex.quote(str(script_path))} {HOOK_MARKER}"

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

    def _write_session_start_script(self) -> Path:
        script_path = self._get_session_start_script_path()
        script_path.parent.mkdir(parents=True, exist_ok=True)
        command = build_session_hook_command("claude", "SessionStart", self._service_url)

        if os.name == "nt":
            content = self._build_powershell_session_start_script(command)
        else:
            content = self._build_bash_session_start_script(command)

        script_path.write_text(content, encoding="utf-8")
        if os.name != "nt":
            current_mode = script_path.stat().st_mode
            script_path.chmod(current_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        return script_path

    @staticmethod
    def _build_bash_session_start_script(command: list[str]) -> str:
        return (
            "#!/bin/bash\n"
            f"{HOOK_MARKER}\n"
            "set -euo pipefail\n"
            "INPUT=$(cat)\n"
            f"if ! printf '%s' \"$INPUT\" | {shlex.join(command)}; then\n"
            "  echo '{}'\n"
            "fi\n"
        )

    @staticmethod
    def _build_powershell_session_start_script(command: list[str]) -> str:
        args_literal = ",\n".join(HookInstaller._quote_powershell_arg(arg) for arg in command)
        return (
            f"{HOOK_MARKER}\n"
            "try {\n"
            "    $inputData = [Console]::In.ReadToEnd()\n"
            "    $command = @(\n"
            f"{args_literal}\n"
            "    )\n"
            "    $response = $inputData | & $command[0] $command[1..($command.Length - 1)] | Out-String\n"
            "    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($response)) {\n"
            "        Write-Output '{}'\n"
            "    } else {\n"
            "        Write-Output $response.TrimEnd()\n"
            "    }\n"
            "} catch {\n"
            "    Write-Output '{}'\n"
            "}\n"
        )

    @staticmethod
    def _quote_powershell_arg(arg: str) -> str:
        return "        '" + arg.replace("'", "''") + "'"

    @staticmethod
    def _get_session_start_script_path() -> Path:
        suffix = ".ps1" if os.name == "nt" else ".sh"
        return Path.home() / ".leash" / "hooks" / f"claude-session-start{suffix}"

    def _remove_session_start_script(self) -> None:
        script_path = self._get_session_start_script_path()
        if not script_path.exists():
            return
        try:
            raw = script_path.read_text(encoding="utf-8")
            if HOOK_MARKER in raw:
                script_path.unlink()
        except OSError:
            logger.debug("Failed to remove SessionStart script at %s", script_path, exc_info=True)
