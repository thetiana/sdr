from typing import Any

from fastapi import APIRouter, Depends, Response, status

from ..dependencies import get_runtime_state, require_auth
from ..models import Channel, ChannelCreate, ChannelPatch, ChannelValidationRequest
from ..state import RuntimeState

router = APIRouter(prefix="/api/v1/channels", tags=["channels"], dependencies=[Depends(require_auth)])


@router.get("", response_model=list[Channel])
async def list_channels(state: RuntimeState = Depends(get_runtime_state)) -> list[Channel]:
    return list(state.channels.values())


@router.post("", response_model=Channel, status_code=status.HTTP_201_CREATED)
async def create_channel(req: ChannelCreate, state: RuntimeState = Depends(get_runtime_state)) -> Channel:
    return await state.create_channel(req)


@router.post("/validate", response_model=dict[str, Any])
async def validate_channel(req: ChannelValidationRequest, state: RuntimeState = Depends(get_runtime_state)) -> dict[str, Any]:
    return await state.validate_channel(req)


@router.get("/{channel_id}", response_model=Channel)
async def get_channel(channel_id: str, state: RuntimeState = Depends(get_runtime_state)) -> Channel:
    return state.get_channel(channel_id)


@router.patch("/{channel_id}", response_model=Channel)
async def patch_channel(channel_id: str, patch: ChannelPatch, state: RuntimeState = Depends(get_runtime_state)) -> Channel:
    return await state.patch_channel(channel_id, patch)


@router.delete("/{channel_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_channel(channel_id: str, state: RuntimeState = Depends(get_runtime_state)) -> Response:
    await state.delete_channel(channel_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
