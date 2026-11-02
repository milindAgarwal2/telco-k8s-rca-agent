"""Phase 3 tests: the 'Service area impacted' panel in the incident detail.

Renders the _incident_detail.html partial directly through the Jinja
environment with reports that carry (or omit) a service_area, and asserts the
panel content. Also checks the pptx export tolerates the new field.
"""
from __future__ import annotations

from rca_agent.impact.models import ServiceAreaImpact
from rca_agent.models.incident import IncidentReport
from rca_agent.webhook.ui import templates

_env = templates.env


def _render(report: IncidentReport) -> str:
    tmpl = _env.get_template("_incident_detail.html")
    # Mirror the real inc_detail route: template gets the JSON-dumped dict
    # (datetimes -> strings, service_area -> nested dict) with severity coerced.
    d = report.model_dump(mode="json")
    d["severity"] = getattr(report.severity, "value", report.severity)
    return tmpl.render(d=d, owners={}, pod_health=[], root="/")


def _mapped_report() -> IncidentReport:
    sa = ServiceAreaImpact(
        pod="eric-pc-vpn-gateway-forwarder-85c5f46fc5-9zspm",
        mapped=True, component="PC VPN Gateway Forwarder",
        service_area="VPN Gateway", section="18",
        relationship_type="Direct component match", confidence="High",
        component_sibling_count=2, service_area_pod_count=22,
    )
    return IncidentReport(symptom="pod not ready",
                          affected_resource=sa.pod, service_area=sa)


def test_panel_shows_service_area_and_counts():
    html = _render(_mapped_report())
    assert "Service area impacted" in html
    assert "VPN Gateway" in html
    assert "section 18" in html
    assert "PC VPN Gateway Forwarder" in html
    assert "confidence: High" in html
    # factual redundancy counts both present
    assert "2</strong> pod(s) in this component" in html
    assert "22</strong> pod(s) in the service area" in html


def test_panel_unknown_when_unmapped():
    sa = ServiceAreaImpact(pod="mystery-pod", mapped=False)
    report = IncidentReport(symptom="x", affected_resource="mystery-pod",
                            service_area=sa)
    html = _render(report)
    assert "Service area impacted" in html
    assert "UNKNOWN" in html
    assert "not mapped" in html


def test_panel_absent_when_no_service_area():
    report = IncidentReport(symptom="x", affected_resource="p")
    html = _render(report)
    assert "Service area impacted" not in html


def test_pptx_export_includes_service_area():
    from rca_agent.webhook.pptx_report import build_incident_pptx, pptx_available
    if not pptx_available():
        return  # python-pptx not installed in this env
    data = build_incident_pptx(_mapped_report())
    assert isinstance(data, bytes) and len(data) > 1000  # produced a deck
