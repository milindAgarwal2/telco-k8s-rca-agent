"""Offline Postman collection inspection and approved reference change."""

from __future__ import annotations

import copy
import fnmatch
import json
from pathlib import Path
from typing import Any

from .errors import ConfigurationError, VerificationError
from .util import (
    FileTransaction,
    canonical_json,
    normalize_relative,
    safe_join,
    utc_now,
)
from .workflow import assert_current_approval, enforce_scope, load_run, save_run


def _read_collection(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigurationError(f"Invalid Postman collection {path}: {exc}") from exc
    if not isinstance(value.get("item"), list):
        raise ConfigurationError("Postman collection must contain an item array.")
    return value


def _flatten(items: list[dict[str, Any]], prefix: str = "") -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    for item in items:
        name = str(item.get("name", "<unnamed>"))
        qualified = f"{prefix}/{name}" if prefix else name
        if isinstance(item.get("item"), list):
            found.extend(_flatten(item["item"], qualified))
        else:
            request = item.get("request", {})
            found.append(
                {
                    "name": qualified,
                    "method": request.get("method"),
                    "url": request.get("url"),
                    "events": [event.get("listen") for event in item.get("event", [])],
                    "test_lines": [
                        line
                        for event in item.get("event", [])
                        if event.get("listen") == "test"
                        for line in event.get("script", {}).get("exec", [])
                    ],
                }
            )
    return found


def inspect(root: Path, collection_path: str) -> dict[str, Any]:
    """Parse a collection deterministically without sending requests."""

    relative = normalize_relative(collection_path)
    value = _read_collection(safe_join(root, relative, allow_leaf_missing=False))
    return {
        "collection": relative,
        "name": value.get("info", {}).get("name"),
        "requests": _flatten(value["item"]),
        "network_requests_sent": 0,
    }


def _ready_item() -> dict[str, Any]:
    return {
        "name": "Readiness",
        "event": [
            {
                "listen": "test",
                "script": {
                    "type": "text/javascript",
                    "exec": [
                        'pm.test("readiness returns HTTP 200", function () {',
                        "  pm.response.to.have.status(200);",
                        "});",
                    ],
                },
            }
        ],
        "request": {
            "method": "GET",
            "header": [],
            "url": {
                "raw": "{{baseUrl}}/readyz",
                "host": ["{{baseUrl}}"],
                "path": ["readyz"],
            },
            "description": (
                "Offline-authored readiness contract; execution is separate."
            ),
        },
        "response": [],
    }


def apply_readyz(
    root: Path,
    run_id: str,
    collection_path: str,
    runbook_path: str,
) -> dict[str, Any]:
    """Apply only the approved offline reference change."""

    collection_relative = normalize_relative(collection_path)
    runbook_relative = normalize_relative(runbook_path)
    run = load_run(root, run_id)
    assert_current_approval(root, run, f"postman:{collection_relative}:readyz")
    for relative in (collection_relative, runbook_relative):
        if not any(fnmatch.fnmatch(relative, pattern) for pattern in run["scope"]):
            raise VerificationError(f"Approved scope does not include {relative}")
    enforce_scope(root, run)
    collection_target = safe_join(root, collection_relative, allow_leaf_missing=False)
    runbook_target = safe_join(root, runbook_relative)
    collection = _read_collection(collection_target)
    before = copy.deepcopy(collection)
    requests = _flatten(collection["item"])
    if not any(req["name"] == "Readiness" for req in requests):
        collection["item"].append(_ready_item())
    runbook = (
        b"# Readiness request runbook\n\n"
        b"This change adds `GET {{baseUrl}}/readyz` without executing it.\n\n"
        b"- Set `baseUrl` in an approved non-production environment.\n"
        b"- Run the Readiness request with an approved Postman/Newman workflow.\n"
        b"- Expected result: HTTP 200.\n"
        b"- No credential is committed by this artifact.\n"
    )
    transaction = FileTransaction()
    try:
        transaction.write(collection_target, canonical_json(collection))
        transaction.write(runbook_target, runbook)
        result = verify_readyz(root, collection_relative, before=before)
        if result["status"] != "PASS":
            raise VerificationError("Postman structural verification failed.")
        run["state"] = "VERIFYING"
        run["updated_at"] = utc_now()
        save_run(root, run)
        return result
    except Exception:
        transaction.rollback()
        raise


def verify_readyz(
    root: Path, collection_path: str, before: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Verify structure and assertions without executing the collection."""

    value = _read_collection(
        safe_join(root, normalize_relative(collection_path), allow_leaf_missing=False)
    )
    requests = _flatten(value["item"])
    candidates = [item for item in requests if item["name"] == "Readiness"]
    checks = {
        "exactly_one_readiness": len(candidates) == 1,
        "method_get": bool(candidates) and candidates[0]["method"] == "GET",
        "url_readyz": bool(candidates)
        and isinstance(candidates[0]["url"], dict)
        and candidates[0]["url"].get("raw") == "{{baseUrl}}/readyz",
        "has_test_event": bool(candidates) and "test" in candidates[0]["events"],
        "asserts_http_200": bool(candidates)
        and any(
            "pm.response.to.have.status(200)" in line
            for line in candidates[0]["test_lines"]
        ),
        "prior_collection_metadata_preserved": before is None
        or value.get("info") == before.get("info"),
        "prior_variables_preserved": before is None
        or value.get("variable") == before.get("variable"),
        "prior_items_preserved": before is None
        or [item for item in value["item"] if item.get("name") != "Readiness"]
        == before["item"],
        "network_requests_sent": True,
    }
    return {
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "network_requests_sent": 0,
    }
