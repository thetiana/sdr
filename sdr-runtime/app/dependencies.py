from fastapi import Depends, Header, HTTPException, Request, status

from .config import Settings, get_settings
from .state import RuntimeState


def get_runtime_state(request: Request) -> RuntimeState:
    return request.app.state.runtime_state


def get_app_settings() -> Settings:
    return get_settings()


def require_auth(
    authorization: str | None = Header(default=None),
    settings: Settings = Depends(get_app_settings),
) -> None:
    if not settings.auth_token:
        return
    expected = f"Bearer {settings.auth_token}"
    if authorization != expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid or missing bearer token")
