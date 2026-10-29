# Local LLM rerank sidecar (assessment point #3)

The agent's root-cause hypotheses are produced deterministically. When
`RCA_REASONING_MODE=llm`, the agent asks a **local** small LLM to **re-rank and
explain** those hypotheses — it can never invent, add, or remove a cause. The
LLM runs as a **sidecar container** (llama.cpp server) next to the agent.

## Architecture
```
  [ rca-agent container ]  --HTTP (loopback)-->  [ llama.cpp sidecar ]
   extractive pipeline      127.0.0.1:8090        serves the GGUF model
   -> hypotheses            /v1/chat/completions   (Qwen2.5-1.5B, ~1.1 GB)
   -> llm_rerank() reorders+explains
```
- **No internet, no public IP.** The GGUF is a local file; llama.cpp makes zero
  outbound calls; the endpoint is bound to **loopback** (`127.0.0.1`) so even on
  the `--network host` jumpserver it is not reachable by other users.
- **Safe by construction.** Any sidecar error/timeout/unavailable → the agent
  falls back to the deterministic extractive order. Extractive stays the
  default; the LLM is strictly opt-in.
- **Guardrails** (`reasoning/llm_rerank.py`): the model may only return a
  permutation of the existing hypothesis ids + a one-line explanation each; any
  unknown/duplicate/wrong-length order is rejected and the extractive order
  kept; untrusted evidence text is fenced before the model sees it.

## Model (reused from ChatBOT)
`qwen2.5-1.5b-instruct-q4_k_m.gguf` (~1.1 GB), the same GGUF used by the ChatBOT
and telco-rag projects. **Option A**: the model is NOT baked into the image — it
is mounted as a read-only volume, so the sidecar image stays small.

## Build & package
```bash
# builds BOTH the agent image and the sidecar image, packages them into dist/:
./scripts/release.sh 0.8.0 --with-sidecar
# produces dist/cobra-package-0.8.0/:
#   rca-agent-0.8.0.tar.gz(.sha256)
#   rca-agent-sidecar-0.8.0.tar.gz(.sha256)
#   deploy-cobra.sh  (canonical, from docker/deploy-cobra.sh)
```

## One-time: copy the GGUF to the jumpserver
```bash
ssh eagamil@10.242.70.7 'mkdir -p ~/models'
scp /home/milind/ChatBOT/models/qwen2.5-1.5b-instruct-q4_k_m.gguf \
    eagamil@10.242.70.7:~/models/model.gguf
```
(The model file lives OUTSIDE the images and is never committed to git.)

## Deploy with the LLM enabled
```bash
# copy the package up, then on the jumpserver (after oc login):
./deploy-cobra.sh --with-llm
```
`--with-llm` loads the sidecar image, starts it with the GGUF mounted
read-only on `127.0.0.1:8090`, waits for it to answer, then starts the agent
with `RCA_REASONING_MODE=llm` + `RCA_LLM_BASE_URL=http://127.0.0.1:8090`. If the
sidecar doesn't come up, it deploys the agent in **extractive** mode instead
(never blocks the deploy).

Plain `./deploy-cobra.sh` (no flag) = agent only, extractive — unchanged.

## Verify
```bash
curl -s 127.0.0.1:8090/v1/models                 # sidecar up
docker logs -f rca-agent-llm                      # model load / requests
# fire an incident; its reasoning_mode should read "llm-rerank (qwen2.5-1.5b-instruct)",
# and the top hypothesis gains an "LLM explanation: ..." line in its evidence chain.
```

## Resource note
The 1.5B Q4 model needs ~2 GB RAM and runs on CPU; expect a few seconds per
rerank. One LLM call per incident, so throughput is a non-issue.

## Config (agent side; all RCA_*)
`reasoning_mode` (extractive|llm) · `llm_base_url` (default
http://127.0.0.1:8090) · `llm_model` (qwen2.5-1.5b-instruct) ·
`llm_timeout_seconds` (30) · `llm_max_tokens` (512) · `llm_temperature` (0.1).
