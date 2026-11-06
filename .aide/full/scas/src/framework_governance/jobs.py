from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import time
import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .config import load_config
from .models import Component, ScanResult
from .service import GovernanceService


TERMINAL_STATUSES = {"completed", "failed", "cancelled"}
JOB_ID_PATTERN = re.compile(r"^fg-[0-9]{8}-[0-9]{6}-[a-f0-9]{8}$")


class JobNotFound(FileNotFoundError):
    pass


class JobManager:
    def __init__(self, job_root: str | Path | None = None):
        self.job_root = Path(
            job_root or Path.cwd() / ".framework-governance" / "jobs"
        ).resolve()
        # Keep handles while this manager is alive so Python does not treat a
        # deliberately detached worker as an abandoned subprocess. Terminal
        # workers are reaped after their final state has been persisted.
        self._processes: dict[str, subprocess.Popen[bytes]] = {}

    def start_job(
        self,
        repository_path: str | Path,
        config_path: str | Path,
        output_directory: str | Path,
    ) -> dict[str, Any]:
        repository = Path(repository_path).resolve()
        config_file = Path(config_path).resolve()
        output = Path(output_directory).resolve()
        if not repository.is_dir():
            raise ValueError(f"Repository is not a directory: {repository}")
        if not config_file.is_file():
            raise FileNotFoundError(f"Configuration file not found: {config_file}")

        config = load_config(config_file)
        scan_started = time.monotonic()
        scan = GovernanceService().scan(repository, config_file)
        inventory_seconds = round(time.monotonic() - scan_started, 3)
        projection = build_projection(scan, config, inventory_seconds)

        job_id = (
            f"fg-{datetime.now().strftime('%Y%m%d-%H%M%S')}-"
            f"{uuid.uuid4().hex[:8]}"
        )
        job_directory = self.job_root / job_id
        job_directory.mkdir(parents=True, exist_ok=False)
        output.mkdir(parents=True, exist_ok=True)
        state_path = job_directory / "state.json"
        plan_path = job_directory / "plan.json"
        cancel_path = job_directory / "cancel.requested"
        log_path = job_directory / "worker.log"

        plan = {
            "job_id": job_id,
            "repository_path": str(repository),
            "config_path": str(config_file),
            "output_directory": str(output),
            "scan": scan.to_dict(),
            "heartbeat_interval_seconds": float(
                config.get("job", {}).get("heartbeat_interval_seconds", 5)
            ),
        }
        atomic_write_json(plan_path, plan)

        now = utc_now()
        state: dict[str, Any] = {
            "job_id": job_id,
            "status": "queued",
            "health": "starting",
            "phase": "inventory_complete",
            "repository_path": str(repository),
            "config_path": str(config_file),
            "output_directory": str(output),
            "job_directory": str(job_directory),
            "state_file": str(state_path),
            "log_file": str(log_path),
            "created_at": now,
            "started_at": None,
            "updated_at": now,
            "heartbeat_at": now,
            "completed_at": None,
            "worker_pid": None,
            "revision": 1,
            "total_items": len(scan.components),
            "processed_items": 0,
            "remaining_items": len(scan.components),
            "progress_percent": 0.0,
            "current_item": None,
            "current_item_status": "waiting_to_start",
            "last_completed_item": None,
            "recent_items": [],
            "status_counts": {
                "green": 0,
                "amber": 0,
                "yellow": 0,
                "red": 0,
                "grey": 0,
            },
            "elapsed_seconds": 0.0,
            "average_item_seconds": None,
            "eta_seconds": projection["projected_duration_seconds"],
            "eta_at": projection["projected_completion_at"],
            "projection": projection,
            "reports": {},
            "assessment_summary": None,
            "error": None,
            "cancel_requested": False,
            "cancel_file": str(cancel_path),
            "stale_after_seconds": float(
                config.get("job", {}).get("stale_after_seconds", 120)
            ),
        }
        state["summary"] = format_status_summary(state)
        atomic_write_json(state_path, state)

        process = self._launch_worker(job_directory, plan_path, state_path, log_path)
        self._processes[job_id] = process
        # Give the worker a short acknowledgement window. This catches startup
        # failures while keeping the MCP request short and non-blocking.
        deadline = time.monotonic() + 2.0
        acknowledged = False
        while time.monotonic() < deadline:
            current = read_json(state_path)
            if int(current.get("revision", 0)) > 1:
                acknowledged = True
                state = current
                break
            if process.poll() is not None:
                break
            time.sleep(0.05)
        if not acknowledged and process.poll() is not None:
            state.update(
                {
                    "status": "failed",
                    "health": "failed",
                    "phase": "startup_failed",
                    "error": (
                        f"Detached worker exited with code {process.returncode}. "
                        f"Inspect {log_path}."
                    ),
                    "completed_at": utc_now(),
                    "revision": int(state.get("revision", 0)) + 1,
                }
            )
            state["summary"] = format_status_summary(state)
            atomic_write_json(state_path, state)
        response = dict(state)
        response["worker_pid"] = process.pid
        if response.get("status") not in TERMINAL_STATUSES:
            response["health"] = (
                "worker_acknowledged" if acknowledged else "worker_launched"
            )
        if response.get("status") in TERMINAL_STATUSES:
            response["next_action"] = (
                "The assessment reached a terminal state during startup. "
                "Review the report paths or error in this response."
            )
        else:
            response["next_action"] = (
                "Call wait_for_assessment_update with this job_id and the returned "
                "revision. Repeat until status is completed, failed or cancelled."
            )
        response["summary"] = format_status_summary(response)
        if response.get("status") in TERMINAL_STATUSES:
            self.wait_for_worker_exit(job_id, timeout_seconds=2)
        return response

    def get_status(self, job_id: str) -> dict[str, Any]:
        state_path = self._job_directory(job_id) / "state.json"
        if not state_path.exists():
            raise JobNotFound(f"Assessment job not found: {job_id}")
        state = read_json(state_path)
        if state.get("status") in TERMINAL_STATUSES:
            self.wait_for_worker_exit(job_id, timeout_seconds=0.5)
        if state.get("status") not in TERMINAL_STATUSES:
            heartbeat = parse_utc(state.get("heartbeat_at"))
            stale_after = float(state.get("stale_after_seconds", 120))
            if heartbeat and (datetime.now(timezone.utc) - heartbeat).total_seconds() > stale_after:
                state["health"] = "stale"
                state["health_message"] = (
                    "The heartbeat is stale. Inspect worker.log and the worker PID."
                )
            else:
                state["health"] = "healthy"
        state["summary"] = format_status_summary(state)
        return state

    def wait_for_update(
        self,
        job_id: str,
        after_revision: int = 0,
        timeout_seconds: float = 20,
    ) -> dict[str, Any]:
        timeout = max(1.0, min(float(timeout_seconds), 25.0))
        deadline = time.monotonic() + timeout
        while True:
            state = self.get_status(job_id)
            if (
                int(state.get("revision", 0)) > int(after_revision)
                or state.get("status") in TERMINAL_STATUSES
                or time.monotonic() >= deadline
            ):
                state["wait_timed_out"] = (
                    int(state.get("revision", 0)) <= int(after_revision)
                    and state.get("status") not in TERMINAL_STATUSES
                )
                return state
            time.sleep(0.5)

    def cancel_job(self, job_id: str) -> dict[str, Any]:
        job_directory = self._job_directory(job_id)
        state = self.get_status(job_id)
        if state.get("status") in TERMINAL_STATUSES:
            return state
        (job_directory / "cancel.requested").write_text(
            f"requested_at={utc_now()}\n", encoding="utf-8"
        )
        state["cancel_requested"] = True
        state["current_item_status"] = "cancellation_requested"
        state["summary"] = format_status_summary(state)
        return state

    def list_jobs(self, limit: int = 20) -> dict[str, Any]:
        if not self.job_root.exists():
            return {"jobs": [], "count": 0}
        jobs: list[dict[str, Any]] = []
        directories = sorted(
            (path for path in self.job_root.iterdir() if path.is_dir()),
            key=lambda path: path.name,
            reverse=True,
        )
        for directory in directories[: max(1, min(int(limit), 100))]:
            state_path = directory / "state.json"
            if not state_path.exists():
                continue
            try:
                state = self.get_status(directory.name)
            except (OSError, ValueError, json.JSONDecodeError):
                continue
            jobs.append(
                {
                    "job_id": state.get("job_id"),
                    "status": state.get("status"),
                    "phase": state.get("phase"),
                    "progress_percent": state.get("progress_percent"),
                    "processed_items": state.get("processed_items"),
                    "total_items": state.get("total_items"),
                    "eta_seconds": state.get("eta_seconds"),
                    "repository_path": state.get("repository_path"),
                    "updated_at": state.get("updated_at"),
                    "summary": state.get("summary"),
                }
            )
        return {"jobs": jobs, "count": len(jobs)}

    def wait_for_worker_exit(
        self, job_id: str, timeout_seconds: float = 2
    ) -> bool:
        """Reap a worker launched by this manager and release its log handle."""
        process = self._processes.get(job_id)
        if process is None:
            return True
        try:
            process.wait(timeout=max(0.0, float(timeout_seconds)))
        except subprocess.TimeoutExpired:
            return False
        self._processes.pop(job_id, None)
        return True

    def _job_directory(self, job_id: str) -> Path:
        if not JOB_ID_PATTERN.match(job_id):
            raise ValueError(f"Invalid assessment job ID: {job_id}")
        return self.job_root / job_id

    @staticmethod
    def _launch_worker(
        job_directory: Path,
        plan_path: Path,
        state_path: Path,
        log_path: Path,
    ) -> subprocess.Popen[bytes]:
        command = [
            sys.executable,
            "-m",
            "framework_governance.job_worker",
            "--job-directory",
            str(job_directory),
            "--plan-file",
            str(plan_path),
            "--state-file",
            str(state_path),
        ]
        kwargs: dict[str, Any] = {
            "cwd": str(Path.cwd()),
            "stdin": subprocess.DEVNULL,
            "close_fds": True,
        }
        if os.name == "nt":
            kwargs["creationflags"] = (
                subprocess.CREATE_NEW_PROCESS_GROUP
                | subprocess.DETACHED_PROCESS
                | subprocess.CREATE_NO_WINDOW
            )
        else:
            kwargs["start_new_session"] = True

        with log_path.open("ab") as log_handle:
            process = subprocess.Popen(
                command,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                **kwargs,
            )
        return process


