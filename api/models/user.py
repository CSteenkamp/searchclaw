"""User and API key database models."""

from sqlalchemy import Column, String, Integer, Boolean, DateTime, ForeignKey, BigInteger
from sqlalchemy.orm import relationship, DeclarativeBase
from sqlalchemy.sql import func
import secrets


class Base(DeclarativeBase):
    pass


class User(Base):
    """User account."""

    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    name = Column(String(255), default="")
    plan = Column(String(50), default="free")  # free, starter, pro, scale, enterprise
    stripe_customer_id = Column(String(255), default="")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    is_active = Column(Boolean, default=True)

    api_keys = relationship("APIKey", back_populates="user", cascade="all, delete-orphan")


class APIKey(Base):
    """API key for authentication."""

    __tablename__ = "api_keys"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    key_prefix = Column(String(20), nullable=False)  # sc_live_ or sc_test_
    key_hash = Column(String(255), nullable=False, unique=True, index=True)
    name = Column(String(255), default="Default")
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    last_used_at = Column(DateTime(timezone=True), nullable=True)

    user = relationship("User", back_populates="api_keys")

    @staticmethod
    def generate_key() -> tuple[str, str]:
        """Generate a new API key. Returns (full_key, prefix)."""
        raw = secrets.token_hex(24)
        prefix = "sc_live_"
        full_key = f"{prefix}{raw}"
        return full_key, prefix


class UsageRecord(Base):
    """Per-request usage tracking."""

    __tablename__ = "usage_records"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    api_key_id = Column(Integer, ForeignKey("api_keys.id"), nullable=False)
    endpoint = Column(String(100), nullable=False)
    credits_used = Column(Integer, default=1)
    cached = Column(Boolean, default=False)
    response_time_ms = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


# Plan limits — single source of truth for all plan configuration
PLAN_LIMITS = {
    "free": {"name": "Free", "monthly_credits": 1000, "rate_per_sec": 1, "price_cents": 0},
    "starter": {"name": "Starter", "monthly_credits": 15000, "rate_per_sec": 5, "price_cents": 1000},
    "pro": {"name": "Pro", "monthly_credits": 100000, "rate_per_sec": 20, "price_cents": 5000},
    "scale": {"name": "Scale", "monthly_credits": 500000, "rate_per_sec": 50, "price_cents": 20000},
    "enterprise": {"name": "Enterprise", "monthly_credits": 999999999, "rate_per_sec": 100, "price_cents": 0},
}
