FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HOME=/tmp

WORKDIR /app

# Install dependencies first for better layer caching.
COPY pyproject.toml README.md ./
COPY src ./src

# Install core + cluster + viz + ui + rag extras:
#   cluster -> kubernetes client (reach the cluster)
#   viz     -> pyvis (interactive /graph/view HTML, embedded in the dashboard)
#   ui      -> streamlit (the dashboard -- see docker/entrypoint.sh)
#   rag     -> pypdf + python-multipart (the dashboard's Runbooks tab upload)
RUN pip install --upgrade pip && pip install ".[cluster,viz,ui,rag]"

COPY streamlit_app ./streamlit_app
COPY docker ./docker
RUN chmod +x ./docker/entrypoint.sh

# RCA_PORT is the ONE externally-visible port -- Streamlit binds it directly.
# FastAPI runs behind a Unix domain socket, not any TCP port at all; see
# docker/entrypoint.sh for why (this image runs with --network host).
ENV RCA_HOST=0.0.0.0 \
    RCA_PORT=8080

# Run as a non-root user (matches the Helm securityContext).
RUN useradd -u 10001 -r -s /usr/sbin/nologin appuser
USER 10001

EXPOSE 8080

CMD ["./docker/entrypoint.sh"]