class JobStateWriter:
    def __init__(self, state_path: Path, heartbeat_interval_seconds: float = 5):
        self.state_path = state_path
        self.state = read_json(state_path)
        self.interval = max(1.0, float(heartbeat_interval_seconds))
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.started_epoch: float | None = None
        self.ema_item_seconds: float | None = None
        self.heartbeat_thread: threading.Thread | None = None

    def start(self) -> None:
        self.started_epoch = time.time()
        self.update(
            status="running",
            health="healthy",
            phase="scas_lookup",
            worker_pid=os.getpid(),
            started_at=utc_now(),
            current_item_status="preparing_catalog",
        )
        self.heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop,
            name="governance-heartbeat",
            daemon=True,
        )
        self.heartbeat_thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        if self.heartbeat_thread:
            self.heartbeat_thread.join(timeout=self.interval + 1)

    def update(self, **fields: Any) -> dict[str, Any]:
        with self.lock:
            self.state.update(fields)
            self._update_temporal_fields()
            self.state["revision"] = int(self.state.get("revision", 0)) + 1
            now = utc_now()
            self.state["updated_at"] = now
            self.state["heartbeat_at"] = now
            self.state["summary"] = format_status_summary(self.state)
            atomic_write_json(self.state_path, self.state)
            return dict(self.state)

    def handle_event(self, event: dict[str, Any]) -> None:
        kind = event.get("event")
        if kind == "item_started":
            component = event["component"]
            self.update(
                phase="scas_lookup",
                current_item={
                    "index": event["index"],
                    "name": component.get("name"),
                    "version": component.get("version"),
                    "ecosystem": component.get("ecosystem"),
                    "category": component.get("category"),
                    "scope": component.get("scope"),
                },
                current_item_status="querying_scas",
            )
            return
        if kind == "item_completed":
            finding = event["finding"]
            status = str(finding.get("status", "grey"))
            duration = max(0.0, float(event.get("duration_seconds", 0)))
            self.ema_item_seconds = (
                duration
                if self.ema_item_seconds is None
                else (0.3 * duration) + (0.7 * self.ema_item_seconds)
            )
            counts = dict(self.state.get("status_counts", {}))
            counts[status] = int(counts.get(status, 0)) + 1
            component = event["component"]
            completed_item = {
                "index": event["index"],
                "name": component.get("name"),
                "version": component.get("version"),
                "ecosystem": component.get("ecosystem"),
                "status": status,
                "policy_rule": finding.get("policy_rule"),
                "duration_seconds": round(duration, 3),
            }
            recent = list(self.state.get("recent_items", []))
            recent.append(completed_item)
            recent = recent[-20:]
            total = int(event.get("total", self.state.get("total_items", 0)))
            processed = int(event["index"])
            self.update(
                processed_items=processed,
                remaining_items=max(0, total - processed),
                progress_percent=round((100 * processed / total) if total else 100, 2),
                current_item_status=f"completed_{status}",
                last_completed_item=completed_item,
                recent_items=recent,
                status_counts=counts,
                average_item_seconds=round(self.ema_item_seconds, 3),
            )
            return
        if kind == "report_started":
            self.update(
                phase="report_generation",
                current_item=None,
                current_item_status="generating_reports",
            )
            return
        if kind == "report_completed":
            self.update(
                phase="report_generation",
                current_item_status="reports_written",
                reports=event.get("reports", {}),
            )

    def _heartbeat_loop(self) -> None:
        while not self.stop_event.wait(self.interval):
            self.update()

    def _update_temporal_fields(self) -> None:
        if self.started_epoch is None:
            return
        elapsed = max(0.0, time.time() - self.started_epoch)
        self.state["elapsed_seconds"] = round(elapsed, 1)
        remaining = int(self.state.get("remaining_items", 0))
        seconds_per_item = self.ema_item_seconds
        if seconds_per_item is None:
            seconds_per_item = float(
                self.state.get("projection", {}).get(
                    "estimated_seconds_per_item", 2.0
                )
            )
        report_overhead = float(
            self.state.get("projection", {}).get(
                "estimated_report_overhead_seconds", 5.0
            )
        )
        eta_seconds = max(0.0, (seconds_per_item * remaining) + report_overhead)
        if self.state.get("phase") == "report_generation":
            eta_seconds = report_overhead
        if self.state.get("status") in TERMINAL_STATUSES:
            eta_seconds = 0.0
        self.state["eta_seconds"] = round(eta_seconds, 1)
        self.state["eta_at"] = (
            datetime.now(timezone.utc) + timedelta(seconds=eta_seconds)
        ).isoformat()


