"""FastAPI app: Alertmanager webhook + health endpoints."""

from rca_agent.webhook.app import app, main

__all__ = ["app", "main"]
