"""LLM synthesis of runbook next-steps (grounded, cited, never inventive).

The semantic retriever returns the top-k most *similar* runbook chunks. Pure
similarity on a short, keyword-dense incident query can rank a config EXAMPLE
(which repeats "Readiness/Liveness/probe") above the actual troubleshooting
section. The fix is a synthesis pass: give the local LLM sidecar the incident
symptom plus the candidate chunks and ask it to (a) pick the chunk that is a
genuine REMEDY for the symptom and (b) write one grounded next-step from it.

HARD GUARDRAILS (enforced in code, not just the prompt):
  * The LLM may only choose a chunk index it was given. An out-of-range /
    unparseable choice -> we keep the top retrieved hit unchanged.
  * The synthesized text is advisory; the CITATION always points to the real
    chunk source the LLM selected, so a human can verify.
  * Any error/timeout/unavailable sidecar -> return None, and the caller keeps
    the raw extractive next-steps. Enabling synthesis can never break the
    pipeline or fabricate a source.

This only runs when semantic RAG is active (which is itself gated behind a live
sidecar), so there is no extra availability check here.
"""
from __future__ import annotations

import json
import logging
import re

from rca_agent.config import Settings
from rca_agent.rag.runbook_retriever import RunbookHit

logger = logging.getLogger("rca_agent")

_SYSTEM = (
    "You are a Kubernetes troubleshooting assistant. You are given an incident "
    "symptom and a numbered list of candidate runbook excerpts retrieved from "
    "an operations manual. Your job: pick the ONE excerpt that is an actual "
    "REMEDY or DIAGNOSTIC procedure for the symptom (NOT a configuration "
    "example or reference listing), and write a single concise next-step a "
    "human operator should take, grounded ONLY in that excerpt. "
    "Do NOT invent commands or steps that are not in the chosen excerpt. "
    "Respond as STRICT JSON: {\"choice\": <integer index>, \"next_step\": "
    "\"<one or two sentences>\"}. If none of the excerpts is a real remedy, "
    "set choice to -1."
)


def _build_user_prompt(symptom: str, hits: list[RunbookHit]) -> str:
    lines = [f"INCIDENT SYMPTOM:\n{symptom}\n", "CANDIDATE RUNBOOK EXCERPTS:"]
    for i, h in enumerate(hits):
        # Fence untrusted runbook text so injected instructions can't steer the
        # model (same discipline as the rerank path).
        lines.append(f"[{i}] (source: {h.source})\n<<<\n{h.snippet}\n>>>")
    lines.append(
        "\nReturn JSON with the index of the best REMEDY excerpt and a grounded "
        "next_step. Use -1 if none is a real remedy."
    )
    return "\n".join(lines)


def _parse_json(content: str):
    """Best-effort: parse a JSON object from the model output."""
    try:
        return json.loads(content)
    except (json.JSONDecodeError, TypeError):
        m = re.search(r"\{.*\}", content or "", re.DOTALL)
        if not m:
            return None
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            return None


def synthesize_next_step(
    symptom: str, hits: list[RunbookHit], cfg: Settings
) -> tuple[str, RunbookHit] | None:
    """Return ``(next_step_text, chosen_hit)`` grounded in a retrieved chunk,
    or None to keep the raw extractive next-steps.

    Never raises. On any sidecar error, invalid JSON, or an out-of-range /
    -1 choice, returns None so the caller falls back to the unmodified hits.
    """
    if not hits:
        return None
    # Local import to avoid a hard dependency cycle and keep httpx import lazy.
    from rca_agent.reasoning.llm_rerank import _call_sidecar

    content = _call_sidecar(cfg, _SYSTEM, _build_user_prompt(symptom, hits))
    if content is None:
        return None
    parsed = _parse_json(content)
    if not isinstance(parsed, dict):
        logger.info("runbook synth: unparseable LLM output; keeping extractive next-steps")
        return None

    choice = parsed.get("choice")
    try:
        choice = int(choice)
    except (ValueError, TypeError):
        return None
    if choice < 0 or choice >= len(hits):
        # -1 (no real remedy) or out of range -> do not fabricate.
        logger.info("runbook synth: LLM found no grounded remedy (choice=%s)", choice)
        return None

    next_step = (parsed.get("next_step") or "").strip()
    if not next_step:
        return None
    return next_step, hits[choice]
