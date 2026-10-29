# Install & setup

## 1. Base agent (no LLM, no cluster) — the default

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e .                 # core deps only
# or with extras:
pip install -e '.[dev,cluster,viz,rag,pptx]'

uvicorn rca_agent.webhook.app:app --reload --port 8080
```

Dev loops (Makefile): `make check` (lint+test) · `make test` · `make lint` ·
`make eval` (fault-injection accuracy harness).

Runs out-of-the-box in **extractive** mode (deterministic, no LLM, no network).

---

## 2. Optional: local LLM rerank sidecar (assessment #3)

When enabled, a **local** small LLM re-ranks and explains the hypotheses the
deterministic pipeline already produced. It can never invent a cause, runs
fully offline (no internet, no public IP), and the agent falls back to
extractive on any failure. See `docker/SIDECAR.md` for the full design.

> **The model file (GGUF) is NOT in this repository** — it is ~1.1 GB and would
> bloat git history. You download or copy it separately (steps below). The repo
> only contains the code + these instructions.

### 2a. Obtain the model (GGUF)

Default model: **Qwen2.5-1.5B-Instruct, Q4_K_M** (~1.1 GB). Either:

- **Reuse the one from the ChatBOT project** (if you have it):
  ```bash
  cp /home/milind/ChatBOT/models/qwen2.5-1.5b-instruct-q4_k_m.gguf ./models/model.gguf
  ```
- **Download from Hugging Face** (one-time, on a connected machine):
  ```bash
  mkdir -p models
  # repo: Qwen/Qwen2.5-1.5B-Instruct-GGUF  file: qwen2.5-1.5b-instruct-q4_k_m.gguf
  #   (use huggingface-cli, or the website, or:)
  curl -L -o models/model.gguf \
    https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/main/qwen2.5-1.5b-instruct-q4_k_m.gguf
  ```

`models/` and `*.gguf` are git-ignored — the model never gets committed.

You may use any GGUF chat model; set `RCA_LLM_MODEL` to a matching name and
adjust the sidecar `--chat_format` in `docker/Dockerfile.sidecar` if needed.

### 2b. Run the sidecar locally (dev)

Option 1 — in the venv (needs a C/C++ toolchain to build llama-cpp-python):
```bash
pip install 'llama-cpp-python[server]==0.3.36'
python -m llama_cpp.server --model models/model.gguf \
  --host 127.0.0.1 --port 8090 --n_ctx 4096 --chat_format qwen
```
Option 2 — as the sidecar container:
```bash
docker build -f docker/Dockerfile.sidecar -t rca-agent-sidecar:dev .
docker run -d --name rca-llm -p 127.0.0.1:8090:8090 \
  -v "$PWD/models/model.gguf":/models/model.gguf:ro \
  -e LLM_HOST=0.0.0.0 rca-agent-sidecar:dev
```

Then run the agent in LLM mode:
```bash
RCA_REASONING_MODE=llm RCA_LLM_BASE_URL=http://127.0.0.1:8090 \
  uvicorn rca_agent.webhook.app:app --port 8080
```
Verify: `curl 127.0.0.1:8090/v1/models`; an incident's `reasoning_mode` should
read `llm-rerank (...)`. If the sidecar is down, the agent stays extractive.

### 2c. Deploy on Cobra with the LLM

```bash
# build + package both images:
./scripts/release.sh 0.8.0 --with-sidecar

# one-time: copy the GGUF to the jumpserver (NOT shipped in any image/repo):
ssh eagamil@10.242.70.7 'mkdir -p ~/models'
scp models/model.gguf eagamil@10.242.70.7:~/models/model.gguf

# copy the package up, then on the jumpserver (after oc login):
./deploy-cobra.sh --with-llm
```

### LLM config (all `RCA_*`)
`reasoning_mode` (extractive|llm) · `llm_base_url` (default
`http://127.0.0.1:8090`) · `llm_model` (default `qwen2.5-1.5b-instruct`) ·
`llm_timeout_seconds` (30) · `llm_max_tokens` (512) · `llm_temperature` (0.1).

### Resource note
The 1.5B Q4 model needs ~2 GB RAM, runs on CPU, a few seconds per rerank (one
call per incident). The agent image is unaffected (~104 MB); the model and the
sidecar are separate.