def build_projection(
    scan: ScanResult, config: dict[str, Any], inventory_seconds: float
) -> dict[str, Any]:
    job_config = config.get("job", {})
    catalog_config = config.get("catalog", {})
    total = len(scan.components)
    estimated_per_item = float(job_config.get("estimated_seconds_per_item", 2.0))
    report_overhead = float(job_config.get("estimated_report_overhead_seconds", 5.0))
    timeout = float(catalog_config.get("timeout_seconds", 30))
    version_fallback = bool(catalog_config.get("version_fallback", True))
    has_maven_coordinate = any(
        component.ecosystem.lower() == "maven" and ":" in component.name
        for component in scan.components
    )
    name_search_stages = (
        4
        if has_maven_coordinate
        and bool(catalog_config.get("maven_coordinate_fallback", True))
        else 1
    )
    maximum_requests = name_search_stages * (2 if version_fallback else 1)
    expected = inventory_seconds + (total * estimated_per_item) + report_overhead
    low = (
        inventory_seconds
        + (total * max(0.1, estimated_per_item * 0.5))
        + report_overhead
    )
    high_per_item = min(timeout * maximum_requests, max(estimated_per_item * 3, 1))
    high = inventory_seconds + (total * high_per_item) + report_overhead

    category_counts = Counter(component.category for component in scan.components)
    ecosystem_counts = Counter(component.ecosystem for component in scan.components)
    scope_counts = Counter(component.scope for component in scan.components)
    limit = max(10, min(int(job_config.get("projection_list_limit", 100)), 500))

    def item(component: Component) -> dict[str, Any]:
        return {
            "name": component.name,
            "version": component.version,
            "ecosystem": component.ecosystem,
            "scope": component.scope,
        }

    frameworks = [item(value) for value in scan.components if value.category == "framework"]
    libraries = [item(value) for value in scan.components if value.category == "library"]
    runtimes = [item(value) for value in scan.components if value.category == "runtime"]
    base_images = [item(value) for value in scan.components if value.category == "base-image"]
    completion = datetime.now(timezone.utc) + timedelta(seconds=expected)
    return {
        "inventory_scan_seconds": inventory_seconds,
        "total_items": total,
        "category_counts": dict(sorted(category_counts.items())),
        "ecosystem_counts": dict(sorted(ecosystem_counts.items())),
        "scope_counts": dict(sorted(scope_counts.items())),
        "frameworks_found": frameworks[:limit],
        "frameworks_total": len(frameworks),
        "libraries_found": libraries[:limit],
        "libraries_total": len(libraries),
        "runtimes_found": runtimes[:limit],
        "runtimes_total": len(runtimes),
        "base_images_found": base_images[:limit],
        "base_images_total": len(base_images),
        "lists_truncated": any(
            len(values) > limit
            for values in (frameworks, libraries, runtimes, base_images)
        ),
        "projection_list_limit": limit,
        "estimated_seconds_per_item": estimated_per_item,
        "estimated_report_overhead_seconds": report_overhead,
        "projected_duration_seconds": round(expected, 1),
        "projected_duration_low_seconds": round(low, 1),
        "projected_duration_high_seconds": round(high, 1),
        "projected_completion_at": completion.isoformat(),
        "maximum_scas_requests_per_item": maximum_requests,
        "maximum_name_search_stages": name_search_stages,
        "projection_note": (
            "Initial estimate uses configured per-item timing. ETA is recalculated "
            "from observed item durations throughout the assessment."
        ),
    }


