from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Set

from fastapi import Header, HTTPException, status


@dataclass
class RequestActor:
    user_id: Optional[int]
    role: str


async def _actor_from_headers(
    x_user_id: Optional[str] = Header(default=None, alias="X-User-Id"),
    x_role: Optional[str] = Header(default=None, alias="X-Role"),
) -> RequestActor:
    user_id: Optional[int] = None
    if x_user_id:
        try:
            user_id = int(str(x_user_id).strip())
        except Exception:
            user_id = None
    role = str(x_role or "admin").strip().lower() or "admin"
    return RequestActor(user_id=user_id, role=role)


def require_roles(*allowed_roles: str):
    allowed: Set[str] = {str(role or "").strip().lower() for role in allowed_roles if str(role or "").strip()}

    async def _dep(
        x_user_id: Optional[str] = Header(default=None, alias="X-User-Id"),
        x_role: Optional[str] = Header(default=None, alias="X-Role"),
    ) -> RequestActor:
        actor = await _actor_from_headers(x_user_id=x_user_id, x_role=x_role)
        if allowed and actor.role not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Acces interzis pentru rolul '{actor.role}'.",
            )
        return actor

    return _dep
