"""Persistent Claude Code client using stream-json format.

Maintains a persistent ``claude`` subprocess with ``--output-format stream-json
--input-format stream-json`` flags and communicates via newline-delimited JSON
messages on stdin/stdout.  Falls back to a one-shot ``ClaudeCliClient`` on failure.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import TYPE_CHECKING

from leash.models.llm_response import LLMResponse
from leash.services.acp_client_base import _build_acp_subprocess_env, _resolve_command_for_platform
from leash.services.claude_cli_client import ClaudeCliClient, parse_response
from leash.services.copilot_cli_client import _parse_text_heuristic
from leash.services.llm_client_base import LLMClientBase, resolve_model_name

if TYPE_CHECKING:
    from leash.config import ConfigurationManager
    from leash.models.configuration import LlmConfig
    from leash.services.terminal_output_service import TerminalOutputService

logger = logging.getLogger(__name__)

_MAX_CONSECUTIVE_FAILURES = 3


class PersistentClaudeStreamClient(LLMClientBase):
    """Persistent Claude Code LLM client using stream-json I/O.

    Spawns ``claude`` with ``--output-format stream-json --input-format stream-json``
    and sends/receives newline-delimited JSON messages.  Falls back to one-shot
    ``ClaudeCliClient`` on failure.

    Message protocol:
    - Send: ``{"type":"user","message":{"role":"user","content":"..."}}\n``
    - Receive assistant chunks: ``{"type":"assistant","message":{"role":"assistant","content":[...]}}``
    - Receive result: ``{"type":"result","subtype":"success","result":"...","session_id":"...","cost_usd":...}``
    """

    def __init__(
        self,
        config: LlmConfig,
        config_manager: ConfigurationManager | None = None,
        terminal_output: TerminalOutputService | None = None,
    ) -> None:
        super().__init__(config_manager=config_manager, initial_config=config, terminal_output=terminal_output)
        if config is None:
            raise ValueError("config is required")
        self._config = config
        self._process: asyncio.subprocess.Process | None = None
        self._lock = asyncio.Lock()
        self._consecutive_failures = 0
        self._disposed = False
        self._fallback_client = ClaudeCliClient(
            config=config,
            config_manager=config_manager,
            terminal_output=terminal_output,
        )
        self._stderr_task: asyncio.Task[None] | None = None

    # -- public API ----------------------------------------------------------

    async def query(self, prompt: str) -> LLMResponse:
        """Send a prompt via stream-json, falling back to one-shot on failure."""
        if self._disposed:
            raise RuntimeError("PersistentClaudeStreamClient has been disposed")

        async with self._lock:
            result = await self._try_stream_query(prompt)
            if result is not None:
                self._consecutive_failures = 0
                return result

        self._push_terminal("claude-stream", "stderr", "Stream query failed -- falling back to one-shot claude")
        logger.warning("Persistent claude-stream query failed, falling back to one-shot")
        return await self._fallback_client.query(prompt)

    # -- stream-json protocol ------------------------------------------------

    @staticmethod
    def _build_user_message(text: str) -> str:
        """Build a stream-json user message."""
        return json.dumps({
            "type": "user",
            "message": {"role": "user", "content": text},
        })

    @staticmethod
    def _parse_result_line(data: dict) -> str | None:
        """Extract the result text from a stream-json result message.

        Returns the ``result`` field value, or None if not a result message.
        """
        if data.get("type") != "result":
            return None
        return data.get("result")

    @staticmethod
    def _parse_assistant_chunks(data: dict) -> str:
        """Extract text from an assistant message's content blocks."""
        if data.get("type") != "assistant":
            return ""
        message = data.get("message", {})
        content = message.get("content", [])
        parts: list[str] = []
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    parts.append(block.get("text", ""))
        return "".join(parts)

    def _parse_assistant_text(self, text: str) -> LLMResponse:
        """Parse collected assistant text into an LLMResponse.

        Tries structured JSON first via ``parse_response``, then falls back
        to keyword heuristics via ``_parse_text_heuristic``.
        """
        result = parse_response(text)
        if result.success:
            return result
        if text and text.strip():
            logger.debug("JSON parsing failed for stream response, falling back to heuristics")
            return _parse_text_heuristic(text)
        return result

    # -- query implementation ------------------------------------------------

    async def _try_stream_query(self, prompt: str) -> LLMResponse | None:
        """Attempt a query via stream-json. Returns None on failure."""
        try:
            if not await self._ensure_process_running():
                return None

            proc = self._process
            if proc is None or proc.stdin is None or proc.stdout is None:
                return None

            timeout = self.current_timeout
            pid = proc.pid
            self._push_terminal("claude-stream", "info", f"[PID {pid}] Sending prompt ({len(prompt)} chars, timeout: {timeout}ms)")
            self._push_terminal("claude-stream", "stdout", f"[PID {pid}] Prompt: {self.preview_prompt(prompt)}")
            logger.info(
                "[claude-stream] Sending prompt (%d chars, timeout: %dms): %s",
                len(prompt), timeout, self.preview_prompt(prompt),
            )

            start = time.monotonic()
            deadline = start + (timeout / 1000.0)

            # Send user message
            msg_line = self._build_user_message(prompt) + "\n"
            proc.stdin.write(msg_line.encode("utf-8"))
            await proc.stdin.drain()

            # Read response lines until we get a result
            collected_text: list[str] = []
            result_text: str | None = None

            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    elapsed_ms = int((time.monotonic() - start) * 1000)
                    self._push_terminal("claude-stream", "stderr", f"[PID {pid}] Timeout after {elapsed_ms}ms")
                    logger.warning("[claude-stream] Timeout after %dms", elapsed_ms)
                    self._increment_failures_and_maybe_kill()
                    return None

                try:
                    line_bytes = await asyncio.wait_for(proc.stdout.readline(), timeout=remaining)
                except asyncio.TimeoutError:
                    elapsed_ms = int((time.monotonic() - start) * 1000)
                    self._push_terminal("claude-stream", "stderr", f"[PID {pid}] Timeout waiting for line after {elapsed_ms}ms")
                    self._increment_failures_and_maybe_kill()
                    return None

                if not line_bytes:
                    logger.error("[claude-stream] stdout closed during prompt")
                    await self._kill_process()
                    return None

                line = line_bytes.decode("utf-8", errors="replace").strip()
                if not line:
                    continue

                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue

                msg_type = data.get("type", "")

                # Collect assistant text chunks
                if msg_type == "assistant":
                    chunk = self._parse_assistant_chunks(data)
                    if chunk:
                        collected_text.append(chunk)
                        self._push_terminal("claude-stream", "stdout", chunk[:200])

                # Result line = turn complete
                elif msg_type == "result":
                    result_text = self._parse_result_line(data)
                    break

            elapsed_ms = int((time.monotonic() - start) * 1000)

            # Prefer result text, fall back to collected assistant chunks
            final_text = result_text if result_text else "".join(collected_text)

            if not final_text:
                self._push_terminal("claude-stream", "stderr", f"[PID {pid}] Empty response after {elapsed_ms}ms")
                self._increment_failures_and_maybe_kill()
                return None

            parsed = self._parse_assistant_text(final_text)
            parsed.elapsed_ms = elapsed_ms
            self._push_terminal(
                "claude-stream", "info",
                f"[PID {pid}] Result in {elapsed_ms}ms -- score={parsed.safety_score}, category={parsed.category}",
            )
            logger.info("[claude-stream] Result in %dms", elapsed_ms)
            return parsed

        except asyncio.CancelledError:
            raise
        except Exception as exc:
            pid_str = f"PID {proc.pid}" if proc is not None else "no process"
            self._push_terminal("claude-stream", "stderr", f"[{pid_str}] Query failed: {exc}")
            logger.error("[claude-stream] Query failed: %s", exc)
            self._increment_failures_and_maybe_kill()
            return None

    # -- process management --------------------------------------------------

    def _build_command_args(self) -> list[str]:
        """Build CLI arguments for the persistent claude stream subprocess."""
        model = self._config.model
        if self._config_manager is not None:
            try:
                model = self._config_manager.get_configuration().llm.model or model
            except Exception:
                logger.warning("[claude-stream] Failed to read model from config", exc_info=True)

        args = [
            "--output-format", "stream-json",
            "--input-format", "stream-json",
            "--verbose",
            "--no-session-persistence",
            "--dangerously-skip-permissions",
            "--settings",
            '{"disableAllHooks":true,"enableAllProjectMcpServers":false,"enableMcpServerCreation":false,"customSlashCommands":{}}',
        ]
        if model:
            args.extend(["--model", resolve_model_name(model)])
        if self._config.system_prompt:
            args.extend(["--system-prompt", self._config.system_prompt])
        return args

    async def _ensure_process_running(self) -> bool:
        """Start the claude stream process if not already running."""
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
                    logger.warning("[claude-stream] Failed to read command from config", exc_info=True)

            args = self._build_command_args()
            cmd, args = _resolve_command_for_platform(cmd, args)
            env = _build_acp_subprocess_env()

            self._process = await asyncio.create_subprocess_exec(
                cmd, *args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )

            pid = self._process.pid
            logger.info("[claude-stream] Process started (PID: %s)", pid)
            self._push_terminal("claude-stream", "info", f"Process started (PID: {pid}, cmd: {cmd} {' '.join(args)})")

            # Consume stderr in background
            proc = self._process
            self._stderr_task = asyncio.create_task(self._consume_stderr(proc))

            # Brief check that the process didn't die immediately
            await asyncio.sleep(0.3)
            if self._process.returncode is not None:
                self._push_terminal("claude-stream", "stderr", f"[PID {pid}] Process exited immediately (code {self._process.returncode})")
                logger.error("[claude-stream] Process exited immediately with code %s", self._process.returncode)
                await self._kill_process()
                return False

            self._push_terminal("claude-stream", "info", f"[PID {pid}] Stream process ready")
            return True

        except FileNotFoundError:
            self._push_terminal("claude-stream", "stderr", "CLI 'claude' not found in PATH")
            logger.error("[claude-stream] CLI 'claude' not found in PATH")
            await self._kill_process()
            return False
        except Exception as exc:
            self._push_terminal("claude-stream", "stderr", f"Failed to start: {exc}")
            logger.error("[claude-stream] Failed to start process: %s", exc)
            await self._kill_process()
            return False

    async def _consume_stderr(self, proc: asyncio.subprocess.Process) -> None:
        """Read stderr, forwarding to terminal output and debug log."""
        if proc.stderr is None:
            return
        try:
            while True:
                line_bytes = await proc.stderr.readline()
                if not line_bytes:
                    break
                line = line_bytes.decode("utf-8", errors="replace").strip()
                if line:
                    self._push_terminal("claude-stream", "stderr", line)
                    logger.debug("[claude-stream stderr] %s", line)
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.debug("[claude-stream] Stderr consumer ended unexpectedly", exc_info=True)

    def _increment_failures_and_maybe_kill(self) -> None:
        """Track consecutive failures, killing the process after too many."""
        self._consecutive_failures += 1
        if self._consecutive_failures >= _MAX_CONSECUTIVE_FAILURES:
            task = asyncio.create_task(self._kill_process())
            task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)

    async def _kill_process(self) -> None:
        """Terminate the persistent process."""
        proc = self._process
        self._process = None

        if proc is not None:
            try:
                if proc.returncode is None:
                    self._push_terminal("claude-stream", "info", f"[PID {proc.pid}] Terminating process")
                    logger.info("[claude-stream] Terminating process (PID: %s)", proc.pid)
                    proc.terminate()
                    try:
                        await asyncio.wait_for(proc.wait(), timeout=2.0)
                    except asyncio.TimeoutError:
                        logger.warning("[claude-stream] Process did not exit, killing (PID: %s)", proc.pid)
                        proc.kill()
                        try:
                            await asyncio.wait_for(proc.wait(), timeout=2.0)
                        except asyncio.TimeoutError:
                            logger.error(
                                "[claude-stream] Process PID %s did not exit after kill — zombie process may remain",
                                proc.pid,
                            )
            except ProcessLookupError:
                pass
            except Exception as exc:
                logger.debug("[claude-stream] Exception killing process: %s", exc)

        if self._stderr_task is not None:
            self._stderr_task.cancel()
            self._stderr_task = None

    async def dispose(self) -> None:
        """Clean up the persistent process."""
        if self._disposed:
            return
        self._disposed = True
        await self._kill_process()
