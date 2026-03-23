from fastapi import APIRouter, Depends

from ..dependencies import get_runtime_state, require_auth
from ..models import Activity, ActivityAudio
from ..state import RuntimeState

router = APIRouter(prefix="/api/v1/activities", tags=["activities"], dependencies=[Depends(require_auth)])


@router.get("", response_model=list[Activity])
async def list_activities(state: RuntimeState = Depends(get_runtime_state)) -> list[Activity]:
    return list(state.activities.values())


@router.get("/{activity_id}", response_model=Activity)
async def get_activity(activity_id: str, state: RuntimeState = Depends(get_runtime_state)) -> Activity:
    activity = state.activities.get(activity_id)
    if not activity:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="activity not found")
    return activity


@router.get("/{activity_id}/audio", response_model=ActivityAudio)
async def get_activity_audio(activity_id: str, state: RuntimeState = Depends(get_runtime_state)) -> ActivityAudio:
    state.cleanup_activity_audio()
    audio = state.activity_audio.get(activity_id)
    if not audio:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="activity audio not found or expired")
    return audio
