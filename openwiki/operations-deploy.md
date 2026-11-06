---
type: operations
title: Operations and Deployment
description: The container image, Helm chart with read-only RBAC, health probes, release packaging, and the optional LLM sidecar deploy.
tags:
  - operations
  - deployment
  - helm
  - rbac
  - container
verified:
  - by: openwiki/0.4.3
    at: 2026-11-03T19:34:26.963Z
sources:
  - id: openwiki-source-b23456ab756611b0d14aab4d
    resource: repo://deploy/helm/templates/deployment.yaml
  - id: openwiki-source-a040a21cb87604843b92ad88
    resource: repo://deploy/helm/templates/rbac.yaml
  - id: openwiki-source-f056d81349e383de297943d9
    resource: repo://deploy/helm/values.yaml
  - id: openwiki-source-b39c2a237ec6484b934d931f
    resource: repo://docker/entrypoint.sh
  - id: openwiki-source-7899632fc75fcc9c19586b6f
    resource: repo://docker/SIDECAR.md
  - id: openwiki-source-bb1ebe868e35e9e500714501
    resource: repo://Dockerfile
  - id: openwiki-source-76478c25db28b99104e23105
    resource: repo://scripts/release.sh
  - id: openwiki-source-91386c0b169bf4a09d4c43b0
    resource: repo://src/rca_agent/webhook/app.py
generated: { by: "kiro", at: "2026-11-03T19:34:26.963Z" }
---

# Operations and Deployment

> Draft pending subject-matter expert (SME) review. Deployment-topology
> specifics (hostnames, model file locations) come from narrative docs and are
> labelled as deployment-specific where they cannot be verified from source.

## Container image

The `Dockerfile` builds a single-process image from `python:3.12-slim`. One
uvicorn process serves both the read-only Application Programming Interface
(API) and the server-rendered HyperText Markup Language (HTML) dashboard on port
8080, as confirmed by `docker/entrypoint.sh`, which `exec`s a single
`uvicorn rca_agent.webhook.app:app` command.

The image installs the `cluster`, `viz`, `rag`, `rag-semantic`, and `pptx`
extras. It pre-downloads the fastembed embedding model
(`BAAI/bge-small-en-v1.5`, ONNX) into the image so the opt-in semantic RAG works
offline; the `Dockerfile` notes this is best-effort - if the download fails at
build time, semantic RAG falls back to extractive at runtime. The image runs as
a non-root user (uid 10001), matching the Helm `securityContext`.

## Helm chart

The chart lives under `deploy/helm/`.

**Read-only RBAC.** `deploy/helm/templates/rbac.yaml` creates a ServiceAccount
and a ClusterRole limited to `get`, `list`, and `watch` verbs across pods,
pods/log, services, endpoints, events, configmaps, secrets,
persistentvolumeclaims, nodes, namespaces, the `apps` workloads, `batch`
jobs/cronjobs, and `metrics.k8s.io`. The template carries an explicit comment:
"READ-ONLY BY CONSTRUCTION: only get/list/watch. No create/update/patch/delete."
A ClusterRoleBinding binds the role to the ServiceAccount.

**Deployment.** `deploy/helm/templates/deployment.yaml` runs the agent with the
ServiceAccount, injects `RCA_*` environment variables from values, and hardens
the pod: `runAsNonRoot`, `runAsUser` 10001, `allowPrivilegeEscalation: false`,
`readOnlyRootFilesystem: true`, and all capabilities dropped (from
`deploy/helm/values.yaml`). A writable `/tmp` `emptyDir` backs the runbook store
and caches because the root filesystem is read-only.

**Service.** A ClusterIP Service on port 8080 (from `values.yaml`); the Service
template is `deploy/helm/templates/service.yaml`.

**Defaults.** `values.yaml` defaults to `reasoningMode: extractive`,
`clusterEnabled: true`, `monitorNamespace: open5gs`, one replica, and modest CPU
and memory requests and limits.

## Health and readiness

The Deployment configures a liveness probe on `/healthz` and a readiness probe
on `/readyz`. `/readyz` reflects the background graph build (the handler returns
ready once the reasoning flow is initialized), as implemented in
`src/rca_agent/webhook/app.py`.

## Release packaging and the LLM sidecar

*Deployment-specific, from `docker/SIDECAR.md`:* `scripts/release.sh` builds the
agent image (and, with `--with-sidecar`, the sidecar image) and packages them
into `dist/`, including a `deploy-cobra.sh` script. Running `deploy-cobra.sh
--with-llm` loads the sidecar image, starts it with the GGUF model mounted
read-only on `127.0.0.1:8090`, waits for it to answer, then starts the agent in
`llm` mode. If the sidecar does not come up, the agent is deployed in extractive
mode instead, so the sidecar never blocks the deploy. Plain `deploy-cobra.sh`
runs the agent only, in extractive mode.

The GGUF model file lives outside the images and is not committed to git; the
exact host and path in `docker/SIDECAR.md` are deployment-specific and not
verifiable from repository source.

## Related pages

- [System Overview](/openwiki/overview.md)
- [Quickstart](/openwiki/quickstart.md)
- [Configuration Reference](/openwiki/configuration.md)
- [Integrations and Data Inputs](/openwiki/integrations.md)
