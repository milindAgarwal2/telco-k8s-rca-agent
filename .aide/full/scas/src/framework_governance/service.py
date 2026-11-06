from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable

from .catalog import CatalogError, build_catalog
from .config import load_config
from .models import Assessment, Component, ScanResult
from .policy import PolicyEngine
from .report import ReportWriter
from .scanner import RepositoryScanner


class AssessmentCancelled(RuntimeError):
    pass


class GovernanceService:
    def scan(self, repository: str | Path, config_path: str | Path | None = None) -> ScanResult:
        config = load_config(config_path)
        return RepositoryScanner(config.get("scanner")).scan(repository)

    def assess(
        self,
        repository: str | Path,
        config_path: str | Path | None,
        output_directory: str | Path | None = None,
        scan_result: ScanResult | None = None,
        progress_callback: Callable[[dict[str, Any]], None] | None = None,
        cancellation_check: Callable[[], bool] | None = None,
    ) -> tuple[Assessment, dict[str, str]]:
        config = load_config(config_path)
        scan = scan_result or RepositoryScanner(config.get("scanner")).scan(repository)
        policy = PolicyEngine(config.get("policy"))
        findings = []
        errors: list[str] = []
        total = len(scan.components)

        try:
            catalog = build_catalog(config)
        except CatalogError as exc:
            error = str(exc)
            errors.append(error)
            catalog = None

        for index, component in enumerate(scan.components, start=1):
            if cancellation_check and cancellation_check():
                raise AssessmentCancelled("Assessment cancelled by user.")
            if progress_callback:
                progress_callback(
                    {
                        "event": "item_started",
                        "index": index,
                        "total": total,
                        "component": component.to_dict(),
                    }
                )
            item_started = time.monotonic()
            if policy.is_whitelisted(component):
                finding = policy.evaluate(component, [])
                findings.append(finding)
                if progress_callback:
                    progress_callback(
                        {
                            "event": "item_completed",
                            "index": index,
                            "total": total,
                            "component": component.to_dict(),
                            "finding": finding.to_dict(),
                            "duration_seconds": time.monotonic() - item_started,
                        }
                    )
                continue
            if catalog is None:
                finding = policy.evaluate(component, [], errors[0])
                findings.append(finding)
                if progress_callback:
                    progress_callback(
                        {
                            "event": "item_completed",
                            "index": index,
                            "total": total,
                            "component": component.to_dict(),
                            "finding": finding.to_dict(),
                            "duration_seconds": time.monotonic() - item_started,
                        }
                    )
                continue
            try:
                records = catalog.find(component)
                finding = policy.evaluate(component, records)
            except CatalogError as exc:
                error = str(exc)
                errors.append(error)
                finding = policy.evaluate(component, [], error)
            findings.append(finding)
            if progress_callback:
                progress_callback(
                    {
                        "event": "item_completed",
                        "index": index,
                        "total": total,
                        "component": component.to_dict(),
                        "finding": finding.to_dict(),
                        "duration_seconds": time.monotonic() - item_started,
                    }
                )

        assessment = Assessment(
            scan,
            findings,
            str(config.get("catalog", {}).get("mode", "file")),
            str(config.get("policy_version", "1.0")),
            errors,
        )
        reports = {}
        if output_directory:
            if progress_callback:
                progress_callback({"event": "report_started", "total": total})
            reports = ReportWriter(output_directory).write_all(assessment)
            if progress_callback:
                progress_callback(
                    {"event": "report_completed", "reports": reports, "total": total}
                )
        return assessment, reports

    def check_component(
        self,
        component_data: dict[str, Any],
        config_path: str | Path | None,
    ) -> dict[str, Any]:
        config = load_config(config_path)
        component = Component(
            name=str(component_data["name"]),
            version=component_data.get("version"),
            ecosystem=str(component_data.get("ecosystem", "unknown")),
            category=str(component_data.get("category", "framework")),
            source="manual-query",
        )
        policy = PolicyEngine(config.get("policy"))
        if policy.is_whitelisted(component):
            return policy.evaluate(component, []).to_dict()
        try:
            records = build_catalog(config).find(component)
            return policy.evaluate(component, records).to_dict()
        except CatalogError as exc:
            return policy.evaluate(component, [], str(exc)).to_dict()