def format_status_summary(state: dict[str, Any]) -> str:
    status = str(state.get("status", "unknown")).upper()
    percent = float(state.get("progress_percent", 0))
    processed = int(state.get("processed_items", 0))
    total = int(state.get("total_items", 0))
    remaining = int(state.get("remaining_items", max(0, total - processed)))
    eta = format_duration(state.get("eta_seconds"))
    elapsed = format_duration(state.get("elapsed_seconds"))
    current = state.get("current_item") or {}
    current_text = "none"
    if current:
        version = current.get("version") or "unresolved"
        current_text = f"{current.get('name')} {version}"
    return (
        f"{status} | {percent:.2f}% | {processed}/{total} completed | "
        f"{remaining} remaining | elapsed {elapsed} | ETA {eta} | "
        f"Current: {current_text} "
        f"[{state.get('current_item_status', 'unknown')}]"
    )


def format_duration(value: Any) -> str:
    if value is None:
        return "calculating"
    seconds = max(0, int(float(value)))
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes:02d}m {seconds:02d}s"
    if minutes:
        return f"{minutes}m {seconds:02d}s"
    return f"{seconds}s"


def scan_result_from_dict(data: dict[str, Any]) -> ScanResult:
    components = [Component(**value) for value in data.get("components", [])]
    return ScanResult(
        repository=str(data["repository"]),
        components=components,
        warnings=list(data.get("warnings", [])),
        scanned_at=str(data.get("scanned_at", utc_now())),
    )


def atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, indent=2), encoding="utf-8")
    last_error: PermissionError | None = None
    for attempt in range(50):
        try:
            os.replace(temporary, path)
            return
        except PermissionError as exc:
            # Windows may briefly deny replacement while antivirus software
            # or another process has the previous state file open.
            last_error = exc
            if attempt == 49:
                break
            time.sleep(0.02)
    if last_error:
        raise last_error


def read_json(path: Path) -> dict[str, Any]:
    last_error: PermissionError | FileNotFoundError | json.JSONDecodeError | None = None
    for attempt in range(50):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (PermissionError, FileNotFoundError, json.JSONDecodeError) as exc:
            # Atomic replacement can still present a transient sharing
            # violation on Windows. Retry for up to roughly one second.
            last_error = exc
            if attempt == 49:
                break
            time.sleep(0.02)
    if last_error:
        raise last_error
    raise RuntimeError(f"Unable to read JSON file: {path}")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_utc(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None
