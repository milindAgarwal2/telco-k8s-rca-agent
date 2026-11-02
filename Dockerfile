FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HOME=/tmp

WORKDIR /app

# Install dependencies first for better layer caching.
COPY pyproject.toml README.md ./
COPY src ./src

# Install core + cluster + viz + rag + rag-semantic extras:
#   cluster      -> kubernetes client (reach the cluster)
#   viz          -> pyvis (interactive /graph/view HTML, embedded in the dashboard)
#   rag          -> pymupdf4llm + pypdf + python-multipart (structure-aware
#                   runbook extraction by default + the Runbooks tab upload)
#   rag-semantic -> fastembed (ONNX) + chromadb + langchain splitters. Ships the
#                   OPT-IN semantic runbook retriever. It stays OFF unless
#                   RCA_RUNBOOK_RAG_SEMANTIC=true AND the LLM sidecar is live --
#                   otherwise the agent falls back to the extractive retriever.
#                   Baked in so enabling it at deploy time needs no rebuild.
# The dashboard is now server-rendered HTML (FastAPI + Jinja2 + vendored
# Bootstrap/HTMX) in the SAME process -- no Streamlit, dropping the ~440 MB
# streamlit/pyarrow/pandas stack (see PLAN-image-size.md).
RUN pip install --upgrade pip && pip install ".[cluster,viz,rag,rag-semantic,pptx]"

# Pre-download the fastembed embedding model (BAAI/bge-small-en-v1.5, ONNX) into
# the image so the OPT-IN semantic RAG works OFFLINE on the Cobra jumpserver
# (the agent container has no internet by design). Cached under /tmp (HOME) so
# the non-root runtime user can read it. Best-effort: if the download fails at
# build time the image still works -- semantic RAG just falls back to extractive
# at runtime. The fastembed cache dir is set explicitly so the runtime user
# (uid 10001, HOME=/tmp) finds the same cache the build populated.
ENV FASTEMBED_CACHE_PATH=/opt/fastembed_cache
RUN mkdir -p "$FASTEMBED_CACHE_PATH" \
 && python -c "from fastembed import TextEmbedding; TextEmbedding(model_name='BAAI/bge-small-en-v1.5', cache_dir='/opt/fastembed_cache'); print('bge-small cached')" \
    || echo "WARN: fastembed model pre-download failed; semantic RAG will fall back to extractive at runtime" \
 && chmod -R a+rX "$FASTEMBED_CACHE_PATH"

COPY docker ./docker
RUN chmod +x ./docker/entrypoint.sh

# The one externally-visible port -- a single uvicorn process serves BOTH the
# API and the HTML dashboard now (no second process, no Unix-socket split).
ENV RCA_HOST=0.0.0.0 \
    RCA_PORT=8080

# Run as a non-root user (matches the Helm securityContext).
RUN useradd -u 10001 -r -s /usr/sbin/nologin appuser
USER 10001

EXPOSE 8080

CMD ["./docker/entrypoint.sh"]
