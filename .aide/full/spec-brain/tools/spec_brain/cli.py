"""Command-line entry point for spec-brain ingestion and diagnostics."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from tools.spec_brain.config import ConfigurationError, SpecBrainSettings
from tools.spec_brain.context_composer import (
    ContextBudgetError,
    compose_context,
    render_markdown,
)
from tools.spec_brain.graphiti_loader import (
    GraphitiDependencyError,
    GraphitiIngestionError,
    GraphitiRuntime,
    GraphitiServiceUnavailable,
    build_episodes,
    select_smoke_episodes,
)
from tools.spec_brain.manifest_builder import (
    build_manifest,
    build_pilot_manifest,
    discover_full_inputs,
)
from tools.spec_brain.models import encode_jsonl
from tools.spec_brain.neo4j_loader import (
    ExactGraphLoader,
    Neo4jDependencyError,
    load_manifest_file,
)
from tools.spec_brain.retrieval import ExactRetrievalError, ExactRetriever


def build_parser() -> argparse.ArgumentParser:
    """Create the command parser without reading configuration or files."""

    parser = argparse.ArgumentParser(
        prog="spec-brain",
        description="Build and query the repository specification knowledge graph.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    config = commands.add_parser(
        "check-config", help="validate configuration without printing secrets"
    )
    config.add_argument(
        "--component",
        choices=("parsed", "exact", "graphiti", "query"),
        default="parsed",
    )

    build = commands.add_parser(
        "build-manifest", help="build deterministic JSON Lines input"
    )
    build.add_argument("--root", type=Path, default=Path.cwd())
    build.add_argument("--scope", choices=("pilot", "full"), default="pilot")
    build.add_argument("--output", type=Path)

    load = commands.add_parser(
        "load-exact", help="additively upsert a manifest into the exact graph"
    )
    load.add_argument("--manifest", type=Path, required=True)
    load.add_argument("--batch-size", type=int, default=500)
    load.add_argument(
        "--skip-schema",
        action="store_true",
        help="do not create stable-ID constraints before loading",
    )

    semantic = commands.add_parser(
        "load-graphiti",
        help="load semantic episodes through approved internal model services",
    )
    semantic.add_argument("--manifest", type=Path, required=True)
    semantic.add_argument(
        "--reference-time",
        required=True,
        help="timezone-aware knowledge snapshot time",
    )
    semantic.add_argument(
        "--smoke",
        action="store_true",
        help="load only one primary and one secondary episode",
    )

    commands.add_parser(
        "check-services",
        help="verify Neo4j and internal model services without mutation",
    )

    query = commands.add_parser(
        "query", help="compose retrieval-first context for a Kiro specification"
    )
    request = query.add_mutually_exclusive_group(required=True)
    request.add_argument("--request")
    request.add_argument("--request-file", type=Path)
    query.add_argument("--target-path", action="append", default=[])
    query.add_argument(
        "--mode",
        choices=("requirements", "design", "tasks", "all"),
        default="all",
    )
    query.add_argument("--format", choices=("json", "markdown"), default="json")
    query.add_argument("--output", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run a spec-brain command and return a process exit code."""

    args = build_parser().parse_args(argv)
    try:
        if args.command == "check-config":
            return _check_config(args.component)
        if args.command == "build-manifest":
            return _build_manifest(args.root, args.scope, args.output)
        if args.command == "load-exact":
            return _load_exact(args.manifest, args.batch_size, args.skip_schema)
        if args.command == "load-graphiti":
            return asyncio.run(
                _load_graphiti(args.manifest, args.reference_time, args.smoke)
            )
        if args.command == "check-services":
            return asyncio.run(_check_services())
        if args.command == "query":
            return asyncio.run(
                _query(
                    request=args.request,
                    request_file=args.request_file,
                    target_paths=args.target_path,
                    mode=args.mode,
                    output_format=args.format,
                    output=args.output,
                )
            )
    except (
        ConfigurationError,
        ContextBudgetError,
        ExactRetrievalError,
        GraphitiDependencyError,
        GraphitiIngestionError,
        GraphitiServiceUnavailable,
        Neo4jDependencyError,
        OSError,
        TypeError,
        ValueError,
    ) as exc:
        print(f"spec-brain: {exc}", file=sys.stderr)
        return 2
    raise AssertionError(f"unhandled command: {args.command}")


