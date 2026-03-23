from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import ORJSONResponse

from .config import get_settings
from .dependencies import require_auth
from .logging_utils import configure_logging
from .routes import activities, channels, radio, scanners, streams, system
from .radio_providers import create_radio_provider
from .state import RuntimeState

settings = get_settings()
configure_logging(settings.log_level)


@asynccontextmanager
async def lifespan(app: FastAPI):
    provider = create_radio_provider(settings)
    capabilities, radio_state = provider.startup()
    app.state.radio_provider = provider
    app.state.runtime_state = RuntimeState(settings, capabilities, radio_state)
    stop_event = asyncio.Event()
    last_sample_sequence = -1

    async def housekeeping() -> None:
        while not stop_event.is_set():
            await asyncio.sleep(30)
            app.state.runtime_state.cleanup_activity_audio()

    async def sample_processing() -> None:
        nonlocal last_sample_sequence
        while not stop_event.is_set():
            latest = getattr(provider, "get_latest_samples", lambda: None)()
            if latest is not None:
                sequence, iq_bytes = latest
                if sequence != last_sample_sequence:
                    last_sample_sequence = sequence
                    await app.state.runtime_state.process_iq_samples(iq_bytes)
            await asyncio.sleep(0.05)

    housekeeping_task = asyncio.create_task(housekeeping())
    sample_task = asyncio.create_task(sample_processing())
    try:
        yield
    finally:
        stop_event.set()
        housekeeping_task.cancel()
        sample_task.cancel()
        provider.shutdown()


app = FastAPI(
    title="sdr-runtime API",
    version=settings.app_version,
    default_response_class=ORJSONResponse,
    lifespan=lifespan,
    description="Stateless SDR runtime API for channelized monitoring and operator control.",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(system.router)
app.include_router(radio.router)
app.include_router(channels.router)
app.include_router(scanners.router)
app.include_router(activities.router)
app.include_router(streams.router)


@app.websocket("/api/v1/events/ws")
async def websocket_events(websocket: WebSocket):
    token = settings.auth_token
    if token:
        auth = websocket.headers.get("authorization")
        query_token = websocket.query_params.get("token")
        if auth != f"Bearer {token}" and query_token != token:
            await websocket.close(code=4401)
            return
    await websocket.accept()
    state = websocket.app.state.runtime_state
    queue = await state.event_bus.subscribe()
    try:
        while True:
            event = await queue.get()
            await websocket.send_text(event.model_dump_json())
    except WebSocketDisconnect:
        pass
    finally:
        await state.event_bus.unsubscribe(queue)


@app.get("/api/v1/events")
async def event_history(_=Depends(require_auth)):
    return app.state.runtime_state.event_bus.history()


@app.post("/api/v1/debug/channels/{channel_id}/activate")
async def debug_activate(channel_id: str, _=Depends(require_auth)):
    return await app.state.runtime_state.simulate_activity(channel_id, True)


@app.post("/api/v1/debug/channels/{channel_id}/idle")
async def debug_idle(channel_id: str, _=Depends(require_auth)):
    return await app.state.runtime_state.simulate_activity(channel_id, False)


@app.post("/api/v1/debug/error")
async def debug_error(message: str, _=Depends(require_auth)):
    return await app.state.runtime_state.emit_error(message)


@app.post("/api/v1/debug/overrun")
async def debug_overrun(message: str, _=Depends(require_auth)):
    return await app.state.runtime_state.emit_overrun(message)
