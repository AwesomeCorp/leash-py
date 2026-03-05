# Leash

Observe and enforce Claude Code & Copilot CLI permission requests via LLM-based safety analysis. Web dashboard, system tray notifications, transcript browsing with token usage tracking, and multi-provider LLM support.

**Core flow:** Claude Code / Copilot CLI &rarr; `curl` hook &rarr; `POST /api/hooks/{client}` &rarr; LLM safety analysis &rarr; approve/deny/passthrough

**Default mode:** Observe-only. Hooks log events but return no decision. Enforcement can be toggled from the dashboard or via `--enforce`.

## Install & Run

### One-liner (any platform)

```bash
# Run directly from GitHub (no install needed)
uvx --from git+https://github.com/AwesomeCorp/leash leash

# Or install globally
uv tool install git+https://github.com/AwesomeCorp/leash
leash
```

### pip install

```bash
pip install git+https://github.com/AwesomeCorp/leash.git
leash
```

### Platform-specific with tray support

**Windows** (tray icon + toast notifications with approve/deny buttons):
```powershell
pip install "leash[tray] @ git+https://github.com/AwesomeCorp/leash.git"
leash
```

**macOS**:
```bash
pip install "leash[tray] @ git+https://github.com/AwesomeCorp/leash.git"
leash
```

**Linux**:
```bash
pip install "leash[tray] @ git+https://github.com/AwesomeCorp/leash.git"
leash
# Optional: install notify-send and zenity for native notifications
```

### From source

```bash
git clone https://github.com/AwesomeCorp/leash.git
cd leash
uv sync --all-extras
uv run leash
```

### From release binary (no Python required)

Download the latest release for your platform from [Releases](https://github.com/AwesomeCorp/leash/releases):

| Platform | Download |
|----------|----------|
| Windows | `leash-windows-amd64.zip` |
| macOS (Intel) | `leash-macos-amd64.tar.gz` |
| macOS (Apple Silicon) | `leash-macos-arm64.tar.gz` |
| Linux | `leash-linux-amd64.tar.gz` |

Extract and run:
```bash
# Windows
.\leash.exe

# macOS / Linux
chmod +x leash
./leash
```

## Quick Start

```bash
leash                    # Start (auto-installs hooks, opens browser)
leash --enforce          # Start in enforcement mode
leash --no-hooks         # Start without installing hooks
leash --port 8080        # Custom port (default: 5050)
leash --no-browser       # Don't open browser on startup
```

On startup: loads config &rarr; installs hooks &rarr; starts at `http://localhost:5050` &rarr; opens browser. Settings (enforcement mode, security profile, LLM analysis toggle) persist across sessions.

## How It Works

### Hook Architecture (curl-based, zero dependencies)

On startup, Leash writes to `~/.claude/settings.json`:

```json
{
  "hooks": {
    "PreToolUse": [{
      "matcher": "Bash|Edit|Write",
      "hooks": [{ "type": "command", "command": "curl -sS -X POST \"http://localhost:5050/api/hooks/claude?event=PreToolUse\" -H \"Content-Type: application/json\" -d @- # leash" }]
    }]
  }
}
```

The `# leash` comment is a marker for clean uninstall (only removes our hooks, not yours).

### Enforcement Modes

| Mode | Behavior |
|------|----------|
| **Observe** (default) | Logs events, optionally runs LLM analysis, returns `{}` - Claude asks user as normal |
| **Approve-Only** | Auto-approves safe requests, falls through to user on anything uncertain |
| **Enforce** | Full control - approve safe requests, deny dangerous ones, tray notifications for uncertain |

Dashboard button cycles: Observe &rarr; Approve-Only &rarr; Enforce &rarr; Observe.

In Observe mode, LLM analysis can be toggled on/off from the dashboard (off = pure log-only with zero latency).

### LLM Providers

| Provider | Config `llm.provider` | Description |
|----------|----------------------|-------------|
| Anthropic API | `anthropic-api` | Direct HTTP to Anthropic (fastest) |
| Claude CLI | `claude-cli` | One-shot `claude` subprocess |
| Persistent Claude | `claude-persistent` | Persistent `claude` process with stream-json I/O |
| Copilot CLI | `copilot-cli` | GitHub Copilot CLI subprocess |
| Generic REST | `generic-rest` | Any REST LLM API (OpenAI, local, etc.) |

### System Tray & Notifications

- **Windows**: System tray icon (pystray) + Windows toast notifications with interactive Approve/Deny buttons
- **macOS**: Native notifications via osascript with interactive dialogs
- **Linux**: notify-send for alerts, zenity for interactive dialogs

Install with `pip install "leash[tray]"` to enable.

## Web Dashboard

| Page | URL | Features |
|------|-----|----------|
| Dashboard | `/` | Stats, charts, profiles, insights, hooks install/enforce toggles |
| Live Logs | `/logs.html` | 6 filters, incremental updates, export CSV/JSON, link to transcripts |
| Transcripts | `/transcripts.html` | Hierarchical session tree (parent + subagents), token usage per session/project, SSE live stream, markdown rendering, tool diffs |
| Prompt Editor | `/prompts.html` | Edit LLM prompt templates |
| Configuration | `/config.html` | Service config + hook handler management |
| Claude Settings | `/claude-settings.html` | JSON editor for `~/.claude/settings.json` |
| Copilot Settings | `/copilot-settings.html` | JSON editor for `~/.copilot/hooks/hooks.json` |

### Transcript Features

- **Hierarchical sessions**: Parent sessions with expandable subagent children (Claude Code Agent tool)
- **Token usage tracking**: Per-session and per-project token counts with model breakdown (Claude + Copilot)
- **CWD from JSONL**: Project grouping uses actual working directory from transcript metadata
- **Live streaming**: SSE-based real-time transcript updates
- **Rich rendering**: Markdown, side-by-side diffs for Edit/Write tools, collapsible tool results

## Configuration

Config auto-created at `~/.leash/config.json`. All settings persist across sessions:

```json
{
  "llm": { "provider": "claude-persistent", "model": "opus", "timeout": 15000 },
  "server": { "port": 5050, "host": "localhost" },
  "security": { "apiKey": null, "rateLimitPerMinute": 600 },
  "profiles": { "activeProfile": "moderate" },
  "enforcementMode": "observe",
  "analyzeInObserveMode": true,
  "tray": { "enabled": true, "alertOnDenied": true, "alertOnUncertain": false, "interactiveEnabled": true }
}
```

## Development

```bash
uv sync --all-extras        # Install all deps including dev
uv run pytest -v            # Run tests
uv run ruff check src/ tests/  # Lint
uv run leash               # Run from source
```

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Web framework | FastAPI + Uvicorn |
| Models | Pydantic v2 (camelCase aliases) |
| HTTP client | httpx |
| SSE | sse-starlette |
| File watching | watchfiles |
| Tray (optional) | pystray + Pillow + windows-toasts |
| Frontend | Vanilla HTML/CSS/JS (zero dependencies) |
| Testing | pytest + pytest-asyncio + pytest-mock |
| Package mgmt | uv + pyproject.toml + hatchling |
| CI/CD | GitHub Actions (test + release) |

## Security

- ASGI middleware pipeline: Security Headers &rarr; Rate Limiting (600/min) &rarr; API Key Auth
- Input sanitization, path traversal protection
- LLM prompt injection defense
- CORS localhost-only
- Hook error safety: any error returns `{}` (no opinion)

## License

MIT
