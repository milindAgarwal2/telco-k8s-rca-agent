# Chaos demo — live ImagePullBackOff detected by the RCA agent

A SAFE, self-cleaning demo: inject one throwaway Deployment with a non-existent
image so the read-only RCA agent raises an ImagePullBackOff incident live, then
clean it up. Runs in the SAME namespace as production, so it is tightly scoped
by the label `rca-demo=true`.

> The RCA agent stays read-only. `chaos-demo.sh` is a SEPARATE actor using YOUR
> `oc` credentials. Nothing the agent does mutates the cluster.

## 0. Prereqs (on the Cobra jumpserver)
```bash
oc login https://api.cobra-2a-openshift.bete.ericy.com:6443 \
  -u eagamil -p '<password>' --insecure-skip-tls-verify
# confirm create/delete on deployments/pods in the namespace:
oc auth can-i create deployments -n plantx2avzwcspgc-y-oc-consp-301
oc auth can-i delete deployments -n plantx2avzwcspgc-y-oc-consp-301
```
Copy the script up:
```bash
scp scripts/chaos-demo.sh eagamil@10.242.70.7:~/
```

## 1. (Recommended) make detection fast for the demo
The default agent polls slowly (event watch 15s, graph rebuild 60s, needs 2
unhealthy rebuilds). For a snappy live demo, redeploy the agent with faster
intervals (add to the `docker run` in deploy-cobra.sh, or set before deploy):
```bash
-e RCA_EVENT_WATCH_INTERVAL_SECONDS=10 \
-e RCA_GRAPH_REBUILD_INTERVAL_SECONDS=15 \
-e RCA_STATUS_UNHEALTHY_REBUILDS=1 \
```
ImagePullBackOff emits a Warning event quickly, so the event watcher usually
catches it within one poll even without this.

## 2. Review what it will do (changes nothing)
```bash
./chaos-demo.sh inject --dry-run
./chaos-demo.sh cleanup --dry-run
```

## 3. Run the demo
```bash
./chaos-demo.sh inject         # creates rca-demo-imagepull (fault ON, persists)
./chaos-demo.sh status         # shows the pod in ImagePullBackOff/ErrImagePull
```
Then show the agent:
- Dashboard **Incidents** tab (or `curl localhost:8004/incidents`) — a new
  **active** incident for `rca-demo-imagepull-*`, cause "ImagePullBackOff",
  with the event timestamp (0.7.2) and evidence.
- **Graph** tab — switch type to **Pod**, search `rca-demo` — the dummy pod,
  unhealthy.

## 4. Clean up (and show recovery)
```bash
./chaos-demo.sh cleanup        # deletes ONLY resources labeled rca-demo=true
```
After the pod is gone, the incident flips to **inactive** on the Incidents tab
(0.7.3) — a nice "it detected the fault AND saw it resolve" beat.

## Safety summary
- Everything created carries `rca-demo=true` + name prefix `rca-demo-`.
- `cleanup` deletes STRICTLY by `-l rca-demo=true` — never by name or namespace,
  so it cannot touch a real `eric-pc-sm-*` workload.
- The fake image `fake-registry.invalid/...` is never pulled; no code runs.
- `--dry-run` prints the exact `oc` commands; an interrupted `inject` self-cleans.
- If anything looks off: `oc get all -n <ns> -l rca-demo=true` shows exactly
  what the demo owns; `./chaos-demo.sh cleanup` removes it.
