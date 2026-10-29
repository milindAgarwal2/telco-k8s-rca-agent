"""Incident capture: record incidents as labelable JSONL for later eval.

Each captured incident is one JSON line with three layers:
  * ``input``  — the reproducible case: the alert, the gathered evidence (with
                 timestamps/citations), and optionally a graph-neighborhood
                 snapshot. This is what lets a record be REPLAYED by the eval
                 harness without a live cluster.
  * ``output`` — what the agent concluded: ranked hypotheses (cause, confidence,
                 evidence chain, citations), blast radius, upstream.
  * ``labels`` — EMPTY at capture time; a human fills ``gold_causes`` and
                 ``hypothesis_verdicts`` later to compute precision/recall.

OFF by default: nothing is written unless ``settings.incident_capture_path`` is
set (a deploy-time env var, RCA_INCIDENT_CAPTURE_PATH). See eval/LABELING.md for
the labeling process.

The writer is best-effort and NEVER raises into the caller: a capture failure
must not break incident detection. Records include real log/object text from the
monitored namespace, so the file is SENSITIVE (see redact option).
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("rca_agent")

SCHEMA_VERSION = "1"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _redact_evidence(evidence: list[dict], redact_logs: bool) -> list[dict]:
    """Optionally drop raw log bodies (keep category/resource/timestamp/citations)
    so a capture file need not carry full log text from a production namespace."""
    if not redact_logs:
        return evidence
    out = []
    for e in evidence:
        e = dict(e)
        if e.get("category") == "log":
            e["summary"] = "<redacted log line>"
            e["citations"] = [
                {**c, "detail": "<redacted>"} for c in e.get("citations", [])
            ]
        out.append(e)
    return out


def build_record(report, *, source: str, graph=None, redact_logs: bool = False,
                 include_graph: bool = True, graph_radius: int = 2) -> dict:
    """Build one capture record (dict) from an IncidentReport.

    ``graph`` is the current DependencyGraph (for the neighborhood snapshot);
    pass None to skip. ``source`` is "event_watcher" or "webhook".
    """
    d = report.model_dump(mode="json")

    neighborhood = None
    if include_graph and graph is not None:
        anchor = d.get("affected_anchor") or d.get("affected_resource")
        if anchor:
            try:
                neighborhood = graph.neighborhood(anchor, radius=graph_radius)
            except Exception:  # noqa: BLE001 - snapshot is best-effort
                neighborhood = None

    return {
        "schema_version": SCHEMA_VERSION,
        "incident_id": d.get("incident_id"),
        "captured_at": _now_iso(),
        "source": source,
        "namespace": d.get("namespace"),
        # ---- INPUT: the reproducible case ----
        "input": {
            "symptom": d.get("symptom"),
            "affected_resource": d.get("affected_resource"),
            "affected_anchor": d.get("affected_anchor"),
            "anchor_kind": d.get("anchor_kind"),
            "affected_pods": d.get("affected_pods", []),
            "detected_at": d.get("detected_at"),
            "evidence": _redact_evidence(d.get("evidence", []), redact_logs),
            "graph_neighborhood": neighborhood,
        },
        # ---- OUTPUT: what the agent concluded (to be scored) ----
        "output": {
            "severity": d.get("severity"),
            "status": d.get("status"),
            "resolved_at": d.get("resolved_at"),
            "hypotheses": d.get("hypotheses", []),
            "blast_radius": d.get("blast_radius", []),
            "upstream_unhealthy": d.get("upstream_unhealthy", []),
            "related_incidents": d.get("related_incidents", []),
            "reasoning_mode": d.get("reasoning_mode"),
        },
        # ---- LABELS: empty now; a human fills these later ----
        "labels": {
            "status": "unlabeled",            # unlabeled | labeled | skipped
            "gold_causes": [],                # the TRUE root cause(s) as text
            "hypothesis_verdicts": [],        # [{cause, verdict: TP|FP|tolerated}]
            "is_real_incident": None,         # true | false (false = should stay quiet)
            "labeler": "",
            "labeled_at": "",
            "notes": "",
        },
    }


class IncidentCaptureWriter:
    """Appends incident capture records to a JSONL file (bounded, best-effort).

    Disabled when ``path`` is falsy — ``record()`` becomes a no-op, so callers
    can always call it unconditionally.
    """

    def __init__(self, path: str | None, *, redact_logs: bool = False,
                 include_graph: bool = True, max_records: int = 5000,
                 graph_radius: int = 2) -> None:
        self.path = path
        self.redact_logs = redact_logs
        self.include_graph = include_graph
        self.max_records = max(1, max_records)
        self.graph_radius = graph_radius

    @property
    def enabled(self) -> bool:
        return bool(self.path)

    def record(self, report, *, source: str, graph=None) -> bool:
        """Capture one incident. Returns True if written. Never raises."""
        if not self.enabled:
            return False
        try:
            rec = build_record(
                report, source=source, graph=graph,
                redact_logs=self.redact_logs, include_graph=self.include_graph,
                graph_radius=self.graph_radius)
            p = Path(self.path)
            p.parent.mkdir(parents=True, exist_ok=True)
            with p.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, default=str) + "\n")
            self._enforce_cap(p)
            return True
        except Exception:  # capture must never break detection
            logger.exception("incident capture failed (path=%s); continuing", self.path)
            return False

    def _enforce_cap(self, p: Path) -> None:
        """Keep only the most recent ``max_records`` lines (rolling window)."""
        try:
            with p.open("r", encoding="utf-8") as fh:
                lines = fh.readlines()
            if len(lines) <= self.max_records:
                return
            keep = lines[-self.max_records:]
            # Atomic rewrite so a crash can't truncate the file.
            fd, tmp = tempfile.mkstemp(dir=str(p.parent), suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.writelines(keep)
            os.replace(tmp, p)
        except Exception:
            logger.exception("incident capture cap enforcement failed; continuing")


def load_records(path: str) -> list[dict]:
    """Load capture records from a JSONL file (for the eval harness / labeling)."""
    out: list[dict] = []
    p = Path(path)
    if not p.exists():
        return out
    with p.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out
