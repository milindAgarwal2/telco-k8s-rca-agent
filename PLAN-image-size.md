# Plan: claw back the +133 MB (0.3.8) image-size regression

## Recap of the problem (verified)

| Version | Tarball (compressed) | Largest image layer (uncompressed) |
|---------|----------------------|-------------------------------------|
| 0.3.0–0.3.7 | ~92 MB | 266 MB (pip layer) |
| 0.3.8+ | 225 MB | **714 MB** (pip layer) |

The entire jump is **one layer** — the `pip install ".[cluster,viz,ui,rag]"`
layer. All base-OS/Python layers are byte-identical (same sha256) before and
after. Installing `streamlit` alone adds **441 MB** of site-packages,
dominated by its *transitive* deps, none of which the RCA logic uses:

| Package | Size | Who needs it |
|---------|------|--------------|
| pyarrow | 172 MB | streamlit (`st.dataframe` serialization) |
| pandas | 77 MB | streamlit, pyarrow |
| numpy (+libs) | 68 MB | pandas, pydeck |
| streamlit | 34 MB | the dashboard |
| pydeck | 24 MB | streamlit (maps — unused here) |
| pillow | 22 MB | streamlit (image widgets — unused here) |
| altair | 10 MB | streamlit (charts — unused here) |

**Hard constraint discovered:** pyarrow, pandas, numpy, pydeck, pillow, altair
are all *required* dependencies in streamlit's own metadata. `pip` cannot skip
them. Any size win that keeps streamlit must either (a) physically delete files
after install, or (b) move streamlit out of the core image.

The dashboard's only real use of the heavy stack is **two `st.dataframe()`
calls** (Incidents table, Query Log table). Everything else is metrics,
markdown, `components.html` (the pyvis graph), progress bars, file upload —
none of which needs pandas/pyarrow.

---

## The three options, evaluated

### Option A — Split the dashboard into a separate sidecar image (RECOMMENDED)

Build **two images**:

- `rca-agent:<ver>` — core only: `pip install ".[cluster,viz]"`. No streamlit.
  Back to ~92 MB. This is the image that runs the read-only agent against the
  cluster.
- `rca-agent-ui:<ver>` — `pip install ".[ui,rag-client]"` + the
  `streamlit_app/`. ~440 MB, but it carries no cluster credentials and does
  nothing but render the backend's JSON/HTML.

They talk over the existing UDS when co-located, or over TCP when split.

**Pros**
- Core image returns to ~92 MB; the heavy UI is opt-in and isolated.
- Matches the security story already in the code: the dashboard is "read-only,
  no cluster access"; making it a separate image makes that *structural*.
- Nothing about the backend changes.

**Cons / work**
- The UDS trick (`docker/entrypoint.sh`) assumes one container/one filesystem.
  Split across two containers/pods, the socket must become either a shared
  volume (same pod, `emptyDir`) or a TCP port. For the Cobra `docker run
  --network host` path, two containers can share a UDS via a bind-mounted host
  dir, OR the backend re-exposes a localhost TCP port. Needs a decision.
- Two Dockerfiles / two build+package flows / two Helm containers.

**Scope:** medium. Biggest win, cleanest long-term.

---

### Option B — Keep one image, strip unused heavy deps in a multi-stage build

`pip install` everything in a builder stage, then in the final stage delete the
packages the dashboard never imports (pydeck, pillow, altair for sure; pyarrow
+ pandas *only if* we first remove the two `st.dataframe` calls).

**Pros**
- Stays a single image / single deploy flow — no architecture change.
- Can reclaim a lot: dropping pydeck+pillow+altair alone ≈ 56 MB; adding
  pyarrow+pandas (after de-dataframe-ing the UI) ≈ another 249 MB. Potential
  final core ≈ 92 + (441−305) ≈ **~135 MB**.

**Cons / risk**
- **Fragile.** streamlit imports pandas/pyarrow lazily; deleting them risks a
  runtime `ImportError` the moment any code path (or a future edit) touches a
  dataframe/chart. Must be guarded by a smoke test that exercises every tab.
- Deleting files out from under a pip-installed package is unsupported; upgrades
  of streamlit could change what's safe to remove.

**Scope:** medium. Decent win, but ongoing fragility.

---

### Option C — Drop Streamlit entirely for a lighter UI

The FastAPI backend already serves HTML (`/graph/view`). Replace the Streamlit
dashboard with server-rendered HTML pages (Jinja2 templates, ~a few hundred KB)
served by the *existing* FastAPI app. The pyvis graph is already HTML; the
incident/runbook/query-log tabs become HTML tables + a tiny bit of JS.

