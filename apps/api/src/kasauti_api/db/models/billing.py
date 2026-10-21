import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from kasauti_api.db.base import Base


class SubscriptionStatus(enum.Enum):
    active = "active"
    past_due = "past_due"
    cancelled = "cancelled"
    expired = "expired"


class PaymentStatus(enum.Enum):
    created = "created"
    authorized = "authorized"
    captured = "captured"
    failed = "failed"
    refunded = "refunded"


class PaymentPurpose(enum.Enum):
    per_evaluation = "per_evaluation"
    subscription = "subscription"


class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    plan_code: Mapped[str] = mapped_column(String(64))
    status: Mapped[SubscriptionStatus] = mapped_column(
        Enum(SubscriptionStatus, name="subscription_status")
    )
    current_period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    current_period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    razorpay_subscription_id: Mapped[str | None] = mapped_column(String(64), unique=True)

    __table_args__ = (Index("ix_subscriptions_user", "user_id"),)


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    razorpay_payment_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    razorpay_order_id: Mapped[str | None] = mapped_column(String(64))
    amount: Mapped[float] = mapped_column(Numeric(10, 2))  # in INR
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    status: Mapped[PaymentStatus] = mapped_column(Enum(PaymentStatus, name="payment_status"))
    purpose: Mapped[PaymentPurpose] = mapped_column(Enum(PaymentPurpose, name="payment_purpose"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (Index("ix_payments_user", "user_id"),)


class EvaluationCredit(Base):
    __tablename__ = "evaluation_credits"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    credits_remaining: Mapped[int] = mapped_column(Integer)
    source_payment_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("payments.id"))

    __table_args__ = (Index("ix_evaluation_credits_user", "user_id"),)
