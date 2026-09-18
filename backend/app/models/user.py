import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    phone: Mapped[str] = mapped_column(String(11), unique=True, index=True)
    role: Mapped[str] = mapped_column(String(32), default="admin")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Campaign(Base):
    __tablename__ = "campaigns"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    slug: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    pillar: Mapped[str] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(String(120))
    subtitle: Mapped[str] = mapped_column(String(200), default="")
    cta: Mapped[str] = mapped_column(String(80), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    assets: Mapped[list["Asset"]] = relationship(back_populates="campaign", cascade="all, delete-orphan")
    copies: Mapped[list["CopyVariant"]] = relationship(
        back_populates="campaign", cascade="all, delete-orphan"
    )


class Asset(Base):
    __tablename__ = "assets"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    campaign_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("campaigns.id"))
    kind: Mapped[str] = mapped_column(String(24))
    channel: Mapped[str] = mapped_column(String(24))
    format: Mapped[str] = mapped_column(String(32))
    rel_path: Mapped[str] = mapped_column(String(400))

    campaign: Mapped[Campaign] = relationship(back_populates="assets")


class CopyVariant(Base):
    __tablename__ = "copy_variants"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    campaign_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("campaigns.id"))
    channel: Mapped[str] = mapped_column(String(24))
    format: Mapped[str] = mapped_column(String(32))
    body: Mapped[str] = mapped_column(Text, default="")

    campaign: Mapped[Campaign] = relationship(back_populates="copies")
