"""Install/uninstall Copilot CLI hook scripts and hooks.json files."""

from __future__ import annotations

import json
import logging
import os
import platform
import shlex
import stat
from pathlib import Path
from typing import Any

from leash.session_start_hook import build_session_hook_command

logger = logging.getLogger(__name__)

SCRIPT_MARKER = "# copilot-analyzer"

COPILOT_EVENTS = ("preToolUse", "postToolUse", "sessionStart")


class CopilotHookInstaller:
    """Generates and manages Copilot CLI hook scripts and hooks.json files.

    Supports both repo-level (.github/hooks/) and user-level (~/.copilot/hooks/) installation.
    """

    def __init__(self, service_url: str = "http://localhost:5050", config_manager: Any = None) -> None:
        self._service_url = service_url
        self._config_manager = config_manager

    # ---- Public API ----

    def is_repo_installed(self, repo_path: str) -> bool:
        """Check if hooks are installed at the repo level (.github/hooks/)."""
        hooks_json = Path(repo_path) / ".github" / "hooks" / "hooks.json"
        return hooks_json.exists() and self._contains_our_hooks(hooks_json)

    def is_user_installed(self) -> bool:
        """Check if hooks are installed at the user level (~/.copilot/hooks/)."""
        hooks_json = self._get_user_hooks_json_path()
        return hooks_json.exists() and self._contains_our_hooks(hooks_json)

    def install_repo(self, repo_path: str) -> None:
        """Install Copilot hooks at the repo level."""
        hooks_dir = Path(repo_path) / ".github" / "hooks"
        logger.info("Installing Copilot hooks at repo level: %s", hooks_dir)
        self._install_to_directory(hooks_dir)

    def install_user(self) -> None:
        """Install Copilot hooks at the user level (~/.copilot/hooks/).

        Note: Copilot CLI only supports repo-level hooks (.github/hooks/).
        User-level installation is provided as a convenience.
        """
        hooks_dir = self._get_user_hooks_dir()
        logger.warning(
            "Installing Copilot hooks at user level (%s). "
            "Note: Copilot CLI only reads hooks from .github/hooks/ in the repository. "
            "Use install_repo() with the target repository path instead.",
            hooks_dir,
        )
        self._install_to_directory(hooks_dir)

    def uninstall_repo(self, repo_path: str) -> None:
        """Uninstall Copilot hooks from the repo level."""
        hooks_dir = Path(repo_path) / ".github" / "hooks"
        logger.info("Uninstalling Copilot hooks from repo level: %s", hooks_dir)
        self._uninstall_from_directory(hooks_dir)

    def uninstall_user(self) -> None:
        """Uninstall Copilot hooks from the user level."""
        hooks_dir = self._get_user_hooks_dir()
        logger.info("Uninstalling Copilot hooks from user level: %s", hooks_dir)
        self._uninstall_from_directory(hooks_dir)

    # ---- Internal installation ----

    def _get_enabled_events(self) -> list[str]:
        """Get copilot events that are enabled in the app config.

        Maps Copilot camelCase event names to the PascalCase names used in hookHandlers config.
        """
        # Copilot event -> config key mapping
        event_map = {
            "preToolUse": "PreToolUse",
            "postToolUse": "PostToolUse",
            "sessionStart": "SessionStart",
        }

        if self._config_manager is None:
            return list(COPILOT_EVENTS)

        config = self._config_manager.get_configuration()
        enabled = []
        for copilot_event in COPILOT_EVENTS:
            config_key = event_map.get(copilot_event, copilot_event)
            hook_config = config.hook_handlers.get(config_key)
            if hook_config is None or hook_config.enabled:
                # If no config exists for this event or it's enabled, include it
                enabled.append(copilot_event)
        return enabled

    def _install_to_directory(self, hooks_dir: Path) -> None:
        """Install scripts and hooks.json to the given directory."""
        hooks_dir.mkdir(parents=True, exist_ok=True)

        enabled_events = self._get_enabled_events()

        # Remove scripts for disabled events
        for event_name in COPILOT_EVENTS:
            if event_name not in enabled_events:
                bash_path = hooks_dir / f"{event_name}.sh"
                ps_path = hooks_dir / f"{event_name}.ps1"
                if bash_path.exists() and SCRIPT_MARKER in bash_path.read_text(encoding="utf-8"):
                    bash_path.unlink()
                if ps_path.exists() and SCRIPT_MARKER in ps_path.read_text(encoding="utf-8"):
                    ps_path.unlink()

        # Generate per-event scripts for enabled events
        for event_name in enabled_events:
            self._write_bash_script(hooks_dir, event_name)
            self._write_powershell_script(hooks_dir, event_name)

        # Generate or update hooks.json (only enabled events)
        self._write_hooks_json(hooks_dir, enabled_events)

        logger.info("Copilot hooks installed at %s (events: %s)", hooks_dir, enabled_events)

    def _uninstall_from_directory(self, hooks_dir: Path) -> None:
        """Remove our scripts and entries from hooks.json."""
        if not hooks_dir.exists():
            logger.debug("Hooks directory not found, nothing to uninstall: %s", hooks_dir)
            return

        # Remove our scripts
        for event_name in COPILOT_EVENTS:
            bash_path = hooks_dir / f"{event_name}.sh"
            ps_path = hooks_dir / f"{event_name}.ps1"

            if bash_path.exists() and SCRIPT_MARKER in bash_path.read_text(encoding="utf-8"):
                bash_path.unlink()
            if ps_path.exists() and SCRIPT_MARKER in ps_path.read_text(encoding="utf-8"):
                ps_path.unlink()

        # Remove our entries from hooks.json
        hooks_json_path = hooks_dir / "hooks.json"
        if hooks_json_path.exists():
            try:
                raw = hooks_json_path.read_text(encoding="utf-8")
                root = json.loads(raw)
                if isinstance(root, dict):
                    # Copilot spec: events are nested under root["hooks"]
                    hooks_obj = root.get("hooks")
                    if isinstance(hooks_obj, dict):
                        self._remove_our_entries(hooks_obj)
                        if not hooks_obj:
                            root.pop("hooks", None)

                    # Also handle legacy flat format
                    self._remove_our_entries(root)

                    # Delete file if only "version" remains (or empty)
                    has_content = any(k != "version" for k in root)
                    if not has_content:
                        hooks_json_path.unlink()
                    else:
                        hooks_json_path.write_text(
                            json.dumps(root, indent=2), encoding="utf-8"
                        )
            except Exception as e:
                logger.warning("Failed to clean up hooks.json at %s: %s", hooks_json_path, e)

        # Clean up empty directory
        if hooks_dir.exists() and not any(hooks_dir.iterdir()):
            try:
                hooks_dir.rmdir()
            except OSError:
                pass  # non-fatal

        logger.info("Copilot hooks uninstalled from %s", hooks_dir)

    # ---- Script generation ----

    def _write_bash_script(self, hooks_dir: Path, event_name: str) -> None:
        """Generate a bash hook script for the given event."""
        script_path = hooks_dir / f"{event_name}.sh"
        if event_name == "sessionStart":
            command = shlex.join(build_session_hook_command("copilot", event_name, self._service_url))
            content = (
                "#!/bin/bash\n"
                f"{SCRIPT_MARKER}\n"
                f"# Copilot CLI hook script for {event_name}\n"
                "set -euo pipefail\n"
                "INPUT=$(cat)\n"
                f"if ! printf '%s' \"$INPUT\" | {command}; then\n"
                "  echo '{}'\n"
                "fi\n"
            )
        else:
            content = (
                "#!/bin/bash\n"
                f"{SCRIPT_MARKER}\n"
                f"# Copilot CLI hook script for {event_name}\n"
                "# Reads JSON from stdin, sends to Leash service, outputs response\n"
                "\n"
                "INPUT=$(cat)\n"
                f'echo "$INPUT" | curl -sS -X POST "{self._service_url}/api/hooks/copilot?event={event_name}" \\\n'
                '  -H "Content-Type: application/json" \\\n'
                "  -d @- 2>/dev/null || echo '{}'\n"
            )
        script_path.write_text(content, encoding="utf-8")

        # Make executable on Unix
        if platform.system() != "Windows":
            try:
                current_mode = script_path.stat().st_mode
                script_path.chmod(current_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
            except Exception as e:
                logger.debug("Could not set executable permission on %s: %s", script_path, e)

    def _write_powershell_script(self, hooks_dir: Path, event_name: str) -> None:
        """Generate a PowerShell hook script for the given event."""
        script_path = hooks_dir / f"{event_name}.ps1"
        if event_name == "sessionStart":
            command = build_session_hook_command("copilot", event_name, self._service_url)
            args_literal = ",\n".join(self._quote_powershell_arg(arg) for arg in command)
            content = (
                f"{SCRIPT_MARKER}\n"
                f"# Copilot CLI hook script for {event_name}\n"
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
        else:
            content = (
                f"{SCRIPT_MARKER}\n"
                f"# Copilot CLI hook script for {event_name}\n"
                "# Reads JSON from stdin, sends to Leash service, outputs response\n"
                "\n"
                "try {\n"
                "    $inputData = [Console]::In.ReadToEnd()\n"
                f'    $response = Invoke-RestMethod -Uri "{self._service_url}/api/hooks/copilot?event={event_name}" `\n'
                "        -Method POST `\n"
                '        -ContentType "application/json" `\n'
                "        -Body $inputData `\n"
                "        -ErrorAction SilentlyContinue\n"
                "    $response | ConvertTo-Json -Compress\n"
                "} catch {\n"
                "    Write-Output '{}'\n"
                "}\n"
            )
        script_path.write_text(content, encoding="utf-8")

    @staticmethod
    def _quote_powershell_arg(arg: str) -> str:
        return "        '" + arg.replace("'", "''") + "'"

    def _write_hooks_json(self, hooks_dir: Path, enabled_events: list[str] | None = None) -> None:
        """Generate or update hooks.json with our hook entries."""
        if enabled_events is None:
            enabled_events = list(COPILOT_EVENTS)
        hooks_json_path = hooks_dir / "hooks.json"

        if hooks_json_path.exists():
            try:
                raw = hooks_json_path.read_text(encoding="utf-8")
                root = json.loads(raw)
                if not isinstance(root, dict):
                    root = {}
                hooks_obj: dict[str, Any] = root.get("hooks", {})
                if not isinstance(hooks_obj, dict):
                    hooks_obj = {}
                self._remove_our_entries(hooks_obj)
            except Exception:
                root = {}
                hooks_obj = {}
        else:
            root = {}
            hooks_obj = {}

        # Add our hook entries per Copilot spec: { type, bash, powershell }
        for event_name in enabled_events:
            event_array: list[Any] = hooks_obj.get(event_name, [])
            if not isinstance(event_array, list):
                event_array = []

            bash_path = str(hooks_dir / f"{event_name}.sh").replace(os.sep, "/")
            ps_path = str(hooks_dir / f"{event_name}.ps1")

            entry = {
                "type": "command",
                "bash": bash_path,
                "powershell": f'powershell -ExecutionPolicy Bypass -File "{ps_path}"',
                "description": f"Leash - {event_name} {SCRIPT_MARKER}",
            }

            event_array.append(entry)
            hooks_obj[event_name] = event_array

        root["version"] = 1
        root["hooks"] = hooks_obj

        hooks_json_path.write_text(json.dumps(root, indent=2), encoding="utf-8")

    # ---- Helpers ----

    def _contains_our_hooks(self, hooks_json_path: Path) -> bool:
        """Check if hooks.json contains our marker."""
        try:
            raw = hooks_json_path.read_text(encoding="utf-8")
            return SCRIPT_MARKER in raw
        except Exception:
            return False

    @staticmethod
    def _remove_our_entries(obj: dict[str, Any]) -> None:
        """Remove entries with our marker from a hooks object."""
        for key in list(obj.keys()):
            entries = obj[key]
            if not isinstance(entries, list):
                continue

            obj[key] = [
                entry
                for entry in entries
                if not _is_our_entry(entry)
            ]

            if not obj[key]:
                del obj[key]

    @staticmethod
    def _get_user_hooks_dir() -> Path:
        return Path.home() / ".copilot" / "hooks"

    @staticmethod
    def _get_user_hooks_json_path() -> Path:
        return Path.home() / ".copilot" / "hooks" / "hooks.json"


def _is_our_entry(entry: Any) -> bool:
    """Check if a hooks.json entry was installed by us."""
    if not isinstance(entry, dict):
        return False

    desc = entry.get("description", "")
    cmd = entry.get("command", "")
    bash = entry.get("bash", "")
    ps = entry.get("powershell", "")

    if isinstance(desc, str) and SCRIPT_MARKER in desc:
        return True
    if isinstance(cmd, str) and SCRIPT_MARKER in cmd:
        return True
    if isinstance(bash, str) and "api/hooks/copilot" in bash:
        return True
    if isinstance(ps, str) and "api/hooks/copilot" in ps:
        return True

    return False
