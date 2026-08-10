from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import Header, HTTPException

from apps.api.app.config import settings
from apps.api.app.repositories.fixture import repository
from apps.api.app.security.tokens import AuthError, verify_bearer_token
from apps.api.app.services.private_alpha import AccessDenied, assert_invited


@dataclass(frozen=True)
class Principal:
    user_id: str
    workspace_id: str
    role: str = "owner"


async def get_principal(
    authorization: Annotated[str | None, Header()] = None,
    x_demo_user: Annotated[str | None, Header()] = None,
    x_workspace_id: Annotated[str | None, Header()] = None,
) -> Principal:
    email: str | None = None
    if settings.auth_mode == "oidc":
        try:
            verified = await verify_bearer_token(authorization)
        except AuthError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        user_id = verified.subject
        claim = verified.claims.get("email")
        email = str(claim) if claim else None
    elif not settings.demo_auth_enabled:
        raise HTTPException(
            status_code=401, detail="Production JWT verification required"
        )
    else:
        user_id = x_demo_user or "demo-user"

    # The invite gate lived only in the live router, so a validly-signed but
    # uninvited identity reached the fixture router unchallenged. Authentication
    # and authorisation are different questions, and both routers must ask both.
    try:
        assert_invited(user_id, email)
    except AccessDenied as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    workspace_id = x_workspace_id or repository.demo_workspace_id
    try:
        repository.assert_member(user_id, workspace_id)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return Principal(user_id=user_id, workspace_id=workspace_id)
