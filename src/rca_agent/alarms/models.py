"""Pydantic models for the potential-alarms feature.

These are CANDIDATE alarm associations for a pod, drawn from the curated
pod-alarm mapping workbook -- alarms that *could have been* raised for the pod.
They are never observed, confirmed, or active alarms.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class CandidateAlarm(BaseModel):
    """One candidate alarm association for a pod, drawn from one row of the
    'Pod Alarm Mapping' sheet. A CANDIDATE that could have been raised -- never
    an observed/confirmed/active alarm."""

    alarm_name: str
    scope: str = ""              # "Individual pod" | "Workload (...)" | "Microservice/service"
    severity: str = ""
    raise_condition: str = ""    # "Condition that raises alarm"
    clear_condition: str = ""    # "Clear/reset condition"
    applicability: str = ""      # applicability / qualification (verbatim)
    mapping_basis: str = ""      # "Exact pod name ..." (Direct) | "Conditional candidate ..."
    source_citation: str = ""    # the workbook 'Source in PDF' value, surfaced verbatim
    workload_key: str = ""       # 'Name-derived workload/service key' (optional)

    @property
    def is_direct(self) -> bool:
        """True when the mapping basis indicates an exact pod-name/direct
        mapping (basis contains 'exact pod name'). Used only for Direct-before-
        Conditional ordering -- it does not change or reclassify any value."""
        return "exact pod name" in self.mapping_basis.lower()


class PotentialAlarms(BaseModel):
    """The per-pod answer: candidate alarms for a pod. ``mapped=False`` means the
    pod is not in the workbook (reported as UNKNOWN, never guessed). These are
    candidate alarms that could have been raised -- never observed, confirmed,
    or active."""

    pod: str
    mapped: bool = False
    alarms: list[CandidateAlarm] = Field(default_factory=list)

    def summary_line(self) -> str:
        """One ASCII-safe human sentence (<= 200 chars) for evidence/pptx/UI.

        The pod name is embedded from arbitrary input, so it is ASCII-folded
        (non-ASCII replaced with '?') and length-capped before composition,
        keeping the whole sentence ASCII-encodable and <= 200 chars for any pod
        name or alarm count while preserving the fixed wording (including the
        UNKNOWN reason) intact."""
        pod = self.pod.encode("ascii", "replace").decode("ascii")
        # Cap the variable pod name so the fixed wording is never truncated
        # and the whole sentence stays <= 200 chars. The longest template adds
        # ~101 fixed chars (incl. a multi-digit count), so a 95-char pod keeps
        # the total within bound.
        if len(pod) > 95:
            pod = pod[:92] + "..."
        if not self.mapped:
            return (f"Potential alarms UNKNOWN for {pod} "
                    f"(pod not mapped in the pod-alarm workbook)")
        return (
            f"{pod} has {len(self.alarms)} candidate potential alarm(s) "
            f"that could have been raised (candidates, not confirmed/active)"
        )
