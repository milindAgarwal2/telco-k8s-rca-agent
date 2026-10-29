FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HOME=/tmp

WORKDIR /app

# Install dependencies first for better layer caching.
COPY pyproject.toml README.md ./
COPY src ./src

# Install core + cluster + viz + rag extras:
#   cluster -> kubernetes client (reach the cluster)
#   viz     -> pyvis (interactive /graph/view HTML, embedded in the dashboard)
#   rag     -> pypdf + python-multipart (the dashboard's Runbooks tab upload)
# The dashboard is now server-rendered HTML (FastAPI + Jinja2 + vendored
# Bootstrap/HTMX) in the SAME process -- no Streamlit, dropping the ~440 MB
# streamlit/pyarrow/pandas stack (see PLAN-image-size.md).
RUN pip install --upgrade pip && pip install ".[cluster,viz,rag,pptx]"

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
