"""Organisation and membership models for team accounts."""

from sqlalchemy import Column, String, Integer, Boolean, DateTime, ForeignKey, Text, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from api.models.user import Base


class Organisation(Base):
    """Organisation / team account."""

    __tablename__ = "organisations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)
    slug = Column(String(100), unique=True, nullable=False, index=True)
    plan = Column(String(50), default="free")
    stripe_customer_id = Column(String(255), default="")
    monthly_credits = Column(Integer, default=1000)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    is_active = Column(Boolean, default=True)

    members = relationship("OrgMember", back_populates="organisation", cascade="all, delete-orphan")


class OrgMember(Base):
    """Membership linking users to organisations with roles."""

    __tablename__ = "org_members"

    id = Column(Integer, primary_key=True, autoincrement=True)
    org_id = Column(Integer, ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    role = Column(String(50), default="member")  # owner, admin, member
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (UniqueConstraint("org_id", "user_id", name="uq_org_member"),)

    organisation = relationship("Organisation", back_populates="members")
    user = relationship("User")
