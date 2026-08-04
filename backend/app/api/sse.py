"""SSE (Server-Sent Events) endpoint for real-time dashboard updates."""

import asyncio
import logging
from fastapi import APIRouter
from sse_starlette.sse import EventSourceResponse

from app.core.incident_manager import add_sse_listener, remove_sse_listener

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["sse"])


@router.get("/sse")
async def sse_stream():
    """
    Server-Sent Events stream.

    The dashboard connects once and receives events:
    - incident_created: new fault detected
    - incident_updated: status change
    - incident_verified: auto-verified by telemetry
    - heartbeat: keep-alive every 15s

    Simpler than WebSockets and works reliably through Render.com's proxy.
    """
    queue = asyncio.Queue()
    add_sse_listener(queue)

    async def event_generator():
        try:
            # Send immediate connect confirmation
            yield {"event": "connected", "data": "SSE stream active"}

            while True:
                try:
                    # Wait for event with timeout (keepalive heartbeat)
                    message = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield {"data": message}
                except asyncio.TimeoutError:
                    # Send keepalive
                    yield {"event": "heartbeat", "data": "ping"}
        except asyncio.CancelledError:
            pass
        finally:
            remove_sse_listener(queue)

    return EventSourceResponse(event_generator())
