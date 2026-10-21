"""Learner accounts: registration, login, and the "who is asking" dependency.

Built on `fastapi-users`, which has been a declared dependency since the first commit and
was never wired up. Rolling our own password hashing and token handling next to an
installed library that does both correctly would be the wrong kind of not-invented-here —
this module is deliberately thin, and everything security-shaped in it is the library's.

**Bearer tokens, not cookies, on purpose.** The learner app renders on the server and
calls this API from Node, so a cookie set on the API's origin would never reach the pages
that need it. The Next.js side holds the token in its own httpOnly cookie and forwards it
as `Authorization: Bearer …` (see `apps/web/src/lib/session.ts`). One session cookie, on
one origin, readable by the server components that do the fetching.

**`/admin` is untouched.** It keeps its own env-credential session login. Learner accounts
and founder access are different problems, and giving the founder's console a second door
that depends on the learner auth stack would only widen what a learner bug can reach.
"""

import uuid

from fastapi import Depends, Request
from fastapi_users import BaseUserManager, FastAPIUsers, UUIDIDMixin, schemas
from fastapi_users.authentication import (
    AuthenticationBackend,
    BearerTransport,
    JWTStrategy,
)
from fastapi_users.db import SQLAlchemyUserDatabase
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from kasauti_api.db.base import get_session
from kasauti_api.db.models import User
from kasauti_api.db.models.users import PreferredLanguage
from kasauti_api.settings import get_settings

# A week. Long enough that a learner mid-preparation is not logged out between study
# sessions, short enough that a leaked token expires without anyone doing anything.
TOKEN_LIFETIME_SECONDS = 60 * 60 * 24 * 7


class UserRead(schemas.BaseUser[uuid.UUID]):
    name: str | None = None
    preferred_language: PreferredLanguage = PreferredLanguage.en


class UserCreate(schemas.BaseUserCreate):
    name: str | None = None
    preferred_language: PreferredLanguage = PreferredLanguage.en


class UserUpdate(schemas.BaseUserUpdate):
    name: str | None = None
    preferred_language: PreferredLanguage | None = None


async def get_user_db(session: AsyncSession = Depends(get_session)):
    yield SQLAlchemyUserDatabase(session, User)


class UserManager(UUIDIDMixin, BaseUserManager[User, uuid.UUID]):
    """Password rules and lifecycle hooks.

    No email is sent on registration or password reset: there is no mail transport in
    this deployment, and a flow that silently does nothing is worse than one that is
    absent. Verification and reset land when a transport does.
    """

    reset_password_token_secret = get_settings().auth_secret
    verification_token_secret = get_settings().auth_secret

    async def validate_password(self, password: str, user: UserCreate | User) -> None:
        from fastapi_users.exceptions import InvalidPasswordException

        if len(password) < 8:
            raise InvalidPasswordException("Password must be at least 8 characters.")
        email = getattr(user, "email", "") or ""
        if email and password.lower() == email.lower():
            raise InvalidPasswordException("Password must not be your email address.")

    async def on_after_register(self, user: User, request: Request | None = None) -> None:
        # Deliberately quiet. A print here would put an email address in the logs.
        return None


async def get_user_manager(user_db=Depends(get_user_db)):
    yield UserManager(user_db)


def get_jwt_strategy() -> JWTStrategy:
    settings = get_settings()
    return JWTStrategy(
        secret=settings.auth_secret, lifetime_seconds=TOKEN_LIFETIME_SECONDS
    )


auth_backend = AuthenticationBackend(
    name="jwt",
    transport=BearerTransport(tokenUrl="api/v1/auth/jwt/login"),
    get_strategy=get_jwt_strategy,
)

fastapi_users = FastAPIUsers[User, uuid.UUID](get_user_manager, [auth_backend])

#: Requires a signed-in, active learner. Everything under /api/v1/practice and /api/v1/me
#: depends on this; the PYQ intelligence endpoints stay public on purpose, because the
#: corpus analysis is the thing worth being found by a search engine.
current_user = fastapi_users.current_user(active=True)
#: Same, but returns None instead of 401 — for endpoints that read better with a
#: signed-out state than with an error.
optional_user = fastapi_users.current_user(active=True, optional=True)


class AuthConfigOut(BaseModel):
    """What the frontend needs to know before showing a login form."""

    registration_open: bool
    token_lifetime_seconds: int


def build_router():
    """Assemble the auth router: register, login, logout, and /users/me."""
    from fastapi import APIRouter

    router = APIRouter(prefix="/api/v1", tags=["auth"])
    router.include_router(
        fastapi_users.get_auth_router(auth_backend), prefix="/auth/jwt"
    )
    router.include_router(
        fastapi_users.get_register_router(UserRead, UserCreate), prefix="/auth"
    )
    router.include_router(
        fastapi_users.get_users_router(UserRead, UserUpdate), prefix="/users"
    )

    @router.get("/auth/config", response_model=AuthConfigOut)
    async def auth_config() -> AuthConfigOut:
        return AuthConfigOut(
            registration_open=True, token_lifetime_seconds=TOKEN_LIFETIME_SECONDS
        )

    return router
