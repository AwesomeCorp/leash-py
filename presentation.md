# Leash — Safety Guardrails for AI Coding Agents

**Stay in control without babysitting**

Shahab Movahed

---

## The Problem

AI coding agents are powerful — but they run with **your permissions**.

**Destructive Commands**
A misunderstood prompt can lead to `rm -rf`, force pushes, or dropped tables.

**Silent Execution**
Agents run dozens of commands per session — impossible to review each one manually.

**No Graduated Trust**
It's all-or-nothing: full auto-approve or constant pop-up interruptions.

**No Audit Trail**
What did the agent do last Tuesday? Which tools did it use? No easy answer today.

---

## What is Leash?

> An intelligent safety layer that **observes, evaluates, and gates** every action your AI agent takes — so you stay in control without babysitting.

- **LLM-Powered Scoring** — Every tool call is evaluated by a dedicated LLM. Safe operations pass silently.
- **Interactive Notifications** — Risky requests surface as toast notifications with Approve / Deny buttons.
- **Full Visibility** — Live dashboard with logs, transcripts, latency stats, and audit reports.

---

## How It Works

```
AI Agent ──> Hook (curl POST) ──> Leash (FastAPI) ──> LLM Analysis ──> Threshold Check ──> Decision
 Claude        auto-installed        localhost:5050      safety score      profile-based     approve
 Copilot       zero code changes     fail-safe design      0–100          per-tool          deny
                                                                                            flag
```

1. Claude Code or Copilot makes a tool call (bash, edit, write, etc.)
2. A curl hook intercepts the call and sends it to Leash
3. Leash routes to the right handler and queries an LLM for a safety score (0–100)
4. The score is compared against your active profile threshold
5. Decision: **auto-approve**, **deny**, or **flag for review**

**Zero code changes** — drop-in curl hooks, no modifications to Claude Code or Copilot needed.

**Fail-safe design** — any error returns empty JSON, agent proceeds as normal, never blocks.

---

## Three Enforcement Modes

Graduate your trust level as you gain confidence.

### 1. Observe

Watch & log everything. Agent runs normally. You learn what it does.

*Start here.*

### 2. Approve-Only

Auto-approve safe operations. Uncertain ones fall through to you.

*Recommended for daily use.*

### 3. Enforce

Full control. Approve safe, deny dangerous, flag uncertain with tray alerts.

*Full protection.*

Switch between modes with **one click** on the dashboard.

---

## Security Profiles

One click to match your risk tolerance.

| Profile | Default Threshold | Bash | Write | Edit | Read | Use Case |
|---------|:-:|:-:|:-:|:-:|:-:|----------|
| **Trust** | 50 | 55 | 50 | 50 | 30 | Solo / personal projects |
| **Permissive** | 70 | 80 | 75 | 70 | 60 | Experienced developer |
| **Moderate** | 85 | 90 | 88 | 85 | 75 | Team default |
| **Strict** | 95 | 98 | 96 | 95 | 90 | Sensitive / production code |
| **Lockdown** | 100 | — | — | — | — | Full manual, nothing auto-approved |

Higher threshold = more restrictive. Each profile has **per-tool overrides** — bash commands need higher scores than file reads.

```
Score:  0 ──────────── 50 ──────── 70 ──── 85 ── 95 ── 100
        Dangerous      Trust    Permissive  Mod  Strict  Safe
```

---

## LLM Safety Scoring

When a tool call comes in, Leash constructs a security-focused prompt and sends it to an LLM. The LLM returns a 0–100 score with reasoning and a category.

### Examples

**Score: 95 — Auto-approved**
```
git status
```
Read-only, workspace-scoped, no side effects.

**Score: 72 — Flagged for review**
```
npm install some-unknown-package
```
Modifies node_modules and lockfile, downloads external code.

**Score: 15 — Denied**
```
git push --force origin main
```
Destructive, affects shared state, unreversible data loss risk.

### Scoring Features

- **Hard rules** — `rm -rf /` is always score 0, `cat file.txt` always scores high
- **Graduated criteria** — read-only +40, workspace-scoped +30, destructive -25
- **Prompt injection defense** — untrusted data in delimited blocks, system instructions separated
- **Score clamping** — LLM scores always clamped to 0–100 to prevent manipulation
- **Per-tool templates** — bash, file-write, file-read, web, and MCP each have specialized prompts

---

## Interactive Notifications

Approve or deny from anywhere — no terminal switching.

When Leash encounters an uncertain or denied operation, you get a **native OS notification**:

```
┌─────────────────────────────────┐
│  Leash Safety Alert             │
│                                 │
│  npm install axios              │
│  Score: 72 / 90 threshold       │
│  "External package install"     │
│                                 │
│  [ Approve ]    [ Deny ]        │
└─────────────────────────────────┘
```

- **Windows** — Native toast notifications with action buttons
- **macOS** — Native dialog via osascript
- **Linux** — zenity dialogs + notify-send
- Configurable: alert on denied, uncertain, or both, with timeout support

---

## The Dashboard

Full visibility into every agent action.

### Stats & Monitoring
- Real-time approvals, denials, average scores
- Latency analysis: overall, by provider, by session (p50 / p95 / p99)
- Event trends and approval/denial/logged breakdown charts

