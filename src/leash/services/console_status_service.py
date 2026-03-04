"""ANSI console status line with aggregated event stats."""

from __future__ import annotations

import logging
import sys
import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from leash.services.enforcement_service import EnforcementService

logger = logging.getLogger(__name__)

DISPLAY_LINES = 4


class ConsoleStatusService:
    """Tracks aggregated hook event stats and renders a fixed multi-line console block
    using ANSI escape codes for in-place updates. Refreshes on a 500ms debounce.
    """

    def __init__(self, enforcement_service: EnforcementService) -> None:
        self._enforcement_service = enforcement_service
        self._write_lock = threading.Lock()
        self._dirty = False
        self._rendered = False

        # Thread-safe counters
        self._total_events = 0
        self._approved = 0
        self._denied = 0
        self._passthrough = 0
        self._scored_events = 0
        self._total_score = 0

        self._tool_counts: dict[str, int] = {}
        self._counts_lock = threading.Lock()

        # Timer for periodic rendering
        self._timer: threading.Timer | None = None
        self._schedule_render()

    def record_event(
        self,
        decision: str | None,
        tool_name: str | None,
        score: int | None,
        elapsed_ms: int | None,
    ) -> None:
        """Update counters with a new event."""
        self._total_events += 1

        if decision == "auto-approved":
            self._approved += 1
        elif decision == "denied":
            self._denied += 1
        else:
            self._passthrough += 1

        if score is not None:
            self._scored_events += 1
            self._total_score += score

        tool = tool_name or "other"
        with self._counts_lock:
            self._tool_counts[tool] = self._tool_counts.get(tool, 0) + 1

        self._dirty = True

    def _schedule_render(self) -> None:
        """Schedule the next render cycle (500ms)."""
        self._timer = threading.Timer(0.5, self._flush_render)
        self._timer.daemon = True
        self._timer.start()

    def _flush_render(self) -> None:
        """Render if dirty, then schedule next cycle."""
        try:
            if self._dirty:
                self._dirty = False
                self._render()
        finally:
            self._schedule_render()

    def _render(self) -> None:
        """Build and write the status block to the console."""
        total = self._total_events
        approved = self._approved
        denied = self._denied
        passthrough = self._passthrough
        scored = self._scored_events
        avg_score = self._total_score // scored if scored > 0 else 0
        mode = self._enforcement_service.mode.upper()

        # Build tool breakdown pairs
        with self._counts_lock:
            tools = sorted(self._tool_counts.items(), key=lambda kv: kv[1], reverse=True)

        # Line 1: mode + summary
        line1 = f"  {mode} | {total} events | approved:{approved}  denied:{denied}  pass:{passthrough}"
        if scored > 0:
            line1 += f"  avg-score:{avg_score}"

        # Lines 2-3: tool breakdown (wrap at ~70 chars)
        tool_lines: list[str] = []
        current = "  Tools: "
        for name, count in tools:
            entry = f"{name}:{count}  "
            if len(current) + len(entry) > 78 and len(current) > 10:
                tool_lines.append(current)
                current = "         "
            current += entry
        if len(current) > 10:
            tool_lines.append(current)

        # Assemble output block (always exactly DISPLAY_LINES lines)
        lines = [""] * DISPLAY_LINES
        lines[0] = line1
        for i in range(DISPLAY_LINES - 1):
            lines[i + 1] = tool_lines[i] if i < len(tool_lines) else ""

        with self._write_lock:
            output = ""

            # Move cursor up to overwrite previous block
            if self._rendered:
                output += f"\x1b[{DISPLAY_LINES}A"

            for line in lines:
                output += "\x1b[2K"  # Clear entire line
                output += line + "\n"

            self._rendered = True
            sys.stdout.write(output)
            sys.stdout.flush()

    def dispose(self) -> None:
        """Stop the render timer."""
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
