"""`uv run --project engine python -m exemplar.api` -> serve on settings.engine_host:engine_port (127.0.0.1:8787)."""
from __future__ import annotations

import os

import uvicorn

from exemplar.settings import get_settings

from .app import create_app
from .config import configure_logging


def main() -> None:
    configure_logging(os.environ.get("EXEMPLAR_LOG", "INFO"))
    s = get_settings()
    uvicorn.run(create_app(settings=s), host=s.engine_host, port=s.engine_port, log_level="info")


if __name__ == "__main__":
    main()
