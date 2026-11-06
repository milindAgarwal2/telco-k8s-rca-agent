from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any


class GovernanceStatus(StrEnum):
    GREEN = "green"
    AMBER = "amber"
    YELLOW = "yellow"
    RED = "red"
    GREY = "grey"


@dataclass(slots=True)
class Component:
    name: str
    version: str | None
    ecosystem: str
    category: str
    source: str
    scope: str = "direct"
    confidence: float = 1.0
    evidence: list[str] = field(default_factory=list)
    purl: str | None = None

    def key(self) -> tuple[str, str]:
        return self.ecosystem.lower(), normalize_name(self.name)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class CatalogRecord:
    name: str
    ecosystem: str | None = None
    version: str | None = None
    status: str = "unknown"
    recommended_version: str | None = None
    support_until: str | None = None
    url: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class Finding:
    component: Component
    status: GovernanceStatus
    reason: str
    recommendation: str
    catalog_record: CatalogRecord | None = None
    policy_rule: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "component": self.component.to_dict(),
            "status": self.status.value,
            "reason": self.reason,
            "recommendation": self.recommendation,
            "catalog_record": (
                self.catalog_record.to_dict() if self.catalog_record else None
            ),
            "policy_rule": self.policy_rule,
        }


@dataclass(slots=True)
class ScanResult:
    repository: str
    components: list[Component]
    warnings: list[str] = field(default_factory=list)
    scanned_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "repository": self.repository,
            "scanned_at": self.scanned_at,
            "component_count": len(self.components),
            "components": [component.to_dict() for component in self.components],
            "warnings": self.warnings,
        }


@dataclass(slots=True)
class Assessment:
    scan: ScanResult
    findings: list[Finding]
    catalog_mode: str
    policy_version: str
    catalog_errors: list[str] = field(default_factory=list)
    assessed_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def counts(self) -> dict[str, int]:
        counts = {status.value: 0 for status in GovernanceStatus}
        for finding in self.findings:
            counts[finding.status.value] += 1
        return counts

    def compliance_score(self) -> float:
        weights = {
            GovernanceStatus.GREEN: 1.0,
            GovernanceStatus.AMBER: 0.65,
            GovernanceStatus.YELLOW: 0.4,
            GovernanceStatus.RED: 0.0,
            GovernanceStatus.GREY: 0.0,
        }
        if not self.findings:
            return 0.0
        return round(
            100 * sum(weights[item.status] for item in self.findings) / len(self.findings),
            1,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "assessment_version": "1.0",
            "assessed_at": self.assessed_at,
            "repository": self.scan.repository,
            "catalog_mode": self.catalog_mode,
            "policy_version": self.policy_version,
            "compliance_score": self.compliance_score(),
            "status_counts": self.counts(),
            "findings": [finding.to_dict() for finding in self.findings],
            "scan_warnings": self.scan.warnings,
            "catalog_errors": self.catalog_errors,
        }


def normalize_name(value: str) -> str:
    return "".join(character.lower() for character in value if character.isalnum())

