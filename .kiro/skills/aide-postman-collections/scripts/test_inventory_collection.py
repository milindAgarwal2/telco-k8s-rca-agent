"""Tests for the deterministic Postman collection inventory."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from inventory_collection import build_inventory, load_collection


class InventoryCollectionTest(unittest.TestCase):
    """Verify redaction, inheritance, and duplicate detection."""

    def test_inventory_does_not_emit_sensitive_values(self) -> None:
        """Sensitive request material is replaced by structural metadata."""
        collection = {
            "info": {"name": "Example", "schema": "v2.1"},
            "auth": {
                "type": "bearer",
                "bearer": [{"key": "token", "value": "secret-token"}],
            },
            "variable": [{"key": "baseUrl", "value": "internal.example"}],
            "item": [
                {
                    "name": "Users",
                    "item": [
                        {
                            "name": "Get user",
                            "request": {
                                "method": "GET",
                                "url": (
                                    "https://api.example/users/{{userId}}"
                                    "?token=secret-token&view=full"
                                ),
                                "header": [
                                    {"key": "Authorization", "value": "secret-token"}
                                ],
                            },
                            "event": [
                                {
                                    "listen": "test",
                                    "script": {"exec": ["pm.test('ok', () => true);"]},
                                }
                            ],
                        }
                    ],
                }
            ],
        }

        result = build_inventory(collection, "fixture.json", "digest")
        serialized = json.dumps(result)

        self.assertNotIn("secret-token", serialized)
        self.assertNotIn("Authorization", serialized)
        self.assertEqual(result["requests"][0]["auth_type"], "bearer")
        self.assertTrue(result["requests"][0]["auth_inherited"])
        self.assertEqual(result["requests"][0]["variables_referenced"], ["userId"])
        self.assertEqual(result["requests"][0]["scripts"]["assertions"], 1)
        self.assertIn("token=<redacted>", result["requests"][0]["url_template"])

    def test_duplicate_candidates_are_deterministic(self) -> None:
        """Requests with the same method and redacted URL form one candidate."""
        request = {"method": "POST", "url": "https://api.example/jobs?key=one"}
        collection = {
            "item": [
                {"name": "Second", "request": request},
                {
                    "name": "First",
                    "request": {
                        "method": "POST",
                        "url": "https://api.example/jobs?key=two",
                    },
                },
            ]
        }

        result = build_inventory(collection, "fixture.json", "digest")

        self.assertEqual(result["counts"]["duplicate_candidates"], 1)
        self.assertEqual(
            result["duplicate_candidates"][0]["requests"], ["First", "Second"]
        )

    def test_load_collection_hashes_exact_input(self) -> None:
        """The file loader parses JSON and returns a stable SHA-256 digest."""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "collection.json"
            path.write_text('{"item": []}', encoding="utf-8")

            parsed, digest = load_collection(path, 1024)

        self.assertEqual(parsed, {"item": []})
        self.assertEqual(len(digest), 64)


if __name__ == "__main__":
    unittest.main()
