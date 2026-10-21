import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from kasauti_api.db.base import Base


class PreferredLanguage(enum.Enum):
    en = "en"
    hi = "hi"


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    email: Mapped[str | None] = mapped_column(String(320), unique=True)
    # Phone becomes a login identifier in Phase 2 (OTP before payments go live).
    phone: Mapped[str | None] = mapped_column(String(20), unique=True)
    name: Mapped[str | None] = mapped_column(String(200))
    preferred_language: Mapped[PreferredLanguage] = mapped_column(
        Enum(PreferredLanguage, name="preferred_language"), default=PreferredLanguage.en
    )
    hashed_password: Mapped[str | None] = mapped_column(String(1024))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_superuser: Mapped[bool] = mapped_column(Boolean, default=False)  # gates /admin
    # Required by fastapi-users, which owns registration and login (see api/v1/auth.py).
    # Nothing verifies email yet, so it stays False and gates nothing; the column exists
    # because the library's user table contract requires it.
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
