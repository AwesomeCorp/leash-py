"""Persistent Claude CLI process with stream-json I/O."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import TYPE_CHECKING

from leash.models.llm_response import LLMResponse
from leash.services.claude_cli_client import (
    ClaudeCliClient,
    _build_subprocess_env,
    parse_response,
)
from leash.services.llm_client_base import LLMClientBase

if TYPE_CHECKING:
    from leash.config import ConfigurationManager
    from leash.models.configuration import LlmConfig

logger = logging.getLogger(__name__)

_MAX_CONSECUTIVE_FAILURES = 3


class PersistentClaudeClient(LLMClientBase):
    """LLM client that maintains a persistent claude CLI process using stream-json I/O.

    Sends user messages as {"type":"user","message":{"role":"user","content":"..."}}
    on stdin, reads {"type":"result",...} responses from stdout. The process stays
    alive between requests. Falls back to a one-shot ClaudeCliClient on failure.
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
        self._process: asyncio.subprocess.Process | None = None
        self._lock = asyncio.Lock()
        self._consecutive_failures = 0
        self._disposed = False
        self._fallback_client = ClaudeCliClient(config, config_manager=config_manager)
        self._stderr_task: asyncio.Task[None] | None = None

    async def query(self, prompt: str) -> LLMResponse:
        """Send a prompt via the persistent process, falling back to one-shot on failure."""
        if self._disposed:
            raise RuntimeError("PersistentClaudeClient has been disposed")

        async with self._lock:
            result = await self._try_stream_query(prompt)
            if result is not None:
                self._consecutive_failures = 0
                return result

        # Fall back to one-shot
        logger.warning("Persistent process query failed, falling back to one-shot Claude CLI")
        return await self._fallback_client.query(prompt)

    async def _try_stream_query(self, prompt: str) -> LLMResponse | None:
        """Attempt a query via the persistent process. Returns None on failure."""
        try:
            if not await self._ensure_process_running():
                return None

            proc = self._process
            if proc is None or proc.stdin is None or proc.stdout is None:
                return None

            timeout = self.current_timeout
            logger.info(
                "Sending prompt to persistent process (%d chars, timeout: %dms): %s",
                len(prompt),
                timeout,
                self.preview_prompt(prompt),
            )

            # Send user message in stream-json format
            escaped = json.dumps(prompt)
            msg = f'{{"type":"user","message":{{"role":"user","content":{escaped}}}}}\n'
            proc.stdin.write(msg.encode("utf-8"))
            await proc.stdin.drain()

            # Read lines until we get a "result" type message
            start = time.monotonic()
            assistant_text: str | None = None
            got_result = False

            while True:
                elapsed = time.monotonic() - start
                remaining = (timeout / 1000.0) - elapsed
                if remaining <= 0:
                    break

                try:
                    line_bytes = await asyncio.wait_for(proc.stdout.readline(), timeout=remaining)
                except asyncio.TimeoutError:
                    break

                if not line_bytes:
                    logger.error("Persistent Claude stdout closed -- process died")
                    await self._kill_process()
                    break

                line = line_bytes.decode("utf-8", errors="replace").strip()
                if not line:
                    continue

                try:
                    data = json.loads(line)
                    msg_type = data.get("type")

                    if msg_type == "assistant":
                        message = data.get("message", {})
                        content = message.get("content", [])
                        if isinstance(content, list):
                            for block in content:
                                if isinstance(block, dict) and block.get("type") == "text":
                                    assistant_text = block.get("text", "")

                    elif msg_type == "result":
                        got_result = True
                        elapsed_ms = int((time.monotonic() - start) * 1000)
                        logger.info("Persistent process result received in %dms", elapsed_ms)
                        break

                except json.JSONDecodeError:
                    if line.lstrip().startswith("{"):
                        logger.debug("Failed to parse JSON line from persistent process")

            elapsed_ms = int((time.monotonic() - start) * 1000)

            if not got_result:
                logger.warning("No result from persistent Claude after %dms", elapsed_ms)
                self._increment_failures_and_maybe_kill()
                return None

            parsed = parse_response(assistant_text or "")
            parsed.elapsed_ms = elapsed_ms
            return parsed

        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("Persistent Claude query failed: %s", exc)
            self._increment_failures_and_maybe_kill()
            return None

    async def _ensure_process_running(self) -> bool:
        """Start the persistent process if it is not already running."""
        if self._process is not None and self._process.returncode is None:
            return True

        await self._kill_process()

        try:
            cmd = "claude"
            if self._config_manager is not None:
                try:
                    configured_cmd = self._config_manager.get_configuration().llm.command
                    if configured_cmd:
                        cmd = configured_cmd
                except Exception:
                    pass

            args = [
                "-p",
                "--model",
                self._config.model,
                "--output-format",
                "stream-json",
                "--input-format",
                "stream-json",
                "--verbose",
                "--no-session-persistence",
                "--dangerously-skip-permissions",
            ]

            if self._config.system_prompt:
                args.extend(["--system-prompt", self._config.system_prompt])

            env = _build_subprocess_env()

            self._process = await asyncio.create_subprocess_exec(
                cmd,
                *args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )

            logger.info(
                "Persistent Claude process started (PID: %s, Model: %s)",
                self._process.pid,
                self._config.model,
            )

            # Consume stderr in background
            proc = self._process
            self._stderr_task = asyncio.create_task(self._consume_stderr(proc))

            # Brief check that the process didn't die immediately
            await asyncio.sleep(0.2)
            if self._process.returncode is not None:
                logger.error("Process exited immediately with code %s", self._process.returncode)
                await self._kill_process()
                return False

            return True

        except FileNotFoundError:
            logger.error("Claude CLI not found -- ensure 'claude' command is installed and in PATH")
            await self._kill_process()
            return False
        except Exception as exc:
            logger.error("Failed to start persistent Claude process: %s", exc)
            await self._kill_process()
            return False

    @staticmethod
    async def _consume_stderr(proc: asyncio.subprocess.Process) -> None:
        """Read and log stderr from the persistent process."""
        if proc.stderr is None:
            return
        try:
            while True:
                line_bytes = await proc.stderr.readline()
                if not line_bytes:
                    break
                line = line_bytes.decode("utf-8", errors="replace").strip()
                if line:
                    logger.debug("[persistent-claude stderr] %s", line)
        except Exception:
            pass

    def _increment_failures_and_maybe_kill(self) -> None:
        """Increment consecutive failure counter and kill process if threshold reached."""
        self._consecutive_failures += 1
        if self._consecutive_failures >= _MAX_CONSECUTIVE_FAILURES:
            # Schedule kill in current event loop without blocking
            asyncio.ensure_future(self._kill_process())

    async def _kill_process(self) -> None:
        """Kill the persistent process and clean up."""
        proc = self._process
        self._process = None

        if proc is not None:
            try:
                if proc.returncode is None:
                    logger.info("Killing persistent process (PID: %s)", proc.pid)
                    proc.kill()
                    await proc.wait()
            except ProcessLookupError:
                pass
            except Exception as exc:
                logger.debug("Exception while killing persistent process: %s", exc)

        if self._stderr_task is not None:
            self._stderr_task.cancel()
            self._stderr_task = None

    async def dispose(self) -> None:
        """Clean up the persistent process."""
        if self._disposed:
            return
        self._disposed = True
        await self._kill_process()
