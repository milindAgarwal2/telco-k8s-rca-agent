"""Administrator CLI and silent Kiro hook entry point."""

from __future__ import annotations

import datetime as dt
import json
import sqlite3
import sys
import time
from pathlib import Path
from typing import Annotated

import typer

from .server import main as serve_mcp
from .service import LogService, State, audit, observe_hook, read_policy

app = typer.Typer(add_completion=False, no_args_is_help=True)

PROMPT_GUIDANCE = (
    "AIDE Token Saver is active. Use focused retrieval. Immediately before the "
    "final response, call aide_token_stats exactly once and append its compact "
    "AIDE stats line. Never infer provider usage or savings."
)


def _root(workspace: Path) -> Path:
    value = workspace.resolve(strict=True)
    if not value.is_dir():
        raise typer.BadParameter("workspace must be a directory")
    return value


@app.command()
def serve() -> None:
    """Run the workspace-scoped MCP server."""
    serve_mcp()


@app.command(hidden=True)
def hook(
    event: str,
    workspace: Annotated[Path, typer.Option("--workspace")] = Path("."),
) -> None:
    """Observe a Kiro event and inject fixed Prompt Submit guidance."""
    try:
        root = _root(workspace)
        policy = read_policy(root)
        observe_hook(
            event, root, sys.stdin.buffer.read(policy["max_hook_input_bytes"] + 1)
        )
        if event == "PromptSubmit" and policy["enabled"] and policy["mode"] != "off":
            typer.echo(PROMPT_GUIDANCE)
    except Exception:  # noqa: BLE001, S110 - an observer must never block Kiro
        pass


@app.command()
def status(
    workspace: Annotated[Path, typer.Option("--workspace")] = Path("."),
) -> None:
    """Show the current privacy-preserving service snapshot."""
    typer.echo(json.dumps(State(_root(workspace)).snapshot(), indent=2))


@app.command()
def report(
    workspace: Annotated[Path, typer.Option("--workspace")] = Path("."),
    days: Annotated[int, typer.Option(min=1, max=3650)] = 30,
) -> None:
    """Show long-term aggregate response and log-view metrics."""
    typer.echo(json.dumps(State(_root(workspace)).long_term_report(days), indent=2))


@app.command()
def metrics(
    workspace: Annotated[Path, typer.Option("--workspace")] = Path("."),
    days: Annotated[int, typer.Option(min=1, max=90)] = 90,
) -> None:
    """Show Kiro usage, timing, model coverage, and 90-day local trends."""
    typer.echo(json.dumps(State(_root(workspace)).kiro_metrics_report(days), indent=2))


@app.command()
def dashboard_data(
    workspace: Annotated[Path, typer.Option("--workspace")] = Path("."),
    days: Annotated[int, typer.Option(min=1, max=90)] = 30,
) -> None:
    """Return one content-free snapshot for the local Kiro dashboard."""
    root = _root(workspace)
    state = State(root)
    policy = read_policy(root)
    usage = state.kiro_metrics_report(days)
    optimization = state.long_term_report(days)
    activity = state.snapshot()
    typer.echo(
        json.dumps(
            {
                "schema_version": "1.0",
                "generated_at_utc": dt.datetime.now(dt.UTC).isoformat(),
                "collector": {
                    "enabled": policy["enabled"] and policy["mode"] != "off",
                    "retention_days": policy["retention_days"],
                    "last_observed_hook_utc": activity["last_observed_hook_utc"],
                },
                "kiro": usage,
                "optimization": optimization,
                "reported_credits": None,
                "reported_usage_source": "unavailable",
            },
            ensure_ascii=True,
            separators=(",", ":"),
        )
    )


@app.command()
def doctor(
    workspace: Annotated[Path, typer.Option("--workspace")] = Path("."),
) -> None:
    """Validate policy, SQLite state, and approved log roots."""
    root = _root(workspace)
    policy = read_policy(root)
    state = State(root)
    with state.connection() as database:
        integrity = database.execute("PRAGMA integrity_check").fetchone()[0]
    result = {
        "status": "PASS" if integrity == "ok" else "FAIL",
        "mode": policy["mode"],
        "kiro_metrics_enabled": policy["enabled"] and policy["mode"] != "off",
        "retention_days": policy["retention_days"],
        "database_integrity": integrity,
        "state_path": str(state.dbpath),
        "allowed_log_roots": policy["allowed_log_roots"],
        "content_retained": False,
    }
    typer.echo(json.dumps(result, indent=2))
    if result["status"] != "PASS":
        raise typer.Exit(1)


@app.command()
def audit_steering(
    workspace: Annotated[Path, typer.Option("--workspace")] = Path("."),
) -> None:
    """Estimate workspace steering overhead without changing any file."""
    typer.echo(json.dumps(audit(_root(workspace)), indent=2))


@app.command()
def benchmark(
    path: str,
    workspace: Annotated[Path, typer.Option("--workspace")] = Path("."),
) -> None:
    """Measure one approved log page; this is not a Kiro billing benchmark."""
    root = _root(workspace)
    service = LogService(root)
    started = time.perf_counter()
    service.view(path)
    elapsed = round((time.perf_counter() - started) * 1000, 3)
    value = service.state.snapshot()
    value["benchmark_latency_ms"] = elapsed
    value["scope"] = "one local AIDE log view; no provider traffic"
    typer.echo(json.dumps(value, indent=2))


def main() -> None:
    """Run the Typer command application."""
    try:
        app()
    except (OSError, ValueError, sqlite3.Error) as error:
        typer.echo(f"AIDE Token Saver failed: {error}", err=True)
        raise typer.Exit(1) from error


if __name__ == "__main__":
    main()
