from fastapi import APIRouter, Depends

from ..dependencies import get_runtime_state, require_auth
from ..models import RadioCapabilities, RadioRetuneRequest, RadioState, RadioStatePatch
from ..state import RuntimeState

router = APIRouter(prefix="/api/v1/radio", tags=["radio"], dependencies=[Depends(require_auth)])


@router.get("/capabilities", response_model=RadioCapabilities)
async def get_capabilities(state: RuntimeState = Depends(get_runtime_state)) -> RadioCapabilities:
    return state.capabilities


@router.get("/state", response_model=RadioState)
async def get_state(state: RuntimeState = Depends(get_runtime_state)) -> RadioState:
    return state.radio_state


@router.patch("/state", response_model=RadioState)
async def patch_state(patch: RadioStatePatch, state: RuntimeState = Depends(get_runtime_state)) -> RadioState:
    return await state.patch_radio_state(patch)


@router.post("/retune", response_model=RadioState)
async def retune(req: RadioRetuneRequest, state: RuntimeState = Depends(get_runtime_state)) -> RadioState:
    return await state.retune(req)
