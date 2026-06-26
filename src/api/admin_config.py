from __future__ import annotations

import asyncio
import logging
from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from src.config import get_config, save_config
from src.logging import log_buffer

router = APIRouter(prefix="/api/admin", tags=["admin"])
logger = logging.getLogger(__name__)


class ConfigUpdate(BaseModel):
    server: dict | None = None
    sandbox: dict | None = None
    auth: dict | None = None
    security: dict | None = None
    storage: dict | None = None
    logging: dict | None = None
    network: dict | None = None


@router.get("/config")
async def get_admin_config() -> dict:
    """Retrieve active server configurations."""
    cfg = get_config()
    # Serialize, but sanitize sensitive credentials like api_key or jwt_secret
    data = cfg.model_dump()
    if "auth" in data:
        if data["auth"].get("api_key"):
            data["auth"]["api_key"] = "••••••••••••••••"
        if data["auth"].get("jwt_secret"):
            data["auth"]["jwt_secret"] = "••••••••••••••••"
        if data["auth"].get("password"):
            data["auth"]["password"] = "••••••••••••••••"
    return data


@router.patch("/config")
async def patch_admin_config(req: ConfigUpdate) -> dict:
    """Update global configurations dynamically."""
    updates = req.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No updates provided")

    # Skip updates if values are still redacted masks
    if "auth" in updates:
        auth_updates = updates["auth"]
        for key in ["api_key", "jwt_secret", "password"]:
            if auth_updates.get(key) == "••••••••••••••••":
                del auth_updates[key]
        if not auth_updates:
            del updates["auth"]

    try:
        save_config(updates)
        logger.info("Server configuration updated: %s", list(updates.keys()))
        return await get_admin_config()
    except Exception as e:
        logger.error("Failed to update server configuration: %s", e)
        raise HTTPException(status_code=400, detail=f"Invalid configuration: {str(e)}")


@router.websocket("/logs")
async def stream_server_logs(websocket: WebSocket):
    """WebSocket endpoint to stream raw server logs in real-time."""
    await websocket.accept()

    queue: asyncio.Queue[str] = asyncio.Queue()

    # Pre-populate with recent logs
    for log_line in list(log_buffer.buffer):
        await queue.put(log_line)

    def on_new_log(line: str):
        # Fire-and-forget push to async queue
        asyncio.create_task(queue.put(line))

    log_buffer.subscribe(on_new_log)

    try:
        while True:
            # Check for client disconnect while waiting
            line_task = asyncio.create_task(queue.get())
            recv_task = asyncio.create_task(websocket.receive_text())

            done, pending = await asyncio.wait(
                [line_task, recv_task], return_when=asyncio.FIRST_COMPLETED
            )

            for task in pending:
                task.cancel()

            if recv_task in done:
                try:
                    await recv_task
                except Exception:
                    break
            elif line_task in done:
                log_line = await line_task
                await websocket.send_text(log_line)
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.debug("Logs WebSocket connection error: %s", e)
    finally:
        log_buffer.unsubscribe(on_new_log)
