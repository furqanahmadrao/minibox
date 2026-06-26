"""CLI entry point for running the Minibox server."""

from __future__ import annotations

import uvicorn

from src.config import get_config


def run_server() -> None:
    """Start the Minibox server with uvicorn."""
    config = get_config()
    uvicorn.run(
        "src.main:app",
        host=config.server.host,
        port=config.server.port,
        workers=config.server.workers,
        reload=False,
    )


if __name__ == "__main__":
    run_server()
