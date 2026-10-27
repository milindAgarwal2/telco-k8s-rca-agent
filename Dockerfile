FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install dependencies first for better layer caching.
COPY pyproject.toml README.md ./
COPY src ./src

# Install core + cluster + viz extras:
#   cluster -> kubernetes client (reach the cluster)
#   viz     -> pyvis (interactive /graph/view HTML)
RUN pip install --upgrade pip && pip install ".[cluster,viz]"

# Bind to all interfaces inside the container so the published port works.
ENV RCA_HOST=0.0.0.0 \
    RCA_PORT=8080

# Run as a non-root user (matches the Helm securityContext).
RUN useradd -u 10001 -r -s /usr/sbin/nologin appuser
USER 10001

EXPOSE 8080

CMD ["rca-agent"]
