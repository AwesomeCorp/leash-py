"""Shared subprocess execution for CLI-based LLM clients."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass

logger = logging.getLogger(__name__)

MAX_OUTPUT_SIZE = 1_048_576  # 1MB


@dataclass
class CliProcessResult:
    """Result of a CLI process execution."""

    output: str
    error: str
    exit_code: int


async def run(
    cmd: str,
    args: list[str],
    timeout_ms: int,
    source_name: str,
    *,
    env: dict[str, str] | None = None,
) -> CliProcessResult:
    """Run a CLI subprocess with timeout and output size limits.

    Starts a process with the given command and arguments, collects stdout/stderr,
    and waits with the specified timeout. Kills the process on timeout.

    Args:
        cmd: The executable to run.
        args: Arguments to pass to the executable.
        timeout_ms: Maximum time in milliseconds to wait for the process.
        source_name: Label for log messages (e.g. "claude-cli").
        env: Optional environment variables for the subprocess.

    Returns:
        A CliProcessResult with output, error, and exit code.

    Raises:
        TimeoutError: When the process does not exit within timeout_ms.
        FileNotFoundError: When the executable is not found.
        RuntimeError: When the process exits with a non-zero exit code.
    """
    logger.debug("[%s] Starting: %s %s (timeout: %dms)", source_name, cmd, " ".join(args), timeout_ms)

    proc = await asyncio.create_subprocess_exec(
        cmd,
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )

    start_time = time.monotonic()

    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(),
            timeout=timeout_ms / 1000.0,
        )
    except asyncio.TimeoutError:
        elapsed = int((time.monotonic() - start_time) * 1000)
        logger.warning("[%s] Process timed out after %dms, killing PID %s", source_name, elapsed, proc.pid)
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        await proc.wait()
        raise TimeoutError(f"Command timed out after {timeout_ms}ms") from None

    stdout_text = stdout_bytes.decode("utf-8", errors="replace") if stdout_bytes else ""
    stderr_text = stderr_bytes.decode("utf-8", errors="replace") if stderr_bytes else ""

    # Truncate oversized output
    if len(stdout_text) > MAX_OUTPUT_SIZE:
        logger.warning("[%s] Output exceeded %d bytes, truncating", source_name, MAX_OUTPUT_SIZE)
        stdout_text = stdout_text[:MAX_OUTPUT_SIZE]

    exit_code = proc.returncode if proc.returncode is not None else -1
    elapsed_ms = int((time.monotonic() - start_time) * 1000)

    if exit_code != 0:
        error_message = stderr_text.strip() or f"Process exited with code {exit_code}"
        logger.warning(
            "[%s] Process exited with code %d in %dms: %s", source_name, exit_code, elapsed_ms, error_message
        )
        raise RuntimeError(f"Command failed with exit code {exit_code}: {error_message}")

    logger.debug("[%s] Completed in %dms (exit code 0)", source_name, elapsed_ms)

    return CliProcessResult(
        output=stdout_text,
        error=stderr_text,
        exit_code=exit_code,
    )
