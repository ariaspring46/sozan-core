from uuid import UUID

from pydantic import BaseModel, Field


class OtpSendIn(BaseModel):
    phone: str


class OtpVerifyIn(BaseModel):
    phone: str
    code: str


class CampaignCreateIn(BaseModel):
    slug: str = Field(min_length=2, max_length=80, pattern=r"^[a-z0-9-]+$")
    pillar: str
    title: str
    subtitle: str = ""
    cta: str = ""
    instagram_caption: str = ""
    telegram_caption: str = ""
    whatsapp_caption: str = ""


class CampaignUpdateIn(BaseModel):
    title: str | None = None
    subtitle: str | None = None
    cta: str | None = None
    instagram_caption: str | None = None
    telegram_caption: str | None = None
    whatsapp_caption: str | None = None


class AssetOut(BaseModel):
    id: UUID
    kind: str
    channel: str
    format: str
    rel_path: str

    model_config = {"from_attributes": True}


class CopyOut(BaseModel):
    id: UUID
    channel: str
    format: str
    body: str

    model_config = {"from_attributes": True}


class CampaignOut(BaseModel):
    id: UUID
    slug: str
    pillar: str
    title: str
    subtitle: str
    cta: str
    assets: list[AssetOut]
    copies: list[CopyOut]

    model_config = {"from_attributes": True}


class ImportSlugIn(BaseModel):
    slug: str