def _check_config(component: str) -> int:
    settings = SpecBrainSettings.from_env()
    if component == "exact":
        settings.require_exact()
    elif component == "graphiti":
        settings.require_graphiti()
    elif component == "query":
        settings.require_query()
    print(json.dumps(settings.redacted_summary(), indent=2, sort_keys=True))
    return 0


def _build_manifest(root: Path, scope: str, output: Path | None) -> int:
    if scope == "pilot":
        manifest = build_pilot_manifest(root)
    else:
        markdown_paths, claim_paths = discover_full_inputs(root)
        manifest = build_manifest(root, markdown_paths, claim_paths)
    rendered = encode_jsonl(manifest.entries)
    if output is None:
        sys.stdout.write(rendered)
    else:
        destination = output if output.is_absolute() else root / output
        manifest.write_jsonl(destination)
        print(
            json.dumps(
                {
                    "output": str(destination.resolve()),
                    "nodes": len(manifest.nodes),
                    "relationships": len(manifest.relationships),
                    "scope": scope,
                },
                sort_keys=True,
            )
        )
    return 0


def _load_exact(manifest_path: Path, batch_size: int, skip_schema: bool) -> int:
    settings = SpecBrainSettings.from_env()
    entries = load_manifest_file(manifest_path)
    loader = ExactGraphLoader(settings)
    try:
        loader.check_connectivity()
        if not skip_schema:
            loader.initialize_schema()
        report = loader.load(entries, batch_size=batch_size)
    finally:
        loader.close()
    print(
        json.dumps(
            {
                "nodes": report.nodes,
                "relationships": report.relationships,
                "batches": report.batches,
                "database": settings.neo4j_kb_database,
            },
            sort_keys=True,
        )
    )
    return 0


async def _load_graphiti(
    manifest_path: Path, raw_reference_time: str, smoke: bool
) -> int:
    settings = SpecBrainSettings.from_env()
    settings.require_graphiti()
    reference_time = _parse_reference_time(raw_reference_time)
    entries = load_manifest_file(manifest_path)
    episodes = build_episodes(entries, reference_time)
    if smoke:
        episodes = select_smoke_episodes(episodes)
    runtime = GraphitiRuntime.create(settings)
    try:
        await runtime.check_dependencies()
        await runtime.initialize_schema()
        report = await runtime.add_episodes(episodes)
    finally:
        await runtime.close()
    print(
        json.dumps(
            {
                "episodes_added": report.added,
                "episodes_skipped": report.skipped,
                "database": settings.neo4j_graphiti_database,
                "group_id": settings.graphiti_group_id,
            },
            sort_keys=True,
        )
    )
    return 0


async def _check_services() -> int:
    settings = SpecBrainSettings.from_env()
    runtime = GraphitiRuntime.create(settings)
    try:
        await runtime.check_dependencies()
    finally:
        await runtime.close()
    print(
        json.dumps(
            {
                "neo4j": True,
                "internal_model_service": True,
                "internal_embedding_service": True,
            },
            sort_keys=True,
        )
    )
    return 0


async def _query(
    *,
    request: str | None,
    request_file: Path | None,
    target_paths: list[str],
    mode: str,
    output_format: str,
    output: Path | None,
) -> int:
    settings = SpecBrainSettings.from_env()
    settings.require_query()
    request_text = (
        request_file.read_text(encoding="utf-8").strip()
        if request_file is not None
        else (request or "").strip()
    )
    if not request_text:
        raise ValueError("the specification request must not be empty")

    runtime = GraphitiRuntime.create(settings)
    exact = ExactRetriever(settings)
    try:
        await runtime.check_dependencies()
        semantic = await runtime.search(request_text)
        exact_context = exact.retrieve(request_text, target_paths, semantic)
        package = compose_context(
            request_text,
            exact_context,
            semantic,
            mode=mode,
            max_tokens=settings.max_context_tokens or 0,
        )
    finally:
        exact.close()
        await runtime.close()

    rendered = (
        json.dumps(package, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
        if output_format == "json"
        else render_markdown(package)
    )
    if output is None:
        sys.stdout.write(rendered)
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
        print(str(output.resolve()))
    return 0


def _parse_reference_time(value: str) -> datetime:
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError("reference time must be ISO 8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("reference time must include a timezone")
    return parsed


if __name__ == "__main__":
    raise SystemExit(main())
