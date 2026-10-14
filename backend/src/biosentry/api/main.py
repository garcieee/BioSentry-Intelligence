"""ASGI entry point: `uvicorn biosentry.api.main:app` (the server is a CP8 concern)."""

from .app import create_app

app = create_app()
