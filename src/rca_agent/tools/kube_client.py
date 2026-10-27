"""Read-only Kubernetes client bootstrap.

Config is loaded one of three ways, selected by ``kubeconfig_mode``:

* ``incluster`` — use the mounted ServiceAccount token (the normal in-pod
  deployment path). Safety rests on the restricted ClusterRole bound to that SA.
* ``local`` — use the local kubeconfig (dev iteration from a jumphost/laptop).
* ``auto`` (default) — in-cluster if the ServiceAccount token is present, else
  fall back to kubeconfig. The same build therefore works both ways with no
  code change.

The client is used read-only: only ``list_*`` / ``read_*`` calls are ever made.
The ``kubernetes`` dependency lives in the ``[cluster]`` extra, so it is imported
lazily — the no-cluster/demo path never needs it installed.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass

logger = logging.getLogger("rca_agent.kube")

# Standard in-pod ServiceAccount token mount path.
_SA_TOKEN_PATH = "/var/run/secrets/kubernetes.io/serviceaccount/token"


@dataclass
class KubeClient:
    """Thin holder for the read-only typed API clients."""

    core: object  # kubernetes.client.CoreV1Api
    apps: object  # kubernetes.client.AppsV1Api
    mode: str     # how config was loaded: "incluster" | "local"


def _running_in_cluster() -> bool:
    return os.path.exists(_SA_TOKEN_PATH) or bool(os.environ.get("KUBERNETES_SERVICE_HOST"))


def build_kube_client(mode: str = "auto") -> KubeClient:
    """Load kube config (read-only) and return typed CoreV1Api + AppsV1Api.

    Raises RuntimeError with a clear message if the ``[cluster]`` extra is not
    installed, or if config cannot be loaded for the requested mode.
    """
    try:
        from kubernetes import client, config  # type: ignore
        from kubernetes.config.config_exception import ConfigException  # type: ignore
    except ImportError as exc:  # pragma: no cover - import guard
        raise RuntimeError(
            "The kubernetes client is not installed. Install the cluster extra: "
            "pip install '.[cluster]'"
        ) from exc

    loaded_mode = _load_config(config, ConfigException, mode)
    logger.info("kube config loaded via %s", loaded_mode)
    return KubeClient(core=client.CoreV1Api(), apps=client.AppsV1Api(), mode=loaded_mode)


def _load_config(config, ConfigException, mode: str) -> str:
    """Load kube config for the requested mode; return the effective mode."""
    if mode not in ("auto", "incluster", "local"):
        raise RuntimeError(f"invalid kubeconfig_mode: {mode!r}")

    if mode in ("auto", "incluster") and _running_in_cluster():
        try:
            config.load_incluster_config()
            return "incluster"
        except ConfigException:
            if mode == "incluster":
                raise
            # auto: fall through to local

    if mode == "incluster":
        raise RuntimeError(
            "kubeconfig_mode=incluster but no in-cluster ServiceAccount token found."
        )

    try:
        config.load_kube_config()
        return "local"
    except ConfigException as exc:
        raise RuntimeError(
            "Could not load kubeconfig (local mode). Set KUBECONFIG or run in-cluster."
        ) from exc
