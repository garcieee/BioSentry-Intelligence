"""ASGI entry point: `uvicorn biosentry.api.main:app`, or `python -m biosentry.api` to fail
fast on an unsafe configuration (see __main__.py)."""

from .app import create_app

app = create_app()
