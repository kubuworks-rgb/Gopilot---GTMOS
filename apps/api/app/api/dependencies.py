from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import Header, HTTPException

from apps.api.app.config import settings
from apps.api.app.repositories.fixture import repository


@dataclass(frozen=True)
class Principal:
    user_id: str
    workspace_id: str
    role: str = "owner"


def get_principal(
    x_demo_user: Annotated[str | None, Header()] = None,
    x_workspace_id: Annotated[str | None, Header()] = None,
) -> Principal:
    if not settings.demo_auth_enabled:
        raise HTTPException(status_code=401, detail="Production JWT verification required")
    user_id = x_demo_user or "demo-user"
    workspace_id = x_workspace_id or repository.demo_workspace_id
    try:
        repository.assert_member(user_id, workspace_id)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return Principal(user_id=user_id, workspace_id=workspace_id)
