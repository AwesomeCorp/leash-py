"""Copilot CLI subprocess LLM client."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import TYPE_CHECKING

from leash.models.llm_response import LLMResponse
from leash.services.cli_process_runner import MAX_OUTPUT_SIZE
from leash.services.cli_process_runner import run as run_cli
from leash.services.llm_client_base import LLMClientBase

if TYPE_CHECKING:
    from leash.config import ConfigurationManager
    from leash.models.configuration import LlmConfig

logger = logging.getLogger(__name__)

_MAX_RETRIES = 3
_RETRY_DELAY_S = 0.5

# Nesting-detection env vars to strip
_NESTING_ENV_VARS = ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS")

# Keyword sets for heuristic scoring
_DANGEROUS_KEYWORDS = (
    "dangerous",
    "malicious",
    "destructive",
    "rm -rf",
    "format",
    "drop table",
    "injection",
    "exploit",
    "vulnerability",
)
_RISKY_KEYWORDS = (
    "risky",
    "caution",
    "careful",
    "warning",
    "elevated",
    "sudo",
    "admin",
    "sensitive",
    "credentials",
    "password",
    "secret",
)
_SAFE_KEYWORDS = (
    "safe",
    "harmless",
    "benign",
    "standard",
    "normal",
    "routine",
    "read-only",
    "readonly",
    "no risk",
    "low risk",
)


class CopilotCliClient(LLMClientBase):
    """LLM client that uses a Copilot CLI command for safety analysis.

    By default uses "copilot" but can be configured to "gh" (with "copilot" as first arg).
    Parses text responses heuristically to produce structured safety scores.
    Retries up to 3 times with 500ms delay.
    """

    def __init__(
        self,
        config: LlmConfig,
        config_manager: ConfigurationManager | None = None,
    ) -> None:
        super().__init__(config_manager=config_manager, initial_config=config)
        if config is None:
            raise ValueError("config is required")
        self._config = config

    def _get_command(self) -> tuple[str, bool]:
        """Get the CLI command to use.

        Returns (filename, add_copilot_arg). When the command is "gh",
        "copilot" is passed as the first argument.
        """
        cmd = None
        if self._config_manager is not None:
            try:
                cmd = self._config_manager.get_configuration().llm.command
            except Exception:
                pass
        if not cmd:
            cmd = self._config.command
        if not cmd:
            cmd = "copilot"

        if cmd.lower() == "gh":
            return ("gh", True)
        return (cmd, False)

    async def query(self, prompt: str) -> LLMResponse:
        """Send a prompt to the Copilot CLI and return a structured response."""
        timeout = self.current_timeout
        total_start = time.monotonic()

        for attempt in range(1, _MAX_RETRIES + 1):
            start = time.monotonic()
            try:
                output = await self._execute_copilot(prompt, timeout)
                elapsed_ms = int((time.monotonic() - start) * 1000)

                response = parse_text_response(output)
                response.elapsed_ms = elapsed_ms
                logger.info("Copilot CLI query completed in %dms", elapsed_ms)
                return response

            except TimeoutError:
                elapsed_ms = int((time.monotonic() - start) * 1000)
                if attempt < _MAX_RETRIES:
                    logger.warning(
                        "Copilot CLI attempt %d/%d timed out after %dms, retrying...",
                        attempt,
                        _MAX_RETRIES,
                        elapsed_ms,
                    )
                    await asyncio.sleep(_RETRY_DELAY_S)
                else:
                    total_elapsed = int((time.monotonic() - total_start) * 1000)
                    logger.warning(
                        "All %d Copilot CLI attempts timed out (%dms total)",
                        _MAX_RETRIES,
                        total_elapsed,
                    )
                    return self.create_timeout_response("Copilot CLI", _MAX_RETRIES, timeout, total_elapsed)

            except FileNotFoundError:
                cmd, _ = self._get_command()
                return self.create_failure_response(
                    f"CLI command '{cmd}' not found - ensure it is installed and in PATH",
                    f"CLI command '{cmd}' is not installed or not in PATH",
                )

            except RuntimeError:
                elapsed_ms = int((time.monotonic() - start) * 1000)
                if attempt < _MAX_RETRIES:
                    logger.warning("Copilot CLI attempt %d/%d failed, retrying...", attempt, _MAX_RETRIES)
                    await asyncio.sleep(_RETRY_DELAY_S)
                else:
                    logger.error("Copilot CLI query failed after %d attempts", _MAX_RETRIES)
                    return self.create_failure_response(
                        "Copilot CLI query failed",
                        "Copilot CLI query failed due to runtime error",
                    )

        return self.create_retries_exhausted_response("Copilot CLI")

    async def _execute_copilot(self, prompt: str, timeout_ms: int) -> str:
        """Execute the copilot CLI command and return its output."""
        file_name, add_copilot_arg = self._get_command()

        args: list[str] = []
        if add_copilot_arg:
            args.append("copilot")
        args.extend([
            "-p",
            prompt,
            "-s",
            "--allow-all-tools",
            "--no-custom-instructions",
        ])

        # Build environment without nesting-detection vars
        env = dict(os.environ)
        for key in _NESTING_ENV_VARS:
            env.pop(key, None)

        result = await run_cli(file_name, args, timeout_ms, "copilot-cli", env=env)
        return result.output


def parse_text_response(output: str) -> LLMResponse:
    """Parse unstructured text from Copilot into a structured LLMResponse.

    Uses keyword heuristics since Copilot doesn't return JSON.
    """
    if not output or not output.strip():
        return LLMResponse(
            success=False,
            safety_score=50,
            reasoning="Empty response from Copilot CLI -- defaulting to conservative score",
            category="cautious",
        )

    if len(output) > MAX_OUTPUT_SIZE:
        return LLMResponse(
            success=False,
            safety_score=0,
            reasoning="Copilot output exceeded maximum size limit",
        )

    lower = output.lower()

    danger_count = sum(1 for k in _DANGEROUS_KEYWORDS if k in lower)
    risky_count = sum(1 for k in _RISKY_KEYWORDS if k in lower)
    safe_count = sum(1 for k in _SAFE_KEYWORDS if k in lower)

    if danger_count >= 2:
        score = 15
        category = "dangerous"
    elif danger_count >= 1:
        score = 30
        category = "risky"
    elif risky_count >= 2:
        score = 50
        category = "cautious"
    elif risky_count >= 1 and safe_count == 0:
        score = 60
        category = "cautious"
    elif safe_count >= 2:
        score = 90
        category = "safe"
    elif safe_count >= 1:
        score = 80
        category = "safe"
    else:
        # No strong indicators -- conservative default
        score = 50
        category = "cautious"

    # Truncate reasoning to first 500 chars
    reasoning = output[:500] + "..." if len(output) > 500 else output
    reasoning = reasoning.replace("\n", " ").replace("\r", " ").strip()

    return LLMResponse(
        success=True,
        safety_score=score,
        reasoning=reasoning,
        category=category,
    )
