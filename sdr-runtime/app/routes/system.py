from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse, Response

from ..config import Settings, get_settings
from ..dependencies import get_runtime_state
from ..metrics import render_metrics
from ..state import RuntimeState

router = APIRouter(tags=["system"])


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok", "timestamp": datetime.now(UTC).isoformat()}


@router.get("/readyz")
async def readyz(state: RuntimeState = Depends(get_runtime_state)) -> JSONResponse:
    if state.ready:
        return JSONResponse({"status": "ready"})
    return JSONResponse({"status": "not_ready", "reason": state.radio_state.last_error}, status_code=503)


@router.get("/metrics")
async def metrics(settings: Settings = Depends(get_settings)) -> Response:
    if not settings.metrics_enabled:
        return Response(status_code=404)
    body, content_type = render_metrics()
    return Response(content=body, media_type=content_type)
