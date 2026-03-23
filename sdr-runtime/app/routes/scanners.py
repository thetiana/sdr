from fastapi import APIRouter, Depends, Response, status

from ..dependencies import get_runtime_state, require_auth
from ..models import Scanner, ScannerCreate, ScannerPatch
from ..state import RuntimeState

router = APIRouter(prefix="/api/v1/scanners", tags=["scanners"], dependencies=[Depends(require_auth)])


@router.get("", response_model=list[Scanner])
async def list_scanners(state: RuntimeState = Depends(get_runtime_state)) -> list[Scanner]:
    return list(state.scanners.values())


@router.post("", response_model=Scanner, status_code=status.HTTP_201_CREATED)
async def create_scanner(req: ScannerCreate, state: RuntimeState = Depends(get_runtime_state)) -> Scanner:
    return await state.create_scanner(req)


@router.get("/{scanner_id}", response_model=Scanner)
async def get_scanner(scanner_id: str, state: RuntimeState = Depends(get_runtime_state)) -> Scanner:
    return state.get_scanner(scanner_id)


@router.patch("/{scanner_id}", response_model=Scanner)
async def patch_scanner(scanner_id: str, patch: ScannerPatch, state: RuntimeState = Depends(get_runtime_state)) -> Scanner:
    return await state.patch_scanner(scanner_id, patch)


@router.delete("/{scanner_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_scanner(scanner_id: str, state: RuntimeState = Depends(get_runtime_state)) -> Response:
    await state.delete_scanner(scanner_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{scanner_id}/start", response_model=Scanner)
async def start_scanner(scanner_id: str, state: RuntimeState = Depends(get_runtime_state)) -> Scanner:
    return await state.set_scanner_running(scanner_id, True)


@router.post("/{scanner_id}/stop", response_model=Scanner)
async def stop_scanner(scanner_id: str, state: RuntimeState = Depends(get_runtime_state)) -> Scanner:
    return await state.set_scanner_running(scanner_id, False)
