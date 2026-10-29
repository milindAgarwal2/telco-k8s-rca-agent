"""Synthetic fault-injection + accuracy harness (assessment point #9).

Offline and cluster-free: each :class:`FaultCase` builds a fake-kube fixture
with a KNOWN ground-truth root cause, runs the REAL extractive reasoning
pipeline over it, and the scorer checks whether the ground-truth cause appears
in the top-2 ranked hypotheses. Produces a results table (markdown + CSV).

This is the evidence that makes the dependency-graph (#4), change-correlation
(#5) and time-aware (#7) capabilities *provable* rather than asserted.
"""
from rca_agent.eval.cases import FAULT_LIBRARY, FaultCase
from rca_agent.eval.runner import CaseResult, HarnessReport, run_harness
from rca_agent.eval.scorer import score_case

__all__ = [
    "FAULT_LIBRARY",
    "CaseResult",
    "FaultCase",
    "HarnessReport",
    "run_harness",
    "score_case",
]
