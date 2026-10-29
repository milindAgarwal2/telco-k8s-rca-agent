"""Scoring: does the known root cause appear in the top-2 ranked hypotheses?

Top-2 accuracy (user-confirmed): a case is CORRECT when the ground-truth cause
is among the first two hypotheses. We also record the top-1 hit and the 1-based
rank at which the correct cause appeared (0 = not found) for diagnostics.
"""
from __future__ import annotations

from dataclasses import dataclass

from rca_agent.eval.cases import FaultCase
from rca_agent.models.incident import Hypothesis


@dataclass
class Score:
    top1: bool          # correct cause is the #1 hypothesis
    top2: bool          # correct cause is within the top 2
    matched_rank: int   # 1-based rank of the correct cause (0 = not found)
    top_cause: str      # the #1 hypothesis cause (or "" if none)
    n_hypotheses: int


def score_case(case: FaultCase, hypotheses: list[Hypothesis]) -> Score:
    matched_rank = 0
    for i, h in enumerate(hypotheses, start=1):
        if case.ground_truth(h):
            matched_rank = i
            break
    return Score(
        top1=(matched_rank == 1),
        top2=(1 <= matched_rank <= 2),
        matched_rank=matched_rank,
        top_cause=(hypotheses[0].cause if hypotheses else ""),
        n_hypotheses=len(hypotheses),
    )
