# Fault-injection accuracy harness (assessment point #9)

A synthetic, **offline, cluster-free** benchmark: inject a known fault into a
fake Kubernetes cluster, run the **real** extractive reasoning pipeline over it,
and measure whether the agent's ranked hypotheses name the correct root cause.

This is the evidence that makes the dependency-graph (#4), change-correlation
(#5) and time-aware (#7) capabilities *provable* rather than asserted — and it
runs in CI with no cluster and no LLM.

## Run it

```bash
python -m rca_agent.eval                 # run, print summary, write results/
python -m rca_agent.eval --no-write      # just print
python -m rca_agent.eval --min-top2 0.9  # fail (exit 1) if top-2 < 90%
```

Outputs `results/results.md` and `results/results.csv`.

## Metric: top-2 accuracy

A case is **correct** when the known root cause appears in the **top 2** ranked
hypotheses. We also report top-1 and the exact rank for diagnostics. Top-2 is
the chosen headline metric: the agent surfaces a short ranked list for a human,
so "the right cause is at the top of the list" is the operationally meaningful
bar, and it tolerates the common, honest case where a self-contained probe
failure and its underlying cause both legitimately appear.

## How it works

- `fake_cluster.py` — a package-local, duck-typed read-only kube client (pods,
  events, logs, configmaps, services, nodes, …). No `kubernetes` package.
- `cases.py` — the `FaultCase` model + `FAULT_LIBRARY`. Each case builds a store
  with ONE injected fault, the triggering `Alert`, and a `ground_truth` matcher
  that recognises the correct cause in a `Hypothesis`.
- `runner.py` — builds a real `GraphBuilder(cfg, kube_client=FakeKubeClient(...))`
  with `cluster_enabled=True` (so the real `KubeQueryTools` run, not the demo
  stub) and `reasoning_mode="extractive"`, runs the real `ReasoningFlow`, scores.
- `scorer.py` — top-1 / top-2 / matched-rank.
- `report.py` + `__main__.py` — markdown/CSV table and the CLI.

## Fault library (8 cases)

OOMKilled, CrashLoopBackOff, ImagePullBackOff, readiness-probe failure (HTTP
500), bad mounted-ConfigMap change, unhealthy upstream cascade (via a `calls`
edge), node NotReady, and two simultaneous independent faults (separation).

## Add a case

Append a `FaultCase` to `FAULT_LIBRARY` in `cases.py`: a `build_store` that
injects the fault, the `Alert` (remember `Alert.name/target/namespace` are
read-only properties derived from `labels`), and a `ground_truth` matcher
(`cause_contains(...)` is the usual helper).

## Scope & honesty

- Synthetic faults on a fake cluster — not a substitute for live-cluster
  validation, but reproducible and regression-proof.
- Some cases score at rank 2 because a probe-failure hypothesis co-occurs with
  the underlying cause and ranks first; that is real pipeline behaviour, left
  un-gamed so the numbers mean something.
- Live chaos injection (Chaos Mesh / `oc`) is deliberately out of scope here —
  it is non-reproducible and crosses the read-only boundary.
