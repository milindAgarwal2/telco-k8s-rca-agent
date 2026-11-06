"""Create a deterministic, redacted inventory of a Postman collection."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

VARIABLE_PATTERN = re.compile(r"{{\s*([^{}]+?)\s*}}")


class InventoryError(Exception):
    """Raised when a collection cannot be inventoried safely."""


def find_variable_names(value: Any) -> set[str]:
    """Return referenced Postman variable names without returning values."""
    names: set[str] = set()
    if isinstance(value, str):
        names.update(match.group(1) for match in VARIABLE_PATTERN.finditer(value))
    elif isinstance(value, list):
        for item in value:
            names.update(find_variable_names(item))
    elif isinstance(value, dict):
        for item in value.values():
            names.update(find_variable_names(item))
    return names


def variable_keys(items: Any) -> list[str]:
    """Return variable keys while deliberately omitting their values."""
    if not isinstance(items, list):
        return []
    keys = {
        str(item["key"])
        for item in items
        if isinstance(item, dict) and item.get("key") is not None
    }
    return sorted(keys)


def query_keys(query: str) -> list[str]:
    """Return decoded query parameter names without parameter values."""
    keys = []
    for part in query.split("&"):
        if not part:
            continue
        key = part.split("=", 1)[0]
        keys.append(unquote(key))
    return sorted(set(keys))


def sanitize_url(raw_url: str) -> str:
    """Redact URL credentials, fragments, and query values."""
    expanded = VARIABLE_PATTERN.sub(lambda match: "{" + match.group(1) + "}", raw_url)
    parsed = urlsplit(expanded)
    authority = parsed.netloc.rsplit("@", 1)[-1]
    prefix = ""
    if parsed.scheme:
        prefix = f"{parsed.scheme}://{authority}"
    elif authority:
        prefix = f"//{authority}"
    path = parsed.path
    keys = query_keys(parsed.query)
    query = "&".join(f"{key}=<redacted>" for key in keys)
    return f"{prefix}{path}" + (f"?{query}" if query else "")


def request_url(request: dict[str, Any]) -> str:
    """Extract and sanitize a request URL from supported Postman forms."""
    url = request.get("url", "")
    if isinstance(url, str):
        return sanitize_url(url)
    if not isinstance(url, dict):
        return ""
    if isinstance(url.get("raw"), str):
        return sanitize_url(url["raw"])

    protocol = str(url.get("protocol", ""))
    host_value = url.get("host", [])
    path_value = url.get("path", [])
    host = ".".join(str(part) for part in host_value) if isinstance(
        host_value, list
    ) else str(host_value)
    path = "/".join(str(part) for part in path_value) if isinstance(
        path_value, list
    ) else str(path_value)
    query = url.get("query", [])
    keys = []
    if isinstance(query, list):
        keys = sorted(
            {
                str(item["key"])
                for item in query
                if isinstance(item, dict) and item.get("key") is not None
            }
        )
    raw = f"{protocol}://{host}/{path}" if protocol else f"{host}/{path}"
    suffix = "&".join(f"{key}=<redacted>" for key in keys)
    return sanitize_url(raw) + (f"?{suffix}" if suffix else "")


def auth_type(auth: Any, inherited: str) -> tuple[str, bool]:
    """Return the effective authentication type and inheritance status."""
    if auth is None:
        return inherited, bool(inherited)
    if not isinstance(auth, dict):
        return "unknown", False
    return str(auth.get("type", "unknown")), False


def script_counts(events: Any) -> dict[str, int]:
    """Count script categories and assertions without exposing script source."""
    counts = {"pre_request": 0, "tests": 0, "assertions": 0}
    if not isinstance(events, list):
        return counts
    for event in events:
        if not isinstance(event, dict):
            continue
        listen = event.get("listen")
        if listen == "prerequest":
            counts["pre_request"] += 1
        elif listen == "test":
            counts["tests"] += 1
        script = event.get("script", {})
        source = script.get("exec", []) if isinstance(script, dict) else []
        if isinstance(source, str):
            source = [source]
        if isinstance(source, list):
            counts["assertions"] += sum(
                str(line).count("pm.test(") for line in source
            )
    return counts


def add_counts(left: dict[str, int], right: dict[str, int]) -> dict[str, int]:
    """Add two script count dictionaries."""
    return {key: left[key] + right[key] for key in left}


def build_inventory(collection: dict[str, Any], source_name: str, digest: str) -> dict:
    """Build a deterministic redacted inventory from parsed collection data."""
    info = collection.get("info", {})
    if not isinstance(info, dict):
        info = {}
    collection_auth, _ = auth_type(collection.get("auth"), "")
    collection_scripts = script_counts(collection.get("event"))
    requests: list[dict[str, Any]] = []
    warnings: list[str] = []

    def walk(
        items: Any,
        parents: list[str],
        inherited_auth: str,
        inherited_scripts: dict[str, int],
    ) -> None:
        if not isinstance(items, list):
            warnings.append("Expected an item list at " + "/".join(parents))
            return
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                warnings.append(
                    "Ignored non-object item at " + "/".join(parents + [str(index)])
                )
                continue
            name = str(item.get("name", f"item-{index}"))
            current_path = parents + [name]
            own_scripts = script_counts(item.get("event"))
            effective_scripts = add_counts(inherited_scripts, own_scripts)
            current_auth, is_inherited = auth_type(
                item.get("auth"), inherited_auth
            )
            if "item" in item and "request" not in item:
                walk(item["item"], current_path, current_auth, effective_scripts)
                continue

            request = item.get("request")
            if isinstance(request, str):
                request = {"method": "GET", "url": request}
            if not isinstance(request, dict):
                warnings.append(
                    "Ignored item without request at " + "/".join(current_path)
                )
                continue

            effective_auth, request_auth_inherited = auth_type(
                request.get("auth"), current_auth
            )
            request_scripts = script_counts(request.get("event"))
            effective_scripts = add_counts(effective_scripts, request_scripts)
            variable_names = find_variable_names(request)
            requests.append(
                {
                    "path": "/".join(current_path),
                    "method": str(request.get("method", "GET")).upper(),
                    "url_template": request_url(request),
                    "variables_referenced": sorted(variable_names),
                    "auth_type": effective_auth or "none",
                    "auth_inherited": request_auth_inherited or is_inherited,
                    "scripts": effective_scripts,
                }
            )

    walk(collection.get("item", []), [], collection_auth, collection_scripts)
    requests.sort(key=lambda item: (item["path"], item["method"], item["url_template"]))

    signatures: dict[str, list[str]] = {}
    for request in requests:
        signature = f"{request['method']} {request['url_template']}"
        signatures.setdefault(signature, []).append(request["path"])
    duplicates = [
        {"signature": signature, "requests": sorted(paths)}
        for signature, paths in sorted(signatures.items())
        if len(paths) > 1
    ]

    return {
        "format": "aide-postman-inventory-v1",
        "source": source_name,
        "sha256": digest,
        "collection": {
            "name": str(info.get("name", "")),
            "schema": str(info.get("schema", "")),
            "declared_variables": variable_keys(collection.get("variable")),
        },
        "counts": {
            "requests": len(requests),
            "duplicate_candidates": len(duplicates),
            "warnings": len(warnings),
        },
        "requests": requests,
        "duplicate_candidates": duplicates,
        "warnings": sorted(warnings),
    }


def load_collection(path: Path, max_bytes: int) -> tuple[dict[str, Any], str]:
    """Read and parse a size-bounded Postman collection."""
    if not path.is_file():
        raise InventoryError(f"Collection file does not exist: {path}")
    size = path.stat().st_size
    if size > max_bytes:
        raise InventoryError(
            f"Collection is {size} bytes; limit is {max_bytes} bytes"
        )
    payload = path.read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    try:
        parsed = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise InventoryError(f"Invalid UTF-8 JSON: {error}") from error
    if not isinstance(parsed, dict):
        raise InventoryError("Collection root must be a JSON object")
    return parsed, digest


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Create a deterministic, redacted Postman inventory."
    )
    parser.add_argument("collection", type=Path, help="Postman collection JSON")
    parser.add_argument(
        "--max-bytes",
        type=int,
        default=100 * 1024 * 1024,
        help="Maximum input size; default is 104857600 bytes",
    )
    parser.add_argument(
        "--compact",
        action="store_true",
        help="Emit compact JSON instead of indented JSON",
    )
    return parser.parse_args()


def main() -> int:
    """Run the inventory command and return a process exit code."""
    args = parse_args()
    try:
        collection, digest = load_collection(args.collection, args.max_bytes)
        result = build_inventory(collection, str(args.collection), digest)
    except (InventoryError, OSError) as error:
        print(f"inventory error: {error}", file=sys.stderr)
        return 2
    indent = None if args.compact else 2
    print(json.dumps(result, indent=indent, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

