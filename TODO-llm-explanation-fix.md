# TODO: fix LLM rerank "explanation" quality (echo bug) + surface concrete error

Captured 2026-10-29 (to action later). Not yet implemented.

## Symptom (observed on the live Cobra demo, LLM sidecar running)
In an incident's evidence chain, the LLM line just REPEATS the cause verbatim:

```
LLM explanation: recent rollout to rca-demo-imagepull        <-- echo, not an explanation
symptom: PodPersistentlyUnhealthy on rca-demo-imagepull-...
rollout on rca-demo-imagepull: new ReplicaSet (images: fake-registry.invalid/.../does-not-exist:v0)
...
```
The `reasoning_mode` was `llm-rerank (...)`, so the LLM IS running and its
REORDER works — but the EXPLANATION content is a worthless echo of the cause.

Separately: the top hypothesis is "recent rollout to rca-demo-imagepull"
(generic) rather than naming the concrete error (ImagePullBackOff). The error
hypotheses DO exist lower in the list (ImagePullBackOff #2, ErrImagePull #4);
ranking the CAUSE (rollout) above the SYMPTOM (ImagePullBackOff) is correct RCA
behavior — the issue is the headline WORDING is too vague, not the order.

## Root cause
- Qwen2.5-1.5B is small; under the current prompt it fills the
  `explanations[<id>]` slot with the nearest text (the cause string) instead of
  writing a real rationale.
- The prompt doesn't forbid repeating the cause, and the model isn't given
  enough concrete evidence (the bad image, the ImagePullBackOff symptom) to
  ground a real explanation.

## Planned fix (all in src/rca_agent/reasoning/llm_rerank.py — agent side only,
##            no sidecar rebuild; just redeploy the agent image)

1. STRENGTHEN THE PROMPT
   - Explicitly: "Do NOT repeat the cause text. In ONE sentence explain WHY
     this is the likely root cause, referencing the evidence (e.g. the image,
     the event). Use your own words."
   - Add a one-shot good-vs-bad example in the system prompt.

2. FEED THE EVIDENCE INTO THE EXPLANATION REQUEST
   - Include the concrete detail (bad image value, the ImagePullBackOff/
     ErrImagePill events) alongside each hypothesis so the model has something
     grounded to explain, not just the cause label.

3. ANTI-ECHO GUARD (code)
   - After parsing, if an explanation is (normalized) equal to / high-overlap
     with the cause string, DROP it (attach no explanation rather than an
     echo). Cheap, deterministic safety net regardless of model quality.

4. (SEPARATE, DETERMINISTIC) ENRICH THE CAUSE/HEADLINE WITH THE CONCRETE ERROR
   - In reasoning/steps.py, make the change-correlated hypothesis's cause name
     the concrete failure, e.g.
       "recent rollout to rca-demo-imagepull (bad image -> ImagePullBackOff)"
     The bad image + symptom are already in evidence; promote into the cause
     text so the concrete error shows EVEN WHEN THE LLM IS OFF.
   - This addresses the "I don't see the actual error" point independent of the
     LLM.

## Verification
- Add/extend mocked test in tests/test_llm_rerank.py: an explanation equal to
  the cause is dropped (anti-echo); a real explanation is kept.
- make check (expect pass + ruff clean).
- Redeploy agent image on Cobra (sidecar unchanged); re-run chaos-demo inject;
  confirm the "LLM explanation:" line is a real sentence (or absent), and the
  headline names ImagePullBackOff.

## Honest caveat
Even fixed, a 1.5B model's prose is short and sometimes generic. The ECHO is
fixable at 1.5B; consistently sharp explanations would want a 3B model (bigger
sidecar, more RAM). Decide later if the quality warrants the upgrade.

## Scope confirmed with user: do BOTH
- Fix explanation echo (LLM side: prompt + evidence + anti-echo guard), AND
- Enrich the cause string with the concrete error (deterministic side), so the
  error shows regardless of LLM state.
