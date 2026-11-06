from __future__ import annotations

import fnmatch
from typing import Any

from .models import CatalogRecord, Component, Finding, GovernanceStatus


class PolicyEngine:
    def __init__(self, policy_config: dict[str, Any] | None = None):
        config = policy_config or {}
        self.approved = _normalized(config.get("approved_statuses", []))
        self.warning = _normalized(config.get("warning_statuses", []))
        self.review = _normalized(config.get("review_statuses", []))
        self.denied = _normalized(config.get("denied_statuses", []))
        self.unknown_component = GovernanceStatus(config.get("unknown_component_status", "red"))
        self.unknown_version = GovernanceStatus(config.get("unknown_version_status", "yellow"))
        self.catalog_error = GovernanceStatus(config.get("catalog_error_status", "grey"))
        self.whitelisted_patterns = [
            str(value).strip().lower()
            for value in config.get("whitelisted_component_patterns", [])
            if str(value).strip()
        ]

    def whitelist_pattern(self, component: Component) -> str | None:
        name = component.name.strip().lower()
        return next(
            (
                pattern
                for pattern in self.whitelisted_patterns
                if fnmatch.fnmatchcase(name, pattern)
            ),
            None,
        )

    def is_whitelisted(self, component: Component) -> bool:
        return self.whitelist_pattern(component) is not None

    def evaluate(
        self,
        component: Component,
        records: list[CatalogRecord],
        catalog_error: str | None = None,
    ) -> Finding:
        whitelist_pattern = self.whitelist_pattern(component)
        if whitelist_pattern:
            return Finding(
                component,
                GovernanceStatus.GREEN,
                f"The component matches approved whitelist pattern "
                f"'{whitelist_pattern}'.",
                "No SCAS registration action is required for this approved "
                "internal component pattern.",
                policy_rule="WHITELISTED-COMPONENT",
            )
        if catalog_error:
            return Finding(
                component,
                self.catalog_error,
                f"SCAS could not be queried reliably: {catalog_error}",
                "Retry the SCAS lookup before making a governance decision.",
                policy_rule="CATALOG-ERROR",
            )
        if not records:
            return Finding(
                component,
                self.unknown_component,
                "The component is not listed by SCAS Search 3PP.",
                "Request SCAS/3PPT review or replace it with an available component.",
                policy_rule="COMPONENT-NOT-LISTED",
            )

        exact = self._exact_version(component, records)
        record = exact or self._best_record(records)
        status = record.status.strip().lower()

        newer_version_record = next(
            (item for item in records if _stako_says_newer_version_exists(item)),
            None,
        )
        if newer_version_record is not None:
            target = newer_version_record.recommended_version
            if (
                not target
                and newer_version_record.version
                and (
                    not component.version
                    or not _version_equal(
                        component.version, newer_version_record.version
                    )
                )
            ):
                target = newer_version_record.version
            recommendation = (
                f"Evaluate and align to the newer SCAS version {target}, then "
                "run compatibility tests."
                if target
                else "Ask the SCAS/3PPT owner to identify the newer version, "
                "then test and align to it."
            )
            return Finding(
                component,
                GovernanceStatus.AMBER,
                "The Stako comment says that a newer version exists; this "
                "is consolidated into the Amber upgrade-review group and must "
                "not be classified as Red.",
                recommendation,
                newer_version_record,
                "STAKO-NEWER-VERSION-EXISTS",
            )

        if status in self.denied:
            return Finding(
                component,
                GovernanceStatus.RED,
                f"SCAS marks this component/version as '{record.status}'.",
                self._replacement_recommendation(component, record),
                record,
                "SCAS-DENIED",
            )

        if exact and status in self.approved:
            return Finding(
                component,
                GovernanceStatus.GREEN,
                "The detected version is available in SCAS Search 3PP.",
                "No governance action is required.",
                record,
                "EXACT-APPROVED",
            )

        if exact and status in self.warning:
            return Finding(
                component,
                GovernanceStatus.AMBER,
                f"The detected version has conditional SCAS status '{record.status}'.",
                self._replacement_recommendation(component, record),
                record,
                "EXACT-CONDITIONAL",
            )

        if status in self.review:
            search_match = record.raw.get("_governance_search_match", {})
            partial = (
                isinstance(search_match, dict)
                and search_match.get("stage") == "maven-library-partial"
            )
            return Finding(
                component,
                GovernanceStatus.YELLOW,
                (
                    "SCAS returned only a partial Maven library-name match; "
                    "the candidate must be validated manually."
                    if partial
                    else f"SCAS returned review status '{record.status}', "
                    "which requires manual validation."
                ),
                (
                    "Confirm that the detected Maven coordinate and SCAS "
                    "component identify the same library before approving it."
                    if partial
                    else "Ask the SCAS/3PPT owner to clarify the component status."
                ),
                record,
                "PARTIAL-NAME-MATCH" if partial else "STATUS-REVIEW",
            )

        if component.version is None:
            return Finding(
                component,
                self.unknown_version,
                "The framework was detected, but its installed version could not be resolved.",
                "Generate or inspect the dependency lockfile and rerun the assessment.",
                record,
                "VERSION-UNRESOLVED",
            )

        if not exact:
            target = record.recommended_version or record.version
            recommendation = (
                f"Upgrade or align to SCAS version {target} and run compatibility tests."
                if target
                else "Confirm an available version with the SCAS/3PPT owner."
            )
            return Finding(
                component,
                GovernanceStatus.AMBER if target else GovernanceStatus.YELLOW,
                "The framework exists in SCAS, but the detected version is not an exact available match.",
                recommendation,
                record,
                "VERSION-MISMATCH",
            )

        return Finding(
            component,
            GovernanceStatus.YELLOW,
            f"SCAS returned status '{record.status}', which requires manual review.",
            "Ask the SCAS/3PPT owner to clarify the component status.",
            record,
            "STATUS-REVIEW",
        )

    @staticmethod
    def _exact_version(component: Component, records: list[CatalogRecord]) -> CatalogRecord | None:
        if not component.version:
            return None
        for record in records:
            if record.version and _version_equal(component.version, record.version):
                return record
        return None

    def _best_record(self, records: list[CatalogRecord]) -> CatalogRecord:
        def score(record: CatalogRecord) -> tuple[int, int]:
            status = record.status.lower()
            return (
                3 if status in self.approved else 2 if status in self.warning else 1,
                1 if record.recommended_version else 0,
            )

        return max(records, key=score)

    @staticmethod
    def _replacement_recommendation(component: Component, record: CatalogRecord) -> str:
        target = record.recommended_version
        if target:
            return f"Move from {component.version or 'the unresolved version'} to {target} after compatibility testing."
        return "Replace the component or request an approved exception from the SCAS/3PPT owner."