**Pros**
- Biggest size win: removes the *entire* 441 MB streamlit stack. Core image
  back to ~92 MB **and** the UI lives in the same cheap image.
- One process again (no UDS dance, no two-port entrypoint) — simpler than today.
- Jinja2 is already pulled in transitively (via uvicorn/starlette), so ~0 added.

**Cons / work**
- Rewrites `streamlit_app/dashboard.py` (~450 lines) as FastAPI routes +
  templates. The interactive bits (file upload with confirm, CSV download,
  delete-with-confirm, auto-refresh) must be re-implemented in HTML/HTMX or
  minimal JS. This is the most code.
- Loses Streamlit niceties (auto-reactivity, widgets) for hand-written HTML.

**Scope:** large. Best end-state size+simplicity, most rewrite.

---

## Recommendation

**Option A (sidecar split)** as the primary path — it gives the full ~92 MB core
win, hardens the existing read-only security story, and touches the least code.
If you'd rather not run two images, **Option C** is the better single-image
end-state than B (B's file-stripping fragility isn't worth the smaller win).

I'd avoid B except as a quick stopgap.

---

## Implementation plan — Option A (recommended)

### Phase 1 — Decouple the transport (prerequisite)
1. Make the backend's listen target configurable: UDS *or* TCP, via an env var
   already-ish present (`RCA_HOST`/`RCA_PORT` exist; add `RCA_BACKEND_UDS`
   override). Default stays UDS for the co-located case.
2. Dashboard already reads `RCA_BACKEND_UDS`; add a `RCA_BACKEND_URL` fallback
   so it can talk TCP to a sidecar when no socket is shared.

### Phase 2 — Two Dockerfiles
3. `Dockerfile` (core): `pip install ".[cluster,viz]"`, CMD = uvicorn only
   (drop the entrypoint's streamlit half). Verify ~92 MB.
4. `Dockerfile.ui`: `pip install ".[ui,rag]"` + copy `streamlit_app/`,
   CMD = `streamlit run`. (rag’s pypdf/multipart live with the UI, since upload
   happens there — but the *store/retriever* stay in core; see Phase 4.)

### Phase 3 — Wire them together
5. **Cobra (`docker run`)**: run two containers; share the UDS via a
   bind-mounted host dir (`-v /run/rca:/run/rca`) OR point the UI at the core
   over `127.0.0.1:<port>`. Update `deploy-cobra.sh` to start both + health-check
   both. Keep `--network host` only where the cluster call needs it (core).
6. **Helm**: make the dashboard a second container in the same Pod sharing an
   `emptyDir` for the socket (simplest), or a second Deployment+Service. Probes
   split: core → `/healthz` (now reachable again on its own port/socket), UI →
   `/_stcore/health`.

### Phase 4 — Resolve the runbook-store seam
7. Today the runbook store/query-log are read+written by BOTH the FastAPI
   backend (retrieval) and the Streamlit upload handler, relying on a shared
   filesystem. Split images break that shared file. Fix: the dashboard's
   upload/delete must go **through the backend's existing `POST/DELETE
   /runbooks` HTTP endpoints** (it already does! `_post_runbook`/`_delete` call
   the API) — so the store lives only in the **core** image, and `rag` stays a
   core extra (pypdf), NOT a UI extra. Correct Phase 2 line 4 accordingly:
   core = `.[cluster,viz,rag]`, UI = `.[ui]` only. This keeps pypdf (pure
   Python, tiny) in core and leaves the UI image as pure streamlit.

### Phase 5 — Verify + package
8. Build both; confirm core tarball back to ~92 MB, UI ~225 MB.
9. Smoke-test: start both, exercise every tab, upload a PDF, fire a webhook,
   confirm suggested-next-steps still render.
10. Version bump, update PLAN.md + README (two-image topology), re-package.

### Rollback
- Both old single-image tarballs remain in `dist/`; revert is just redeploying
  `rca-agent:0.4.0`.

---

## Quick stopgap (if you want *some* win today, low risk)

Independently of A/C: the dashboard never uses maps or image widgets, so
**pydeck + pillow + altair are safe-ish to strip** in a multi-stage final layer
(~56 MB) because no dashboard code path imports them. That alone takes 225 → ~195
MB with near-zero risk, and is a 5-line Dockerfile change — a useful down payment
while the sidecar split is built. (Still needs the all-tabs smoke test.)

---

## My recommended sequencing

1. **Now (optional):** stopgap strip of pydeck/pillow/altair (~56 MB, 5 lines).
2. **Main:** Option A, Phases 1–5 — core back to ~92 MB, UI isolated.
3. Revisit Option C later only if running two images proves annoying.
