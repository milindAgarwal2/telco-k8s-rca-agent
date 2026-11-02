"""Pydantic models for the service-area impact feature."""
from __future__ import annotations

from pydantic import BaseModel, Field


class ServiceArea(BaseModel):
    """One numbered service group from the mapping workbook's section map."""

    section: str  # PDF section number, kept as a string ("18", "13", ...)
    service: str  # e.g. "VPN Gateway"
    components: str = ""  # semicolon-separated component names from the PDF
    direct_pods: list[str] = Field(default_factory=list)  # exact pod names


class ServiceAreaImpact(BaseModel):
    """The per-pod answer: which service area a pod belongs to, with factual
    redundancy counts. ``mapped=False`` means the pod is not in the workbook
    (reported as UNKNOWN rather than guessed)."""

    pod: str
    mapped: bool = False
    component: str = ""          # "PC VPN Gateway Forwarder"
    service_area: str = ""       # "VPN Gateway"
    section: str = ""            # "18"
    relationship_type: str = ""  # "Direct component match", ...
    confidence: str = "Unknown"  # High / Medium / Low / Unknown
    component_sibling_count: int = 0   # pods sharing this component (incl. self)
    service_area_pod_count: int = 0    # direct pods in the whole service area

    def summary_line(self) -> str:
        """One ASCII-safe human sentence for evidence/pptx/UI."""
        if not self.mapped:
            return (f"Service area UNKNOWN for {self.pod} "
                    f"(pod not mapped in the service-area workbook)")
        return (
            f"Affected pod belongs to service area '{self.service_area}' "
            f"(section {self.section}); component '{self.component}' has "
            f"{self.component_sibling_count} pod(s), the service area has "
            f"{self.service_area_pod_count} pod(s) [confidence: {self.confidence}]"
        )
