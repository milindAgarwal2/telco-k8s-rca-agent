"""Build a SYNTHETIC service-area mapping fixture for tests.

Deliberately uses only representative, non-sensitive names (the VPN Gateway
component names are generic Ericsson service names, not per-tenant data) and a
small subset, so no live cluster inventory is committed to git. Reproduces the
two sheets and the exact values the impact tests assert:
  forwarder pod -> PC VPN Gateway Forwarder / VPN Gateway / section 18 / High,
  component siblings 2, service-area pods 22.

Run once to (re)generate the fixture:
    .venv/bin/python tests/fixtures/make_service_area_fixture.py
"""
from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook

OUT = Path(__file__).parent / "service_area_mapping_sample.xlsx"

# 22 synthetic VPN Gateway pods (section 18), incl. 2 forwarder instances.
VPN_PODS = [
    "eric-pc-networking-cm-agent-f4c55cc5c-9kzlg",
    "eric-pc-networking-cm-agent-f4c55cc5c-k48k6",
    "eric-pc-routing-aggregator-845f686767-brmnp",
    "eric-pc-routing-aggregator-845f686767-fn6lc",
    "eric-pc-routing-engine-5d4d546b64-bh9px",
    "eric-pc-routing-engine-5d4d546b64-fn7xh",
    "eric-pc-routing-engine-api-7c6b6456ff-2mw52",
    "eric-pc-routing-engine-api-7c6b6456ff-c528b",
    "eric-pc-sm-diameter-7bdcb67999-7tcd2",
    "eric-pc-sm-diameter-7bdcb67999-grd7f",
    "eric-pc-sm-sgw-session-7d89f7cd6b-25r4z",
    "eric-pc-sm-sgw-session-7d89f7cd6b-9t7fk",
    "eric-pc-sm-smf-pgw-session-946b66b96-c2rpf",
    "eric-pc-sm-smf-pgw-session-946b66b96-dxspq",
    "eric-pc-sm-udp-forwarder-769cc57fff-hwvvv",
    "eric-pc-sm-udp-forwarder-769cc57fff-v589r",
    "eric-pc-up-timer-wheel-6f56576db5-2n4wq",
    "eric-pc-up-timer-wheel-6f56576db5-d29gh",
    "eric-pc-vpn-gateway-forwarder-85c5f46fc5-9zspm",
    "eric-pc-vpn-gateway-forwarder-85c5f46fc5-cww6v",
    "eric-tm-partition-distributor-7877b8f785-6658n",
    "eric-tm-partition-distributor-7877b8f785-mv45c",
]
CERT_PODS = ["eric-sec-certm-7d8f9dfc56-f7rpv"]  # a single-instance area

# Which Pod-map component each pod maps to (so sibling counts are exact).
COMPONENT = {
    "eric-pc-vpn-gateway-forwarder-85c5f46fc5-9zspm": "PC VPN Gateway Forwarder",
    "eric-pc-vpn-gateway-forwarder-85c5f46fc5-cww6v": "PC VPN Gateway Forwarder",
    "eric-sec-certm-7d8f9dfc56-f7rpv": "Certificate Management",
}


def main() -> None:
    wb = Workbook()

    # Sheet 1: 20-section map
    sm = wb.active
    sm.title = "20-section map"
    sm.append(["PDF §", "PDF section / service group",
               "Service/component(s) described",
               "Pods mapped directly to this section (exact names)",
               "Related pods / cross-section links (exact names)",
               "Coverage notes"])
    sm.append([18, "VPN Gateway",
               "Networking CM Agent; PC VPN Gateway Forwarder; Routing Engine",
               "\n".join(VPN_PODS), "—", "Synthetic fixture."])
    sm.append([8, "Certificate Management", "Certificate Management",
               "\n".join(CERT_PODS), "—", "Synthetic fixture (single instance)."])

    # Sheet 2: Pod map
    pm = wb.create_sheet("Pod map")
    pm.append(["Pod name (from uploaded list)", "Mapped service/component",
               "PDF section(s)", "Relationship type", "Confidence",
               "Mapping basis / caveat",
               "Probable alerts (numeric ID — specific problem)"])
    for pod in VPN_PODS:
        comp = COMPONENT.get(pod, pod.replace("eric-pc-", "").replace("eric-tm-", "")
                             .rsplit("-", 2)[0])
        pm.append([pod, comp, "§18 VPN Gateway", "Direct component match",
                   "High", "Synthetic fixture.", "n/a"])
    for pod in CERT_PODS:
        pm.append([pod, "Certificate Management", "§8 Certificate Management",
                   "Direct component match", "High", "Synthetic fixture.", "n/a"])

    wb.save(str(OUT))
    print("wrote", OUT)


if __name__ == "__main__":
    main()
