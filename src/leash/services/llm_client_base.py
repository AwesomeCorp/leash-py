"""Shared base class for all LLM client implementations."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from leash.models.llm_response import LLMResponse

if TYPE_CHECKING:
    from leash.config import ConfigurationManager
    from leash.models.configuration import LlmConfig

logger = logging.getLogger(__name__)

MAX_TIMEOUT_MS = 300_000  # 5 minutes
MAX_OUTPUT_SIZE = 1_048_576  # 1MB


class LLMClientBase:
    """Shared infrastructure for all LLM client implementations.

    Provides timeout resolution, error response factories, and prompt preview helpers.
    """

    def __init__(
        self,
        config_manager: ConfigurationManager | None = None,
        initial_config: LlmConfig | None = None,
    ) -> None:
        self._config_manager = config_manager
        self._initial_config = initial_config

    @property
    def current_timeout(self) -> int:
        """Resolve the current timeout from live config, falling back to initial config, then 15000ms.

        Always clamped to [1000, MAX_TIMEOUT_MS].
        """
        timeout: int | None = None
        if self._config_manager is not None:
            try:
                timeout = self._config_manager.get_configuration().llm.timeout
            except Exception:
                pass
        if timeout is None and self._initial_config is not None:
            timeout = self._initial_config.timeout
        if timeout is None:
            timeout = 15000
        return max(1000, min(timeout, MAX_TIMEOUT_MS))

    @staticmethod
    def create_failure_response(error: str, reasoning: str, elapsed_ms: int = 0) -> LLMResponse:
        """Create a failed LLMResponse with the given error and reasoning."""
        return LLMResponse(
            success=False,
            safety_score=0,
            error=error,
            reasoning=reasoning,
            elapsed_ms=elapsed_ms,
        )

    @staticmethod
    def create_timeout_response(
        provider_name: str, max_retries: int, timeout_ms: int, total_elapsed_ms: int
    ) -> LLMResponse:
        """Create a timeout failure response after all retries are exhausted."""
        msg = f"{provider_name} timed out after {max_retries} attempts ({timeout_ms}ms each)"
        return LLMResponse(
            success=False,
            safety_score=0,
            error=msg,
            reasoning=msg,
            elapsed_ms=total_elapsed_ms,
        )

    @staticmethod
    def create_retries_exhausted_response(provider_name: str) -> LLMResponse:
        """Create an exhausted-retries failure response."""
        return LLMResponse(
            success=False,
            safety_score=0,
            error=f"{provider_name} query failed after all retries",
            reasoning="All retry attempts exhausted",
        )

    @staticmethod
    def preview_prompt(prompt: str, max_length: int = 120) -> str:
        """Truncate a prompt for display in logs."""
        if len(prompt) > max_length:
            return prompt[:max_length] + "..."
        return prompt
