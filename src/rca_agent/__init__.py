"""Read-only Kubernetes fault detection & root-cause agent for a 5G core.

The agent detects faults (via Alertmanager webhook and Kubernetes events),
gathers evidence, reasons over a live NetworkX dependency graph, and emits an
incident report with ranked root-cause hypotheses. It never mutates the cluster.
"""

__version__ = "0.9.0"
