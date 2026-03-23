from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from ..dependencies import get_runtime_state, require_auth
from ..models import Stream
from ..state import RuntimeState

router = APIRouter(prefix="/api/v1/streams", tags=["streams"], dependencies=[Depends(require_auth)])


@router.get("", response_model=list[Stream])
async def list_streams(state: RuntimeState = Depends(get_runtime_state)) -> list[Stream]:
    return list(state.streams.values())


@router.get("/{stream_id}", response_model=Stream)
async def get_stream(stream_id: str, state: RuntimeState = Depends(get_runtime_state)) -> Stream:
    stream = state.streams.get(stream_id)
    if not stream:
        raise HTTPException(status_code=404, detail="stream not found")
    return stream


@router.get("/{stream_id}/http")
async def get_stream_http(stream_id: str, state: RuntimeState = Depends(get_runtime_state)) -> StreamingResponse:
    stream = state.streams.get(stream_id)
    if not stream:
        raise HTTPException(status_code=404, detail="stream not found")

    async def iterator():
        payload = f"STREAM {stream.id} CHANNEL {stream.channel_id}\n".encode()
        for _ in range(5):
            yield payload

    return StreamingResponse(iterator(), media_type="audio/L16")
