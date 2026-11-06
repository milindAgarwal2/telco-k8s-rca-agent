"""Build a SYNTHETIC pod-to-alarm mapping fixture for tests.

Deliberately uses only representative, non-sensitive names (generic Ericsson
service names, not per-tenant data) and a small subset, so no live inventory is
committed to git. Reproduces the real workbook's shape that the potential-alarm
loader/index tests assert:

  - sheet "Pod Alarm Mapping"
  - row 1 title, row 2 disclaimer, row 3 header (the 10 columns in design order)
  - data from row 4: several pods with multiple alarm rows mixing Direct and
    Conditional mapping bases
  - one row with a blank ``Pod name`` (exercises the loader's skip path)
  - one row with an empty ``Source in PDF`` (exercises citation suppression)

Run once to (re)generate the fixture:
    .venv/bin/python tests/fixtures/make_pod_alarm_fixture.py
"""
from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook

OUT = Path(__file__).parent / "pod_alarm_mapping_sample.xlsx"

_SHEET = "Pod Alarm Mapping"
_TITLE = "Individual Pod -> Alarm Mapping"
_DISCLAIMER = (
    "Candidate associations from a reviewed mapping -- NOT observed, confirmed, "
    "or active alarms."
)

# The 10 columns, in design order (design.md "Workbook structure (verified)").
_HEADER = [
    "Pod name",
    "Name-derived workload/service key",
    "Alarm name",
    "Alarm scope",
    "Severity in PDF",
    "Condition that raises alarm",
    "Clear/reset condition",
    "Applicability / qualification",
    "Mapping basis",
    "Source in PDF",
]

# Mapping-basis prefixes the loader/index classify on ("exact pod name" => Direct).
_DIRECT = "Exact pod name match to a pod-level alarm."
_CONDITIONAL = (
    "Conditional candidate from name-derived workload/service; depends on live "
    "cluster facts and alarm configuration."
)

# Each tuple is one data row: all 10 columns in design order.
# Several pods, multiple alarm rows per pod, a mix of Direct/Conditional bases.
_ROWS: list[list[str]] = [
    # eric-pc-vpn-gateway-forwarder: two Direct, one Conditional.
    [
        "eric-pc-vpn-gateway-forwarder-85c5f46fc5-9zspm",
        "pc-vpn-gateway-forwarder",
        "Pod Not Ready",
        "Individual pod",
        "Major",
        "Readiness probe fails for longer than the configured threshold.",
        "Readiness probe succeeds and the pod reports Ready.",
        "",
        _DIRECT,
        'Pod related Alarms.pdf -- "Pod Not Ready"',
    ],
    [
        "eric-pc-vpn-gateway-forwarder-85c5f46fc5-9zspm",
        "pc-vpn-gateway-forwarder",
        "Container Restarting Repeatedly",
        "Individual pod",
        "Critical",
        "Container restart count increases repeatedly within a short window.",
        "Restart count stabilizes and the container stays running.",
        "",
        _DIRECT,
        'Pod related Alarms.pdf -- "CrashLoopBackOff"',
    ],
    [
        "eric-pc-vpn-gateway-forwarder-85c5f46fc5-9zspm",
        "pc-vpn-gateway-forwarder",
        "Workload Memory Pressure",
        "Workload (container usage across workload)",
        "Warning",
        "Aggregate workload memory usage exceeds the configured limit.",
        "Workload memory usage returns below the limit.",
        (
            "Applies only when the workload has a memory limit configured and "
            "resource metrics are available."
        ),
        _CONDITIONAL,
        'Workload related Alarms.pdf -- "Memory Pressure"',
    ],
    # eric-pc-routing-engine: one Direct, one Conditional, and one Direct row
    # with an EMPTY Source in PDF (exercises citation suppression downstream).
    [
        "eric-pc-routing-engine-5d4d546b64-bh9px",
        "pc-routing-engine",
        "Pod Not Ready",
        "Individual pod",
        "Major",
        "Readiness probe fails for longer than the configured threshold.",
        "Readiness probe succeeds and the pod reports Ready.",
        "",
        _DIRECT,
        'Pod related Alarms.pdf -- "Pod Not Ready"',
    ],
    [
        "eric-pc-routing-engine-5d4d546b64-bh9px",
        "pc-routing-engine",
        "Service Endpoint Unavailable",
        "Microservice/service",
        "Major",
        "No ready endpoints back the service for the affected microservice.",
        "At least one ready endpoint backs the service again.",
        (
            "Applies only when the pod backs a Service with no other ready "
            "endpoints."
        ),
        _CONDITIONAL,
        'Service related Alarms.pdf -- "Endpoint Unavailable"',
    ],
    [
        "eric-pc-routing-engine-5d4d546b64-bh9px",
        "pc-routing-engine",
        "Liveness Probe Failing",
        "Individual pod",
        "Minor",
        "Liveness probe fails intermittently.",
        "Liveness probe succeeds consistently.",
        "",
        _DIRECT,
        "",  # empty Source in PDF -- suppressed when surfaced (R4 AC2).
    ],
    # eric-sec-certm: single Direct row.
    [
        "eric-sec-certm-7d8f9dfc56-f7rpv",
        "sec-certm",
        "Certificate Expiring Soon",
        "Individual pod",
        "Warning",
        "A managed certificate approaches its expiry threshold.",
        "The certificate is renewed before expiry.",
        "",
        _DIRECT,
        'Pod related Alarms.pdf -- "Certificate Expiring"',
    ],
    # A row with a BLANK Pod name -- the loader must skip it (R1 AC3).
    [
        "",
        "orphan-key",
        "Should Be Skipped",
        "Individual pod",
        "Major",
        "This row has no pod name and must not produce a candidate alarm.",
        "n/a",
        "",
        _DIRECT,
        'Pod related Alarms.pdf -- "Should Be Skipped"',
    ],
]


def main() -> None:
    wb = Workbook()

    ws = wb.active
    ws.title = _SHEET

    # Row 1: title. Row 2: disclaimer. Row 3: the real header. Data from row 4.
    ws.append([_TITLE])
    ws.append([_DISCLAIMER])
    ws.append(_HEADER)
    for row in _ROWS:
        ws.append(row)

    wb.save(str(OUT))
    print("wrote", OUT)


if __name__ == "__main__":
    main()
