# RCA Agent - Fault-Injection Accuracy Results

Synthetic offline harness (no cluster, no LLM). Each case injects one known fault into a fake cluster, runs the real extractive pipeline, and scores the ranked hypotheses. **Accuracy metric: top-2** (the known cause is among the top two hypotheses).

- Cases: **8**
- Top-1 accuracy: **62%** (5/8)
- Top-2 accuracy: **100%** (8/8)

| Case | Fault type | Expected cause | Top hypothesis | Rank | Top-1 | Top-2 |
|---|---|---|---|---|---|---|
| oomkilled | OOMKilled | upf-0 OOMKilled | upf-0 OOMKilled | 1 | yes | yes |
| crashloop | CrashLoopBackOff | smf-0 CrashLoopBackOff | smf-0 failing health probe (smf-0 not ready (readiness probe failing)) | 2 | no | yes |
| imagepull | ImagePullBackOff | amf-0 ImagePullBackOff | amf-0 ImagePullBackOff | 1 | yes | yes |
| probe_failure | ProbeFailure | diameter-0 failing health probe | diameter-0 failing health probe (55:06] Unhealthy: Readiness probe failed: HTTP probe failed with statuscode: 500) | 1 | yes | yes |
| bad_configmap | BadConfigChange | recent configmap_update to upf-config | upf-0 failing health probe (55:06] Unhealthy: Readiness probe failed: config rejected) | 2 | no | yes |
| unhealthy_upstream | UpstreamCascade | service/upf unhealthy (cascades to smf-0) | smf-0 failing health probe (55:06] Unhealthy: Readiness probe failed: upstream UPF unreachable) | 2 | no | yes |
| node_not_ready | NodeNotReady | pcf-0 not ready (node worker-2 NotReady) | pcf-0 failing health probe (pcf-0 not ready (readiness probe failing)) | 1 | yes | yes |
| multi_fault_separation | MultiFault | upf-0 OOMKilled (amf-0 ImagePull is a separate incident) | upf-0 OOMKilled | 1 | yes | yes |
