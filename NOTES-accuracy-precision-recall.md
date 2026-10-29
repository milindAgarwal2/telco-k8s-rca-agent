# Accuracy vs. Precision vs. Recall — explained for the RCA Agent

A plain-language reference for how we measure the Kubernetes RCA agent's
root-cause quality, with examples from this project. Captured 2026-10-29.

---

## The one-line intuitions

- **Accuracy** = "Did the agent get the right answer in its short list?"
  (Is the true cause near the top?)
- **Precision** = "When the agent names causes, how many are actually real?"
  (Does it avoid crying wolf?)
- **Recall** = "Of all the things that were actually wrong, how many did the
  agent catch?" (Does it miss anything?)

---

## The setup (how the agent produces output)

For one incident, the agent outputs a **ranked list of hypotheses**. Example,
for a UPF pod that got OOMKilled:

```
Incident: upf-0 unhealthy
Agent's ranked hypotheses:
  1. upf-0 OOMKilled                      <- the real cause
  2. upf-0 failing health probe           <- a side-effect, not the root cause
  3. recent configmap edit to logging-cm  <- unrelated change it flagged
```

And separately, there is **the truth** (what a human SRE confirms actually
happened):

```
True cause(s): upf-0 OOMKilled
```

---

## ACCURACY — "right answer in the top-k?"

Our chosen metric is **top-2 accuracy**: is the true cause within the first 2
hypotheses?

- Here `upf-0 OOMKilled` is rank 1 -> within top 2 -> **correct.**
- Measured across many incidents: "the agent got the right cause in its top-2
  for 8 out of 8 cases = 100% top-2 accuracy."

Accuracy only cares about **one thing: did the right answer show up near the
top.** It does NOT care how much junk was also in the list. That blind spot is
exactly why we also want precision and recall.

---

## PRECISION — "of what it claimed, how much was real?"

Look at **everything the agent named** and ask how much was legitimate.

The agent named 3 causes. Only 1 is actually real (`OOMKilled`). The
probe-failure is a tolerated side-effect; the configmap edit is a genuine
**false alarm** (unrelated to the fault).

```
precision = real causes it named / total causes it named
          = 1 / (1 + 1 spurious) = 0.5  (50%)
```

**Low precision = a noisy agent that cries wolf** — it buries the real cause
among false alarms, and an operator learns to distrust it. High precision =
"when it speaks, trust it."

---

## RECALL — "of what was actually wrong, how much did it catch?"

Flip it: look at **the true causes** and ask how many the agent found.

This example had only 1 true cause, and the agent found it -> recall = 1/1 =
100%.

Recall matters most in a **multi-fault incident**. Say two things broke at once:

```
True causes: upf-0 OOMKilled  AND  amf-0 ImagePullBackOff
Agent named:  upf-0 OOMKilled   (but MISSED the amf-0 problem)

recall = found / total true = 1 / 2 = 0.5  (50%)
```

**Low recall = the agent misses real problems** (false negatives). Here it would
tell you "UPF is out of memory" and stay silent about AMF — so you fix one and
the outage continues.

---

## The key contrast (why you need all three)

| Metric | Question | Punishes | Blind to |
|---|---|---|---|
| **Accuracy (top-2)** | Right answer near the top? | -- | noise in the list, missed faults |
| **Precision** | Is what it says trustworthy? | false alarms (crying wolf) | missed faults |
| **Recall** | Does it catch everything? | missed faults (silence) | noise / false alarms |

Two memorable failure modes:

- An agent that outputs *every possible cause* has **perfect recall** (never
  misses) but **terrible precision** (mostly noise).
- An agent that outputs *only its single most confident guess* has **high
  precision** but risks **low recall** (misses a second simultaneous fault).

Good RCA needs the balance: name the real causes (**recall**), without drowning
them in false alarms (**precision**), ranked so the true one is on top
(**accuracy**).

---

## Formal definitions (for reference)

Classify each hypothesis the agent emits against the labeled truth:

- **TP** (true positive): a named cause that IS a true cause.
- **FP** (false positive): a named cause that is NOT real (spurious).
- **FN** (false negative): a true cause the agent did NOT name.

Then:

- **precision = TP / (TP + FP)**
- **recall    = TP / (TP + FN)**
- **top-k accuracy** = fraction of incidents where a true cause appears within
  the first k ranked hypotheses (we use k = 2).

(Note: in this project "tolerated" co-hypotheses — e.g. the generic probe-failure
that legitimately accompanies the real cause — are excluded from FP by policy;
see `src/rca_agent/eval/LABELING.md`.)

---

## Where this stands in the project

- **Today:** we measure **accuracy** (top-2) — the true cause is in the top 2 =
  100% on the 8 synthetic cases (`src/rca_agent/eval/results/results.md`).
- **The gap (currently paused):** precision/recall — these need the FULL set of
  true causes labeled per incident (not just one), so we can count false alarms
  and misses. That is exactly why the incident-capture format records every
  hypothesis the agent emitted plus an empty `gold_causes` slot
  (`src/rca_agent/eval/capture.py`, `LABELING.md`) — so later we can tally
  TP/FP/FN and compute precision/recall on REAL incidents, especially the
  multi-fault ones where recall is the thing accuracy cannot see.