### Live Log Streaming
- 6-level filtering: harness, hook type, tool, category, decision, provider
- Chip-based toggle UI with counts
- CSV / JSON export

### Transcript Browser
- Hierarchical session tree (parent sessions + subagent children)
- Token usage tracking with model breakdown
- Side-by-side diffs for Edit/Write tools
- Live SSE streaming as sessions progress

### Controls
- One-click profile switching and enforcement mode toggling
- Hook install / uninstall for Claude and Copilot
- Prompt template editor with live preview
- Full configuration UI (LLM provider, timeouts, rate limits, tray settings)

*Built with vanilla HTML/CSS/JS — zero build step, zero npm dependencies.*

---

## Multi-Provider LLM Support

Use whatever LLM access you already have.

| Provider | Description | Notes |
|----------|-------------|-------|
| **Anthropic API** | Direct HTTP to Claude API | Fastest option, requires API key |
| **Claude CLI** | One-shot `claude` subprocess | Uses existing Claude Code auth |
| **Claude Persistent** | Long-lived `claude` process | Faster responses, parallel queries |
| **Copilot CLI** | GitHub Copilot subprocess | Zero extra cost if you have Copilot |
| **Generic REST** | Any OpenAI-compatible API | Ollama, LM Studio, local models, etc. |

All configurable from the dashboard — switch providers without restarting.

---

## Setup in 2 Minutes

```bash
# Option 1: Run directly (no install)
uvx --from git+https://github.com/AwesomeCorp/leash leash

# Option 2: Install with pip
pip install git+https://github.com/AwesomeCorp/leash.git
leash

# Option 3: With tray notifications
pip install "leash[tray] @ git+https://github.com/AwesomeCorp/leash.git"
```

That's it. Hooks auto-install. Dashboard opens. Observe mode by default.

- **0** code changes needed
- **1** command to start
- Clean uninstall — hooks are marker-based, your own custom hooks are preserved

---

## Live Demo

1. **Dashboard overview** — stats, profiles, enforcement modes
2. **Observe mode** — watch tool calls get scored in real time
3. **Switch to Approve-Only** — safe calls auto-approve silently
4. **Trigger a risky action** — tray notification with Approve / Deny
5. **Transcript browser** — session hierarchy and token tracking

---

## Under the Hood

### Backend
- **FastAPI** with auto-discovered routes
- **Async everywhere** — non-blocking I/O
- **Pydantic v2** models with camelCase aliases
- **JSON file storage** — no database required
- **SSE streaming** for real-time updates
- **Rate limiting** (600 req/min) + input sanitization
- **Prompt injection defense** in all LLM interactions

### Frontend
- **Vanilla HTML/CSS/JS** — zero dependencies
- **Dark / light theme** with CSS variables
- **EventSource** for live log streaming
- **Keyboard shortcuts** (D for theme toggle)
- **CSV / JSON export** for logs

### Security
- Session ID validation, path traversal prevention
- Untrusted data delimited in LLM prompts
- CORS restricted to localhost
- Optional API key authentication
- Score clamping prevents LLM manipulation

---

## Key Takeaways

- **Graduated trust** — from Observe to full Enforce, at your pace
- **LLM-powered safety** — every tool call scored 0–100 with reasoning
- **Zero friction setup** — one command, auto-hooks, no code changes
- **Full audit trail** — every decision logged with score, reasoning, and timing
- **Extensible** — custom profiles, prompt templates, LLM providers, handlers

---

## Questions?

github.com/AwesomeCorp/leash

---

## Appendix: Frequently Asked Questions

**Q: Does Leash slow down the agent?**
LLM analysis adds 1–3 seconds per analyzed call. Read-only and passthrough tools (AskUserQuestion, ReadNotebook, etc.) have near-zero latency. In Observe mode with analysis off, overhead is negligible.

**Q: What happens if Leash crashes or is unreachable?**
Fail-safe design — the curl hook returns an error, Claude Code treats it as "no opinion" and falls back to its normal permission flow. Your agent is never blocked by a Leash failure.

**Q: Can the agent manipulate the safety score via prompt injection?**
Leash uses prompt injection defenses: untrusted data (tool input) is placed in clearly delimited blocks, system instructions are separated, and all scores are clamped to 0–100 regardless of what the LLM returns.

**Q: Does it work with other AI agents beyond Claude Code and Copilot?**
Any tool that supports pre/post hook callbacks via HTTP can integrate. The generic REST client also means Leash can use any LLM for scoring, not just Claude.

**Q: What data does Leash send externally?**
Leash sends tool call details (command, file path, etc.) to whichever LLM provider you configure for safety scoring. Everything else stays local — session data is stored as JSON files on your machine.

**Q: Can I customize what gets flagged?**
Yes — you can edit per-tool prompt templates, adjust thresholds per profile, create custom handler matchers with regex, and add tools to a passthrough list to skip analysis entirely.

**Q: How do I add it to a team workflow?**
Install Leash on each developer's machine. Use Strict or Moderate profiles as a baseline. The audit trail and export features support compliance reviews. Webhook triggers can forward events to external systems (Slack, logging platforms, etc.).
