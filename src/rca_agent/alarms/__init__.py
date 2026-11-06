"""Potential alarms: map a pod to the candidate alarms it could have raised.

Scoped, deterministic feature: it reports ONLY what the curated 'Pod Alarm
Mapping' workbook supports directly -- the candidate alarms associated with a
pod. ``mapped=False`` means the pod is not in the workbook (reported as UNKNOWN,
never guessed). These are CANDIDATES that could have been raised, never a claim
that an alarm actually fired.

Read-only and deterministic: the mapping is curated data, never an LLM guess.
"""
from __future__ import annotations

from rca_agent.alarms.index import PotentialAlarmsIndex, load_potential_alarms_index
from rca_agent.alarms.models import CandidateAlarm, PotentialAlarms

__all__ = [
    "CandidateAlarm",
    "PotentialAlarms",
    "PotentialAlarmsIndex",
    "load_potential_alarms_index",
]
