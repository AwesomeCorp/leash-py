"""CLI entry point for Leash."""

from __future__ import annotations

import argparse
import sys

import uvicorn


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="leash",
        description="Observe and enforce Claude Code permission requests",
    )
    parser.add_argument("--port", type=int, default=5050, help="Port to listen on (default: 5050)")
    parser.add_argument("--host", type=str, default="localhost", help="Host to bind (default: localhost)")
    parser.add_argument("--enforce", action="store_true", help="Start in enforcement mode")
    parser.add_argument("--no-hooks", action="store_true", help="Skip hook installation on startup")
    parser.add_argument("--no-browser", action="store_true", help="Don't open browser on startup")
    parser.add_argument("--config", type=str, default=None, help="Path to config.json")
    parser.add_argument("--run-session-hook", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--hook-provider", type=str, default="", help=argparse.SUPPRESS)
    parser.add_argument("--hook-event", type=str, default="", help=argparse.SUPPRESS)
    parser.add_argument("--service-url", type=str, default="", help=argparse.SUPPRESS)

    args = parser.parse_args(argv)

    if args.run_session_hook:
        from leash.session_start_hook import run_session_hook_proxy

        raise SystemExit(
            run_session_hook_proxy(
                provider=args.hook_provider,
                event=args.hook_event,
                service_url=args.service_url,
            )
        )

    # Store CLI args for the app lifespan to pick up
    import leash.app as app_module

    app = app_module.create_app(config_path=args.config)
    app.state.cli_enforce = args.enforce
    app.state.cli_host = args.host
    app.state.cli_no_hooks = args.no_hooks
    app.state.cli_no_browser = args.no_browser
    app.state.cli_port = args.port

    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        log_level="info",
    )


if __name__ == "__main__":
    main(sys.argv[1:])
