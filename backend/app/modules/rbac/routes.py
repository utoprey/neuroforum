"""HTTP routes for ``rbac`` / moderation."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.modules.rbac.deps import get_rbac_service
from app.modules.rbac.exceptions import (
    AlreadyBanned,
    BanNotFound,
    CannotBanAdmin,
    InsufficientRole,
)
from app.modules.rbac.schemas import BanCreate, BanLift, BanRead
from app.modules.rbac.service import RbacService
from app.modules.users.deps import get_current_user, require_roles
from app.modules.users.models import Role, User

router = APIRouter(prefix="/moderation/bans", tags=["moderation"])

_mod_or_admin = require_roles(Role.MODERATOR, Role.ADMIN)


@router.post(
    "/",
    response_model=BanRead,
    status_code=status.HTTP_201_CREATED,
    summary="Ban a user (moderator/admin)",
)
async def create_ban(
    payload: BanCreate,
    actor: Annotated[User, Depends(_mod_or_admin)],
    svc: Annotated[RbacService, Depends(get_rbac_service)],
) -> BanRead:
    try:
        ban = await svc.ban_user(actor, payload)
    except InsufficientRole as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)
        ) from exc
    except CannotBanAdmin as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)
        ) from exc
    except AlreadyBanned as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An active ban with the same scope already exists",
        ) from exc
    except BanNotFound as exc:
        # ban_user uses BanNotFound for "target user missing"
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    return BanRead.model_validate(ban)


@router.patch(
    "/{ban_id}/lift",
    response_model=BanRead,
    summary="Lift an existing ban (moderator/admin)",
)
async def lift_ban(
    ban_id: UUID,
    payload: BanLift,
    actor: Annotated[User, Depends(_mod_or_admin)],
    svc: Annotated[RbacService, Depends(get_rbac_service)],
) -> BanRead:
    try:
        ban = await svc.lift_ban(actor, ban_id, payload.reason)
    except InsufficientRole as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)
        ) from exc
    except BanNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    return BanRead.model_validate(ban)


@router.get(
    "/me",
    response_model=list[BanRead],
    summary="Current user's active bans (visible to self)",
)
async def list_my_bans(
    current_user: Annotated[User, Depends(get_current_user)],
    svc: Annotated[RbacService, Depends(get_rbac_service)],
) -> list[BanRead]:
    bans = await svc.list_my_active_bans(current_user.id)
    return [BanRead.model_validate(b) for b in bans]


__all__ = ["router"]
