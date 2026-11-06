"""Architecture-specific views over prioritized repository knowledge."""

from __future__ import annotations

from typing import Literal

from aide_knowledge_mcp.index import KnowledgeError, KnowledgeIndex

ArchitectureLevel = Literal["hld", "lld", "both"]

_LEVEL_TERMS: dict[ArchitectureLevel, str] = {
    "hld": (
        "high-level architecture components boundaries interfaces system flows "
        "deployment responsibilities"
    ),
    "lld": (
        "low-level design modules classes functions contracts errors configuration "
        "memory lifecycle tests"
    ),
    "both": (
        "architecture design components modules interfaces flows contracts "
        "relationships ownership"
    ),
}


class ArchitectureError(KnowledgeError):
    """Raised when an architecture request violates the service contract."""


class ArchitectureService:
    """Compose architecture views without changing the underlying evidence."""

    def __init__(self, index: KnowledgeIndex) -> None:
        self.index = index

    @staticmethod
    def _level(value: str) -> ArchitectureLevel:
        if value not in {"hld", "lld", "both"}:
            raise ArchitectureError("level must be hld, lld, or both")
        return value  # type: ignore[return-value]

    @staticmethod
    def _target_terms(target_paths: list[str] | None) -> str:
        if not target_paths:
            return ""
        if len(target_paths) > 20:
            raise ArchitectureError("target_paths must contain at most 20 entries")
        normalized: list[str] = []
        for path in target_paths:
            value = path.strip().replace("\\", "/")
            if not value or len(value) > 500:
                raise ArchitectureError(
                    "each target path must contain 1-500 characters"
                )
            normalized.append(value)
        return " ".join(normalized)

    @staticmethod
    def _architecture_views(
        primary: list[dict[str, object]],
        secondary: list[dict[str, object]],
    ) -> dict[str, list[dict[str, object]]]:
        views: dict[str, list[dict[str, object]]] = {
            "high_level_design": [],
            "low_level_design": [],
            "specification_relationships": [],
            "folder_specifications": [],
            "other_primary": [],
            "openwiki_architecture": [],
            "openwiki_other": [],
        }
        for item in primary:
            path = str(item.get("path", "")).casefold()
            if path == "knowledge-base/hld.md":
                views["high_level_design"].append(item)
            elif path == "knowledge-base/lld.md":
                views["low_level_design"].append(item)
            elif path.endswith("specs-relationship-map.md"):
                views["specification_relationships"].append(item)
            elif path.endswith("specs.md"):
                views["folder_specifications"].append(item)
            else:
                views["other_primary"].append(item)
        for item in secondary:
            path = str(item.get("path", "")).casefold()
            bucket = (
                "openwiki_architecture"
                if path.startswith("openwiki/architecture/")
                else "openwiki_other"
            )
            views[bucket].append(item)
        return views

    def status(self) -> dict[str, object]:
        """Return architecture capability and underlying source status."""
        result = self.index.status()
        result.update(
            {
                "server": "aide-architecture-mcp",
                "domain": "architecture and design evidence",
                "architecture_views": [
                    "high_level_design",
                    "low_level_design",
                    "specification_relationships",
                    "folder_specifications",
                    "openwiki_architecture",
                ],
                "relationship_mode": (
                    "evidence retrieval from the relationship map; not graph "
                    "database traversal"
                ),
            }
        )
        return result

    def search(
        self,
        query: str,
        level: str = "both",
        target_paths: list[str] | None = None,
        limit: int = 12,
    ) -> dict[str, object]:
        """Search architecture evidence and classify returned views."""
        selected_level = self._level(level)
        target_terms = self._target_terms(target_paths)
        effective_query = " ".join(
            part
            for part in (query.strip(), target_terms, _LEVEL_TERMS[selected_level])
            if part
        )
        result = self.index.search(effective_query, limit, include_secondary=True)
        primary = result["primary_results"]
        secondary = result["secondary_results"]
        if not isinstance(primary, list) or not isinstance(secondary, list):
            raise ArchitectureError("knowledge index returned an invalid result shape")
        result.update(
            {
                "architecture_level": selected_level,
                "target_paths": target_paths or [],
                "architecture_views": self._architecture_views(primary, secondary),
            }
        )
        return result

    def build_context(
        self,
        request: str,
        level: str = "both",
        target_paths: list[str] | None = None,
        limit: int = 16,
        max_chars: int | None = None,
    ) -> dict[str, object]:
        """Build an architecture context package for HLD or LLD work."""
        selected_level = self._level(level)
        enriched_request = (
            f"{request}\nArchitecture focus: {_LEVEL_TERMS[selected_level]}"
        )
        context = self.index.build_context(
            enriched_request,
            target_paths=target_paths,
            limit=limit,
            max_chars=max_chars,
        )
        primary = context["primary_context"]
        secondary = context["secondary_context"]
        if not isinstance(primary, list) or not isinstance(secondary, list):
            raise ArchitectureError("knowledge context returned an invalid shape")
        views = self._architecture_views(primary, secondary)
        expected = (
            ["high_level_design"]
            if selected_level == "hld"
            else ["low_level_design"]
            if selected_level == "lld"
            else ["high_level_design", "low_level_design"]
        )
        evidence_gaps = [
            f"No matching {name.replace('_', ' ')} evidence was retrieved."
            for name in expected
            if not views[name]
        ]
        context.update(
            {
                "architecture_level": selected_level,
                "architecture_views": views,
                "evidence_gaps": evidence_gaps,
                "design_review_checklist": [
                    "component responsibilities and boundaries",
                    "inputs, outputs, interfaces, and data contracts",
                    "runtime and batch sequence flows",
                    "failure propagation, cleanup, and recovery",
                    "configuration and environment dependencies",
                    "memory, cache, queue, task, and process ownership",
                    "affected source, tests, and folder specifications",
                    "uncertainties requiring SME confirmation",
                ],
            }
        )
        return context

    def trace_relationships(
        self,
        component_or_path: str,
        limit: int = 20,
    ) -> dict[str, object]:
        """Retrieve declared relationship evidence for a component or path."""
        subject = component_or_path.strip()
        if not subject or len(subject) > 500:
            raise ArchitectureError("component_or_path must contain 1-500 characters")
        query = (
            f"{subject} dependency depends on parent child consumer producer "
            "interaction interface flow relationship"
        )
        result = self.index.search(query, limit, include_secondary=True)
        primary = result["primary_results"]
        secondary = result["secondary_results"]
        if not isinstance(primary, list) or not isinstance(secondary, list):
            raise ArchitectureError("knowledge index returned an invalid result shape")
        views = self._architecture_views(primary, secondary)
        return {
            "subject": subject,
            "relationship_mode": (
                "Lexical retrieval of declared relationships. Static dependency "
                "evidence does not prove a runtime call."
            ),
            "relationship_map_evidence": views["specification_relationships"],
            "design_evidence": (
                views["high_level_design"]
                + views["low_level_design"]
                + views["folder_specifications"]
                + views["other_primary"]
            ),
            "secondary_openwiki_evidence": secondary,
            "index_version": result["index_version"],
            "warnings": result["warnings"],
        }

    def read_evidence(
        self,
        relative_path: str,
        start_line: int = 1,
        end_line: int | None = None,
    ) -> dict[str, object]:
        """Read an exact bounded range from architecture knowledge."""
        return self.index.read_document(relative_path, start_line, end_line)

    def refresh(self) -> dict[str, object]:
        """Rebuild the in-memory architecture index."""
        changed = self.index.refresh(force=True)
        result = self.status()
        result["rebuilt"] = changed
        return result