def _normalized(values: list[str]) -> set[str]:
    return {str(value).strip().lower() for value in values}


def _version_equal(left: str, right: str) -> bool:
    def clean(value: str) -> str:
        return value.strip().lower().lstrip("v").split("+")[0]

    return clean(left) == clean(right)


def _stako_says_newer_version_exists(record: CatalogRecord) -> bool:
    comments: list[str] = []
    for key, value in record.raw.items():
        normalized_key = "".join(
            character.lower() for character in str(key) if character.isalnum()
        )
        if "stako" not in normalized_key:
            continue
        if isinstance(value, (list, tuple, set)):
            comments.extend(str(item) for item in value)
        elif isinstance(value, dict):
            comments.extend(str(item) for item in value.values())
        elif value is not None:
            comments.append(str(value))
    text = " ".join(comments).strip().lower()
    if not text:
        return False
    normalized_text = " ".join(text.replace("_", " ").replace("-", " ").split())
    if any(
        phrase in normalized_text
        for phrase in (
            "no newer version",
            "no newer versions",
            "newer version does not exist",
            "newer versions do not exist",
            "newer version doesn't exist",
            "newer versions don't exist",
        )
    ):
        return False
    return any(
        phrase in normalized_text
        for phrase in (
            "newer version exist",
            "newer versions exist",
            "newer version available",
            "newer versions available",
        )
    )
