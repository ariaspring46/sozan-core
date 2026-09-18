from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.user import Asset, Campaign, CopyVariant


class CampaignRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_all(self) -> list[Campaign]:
        result = await self.session.execute(
            select(Campaign)
            .options(selectinload(Campaign.assets), selectinload(Campaign.copies))
            .execution_options(populate_existing=True)
            .order_by(Campaign.created_at.desc())
        )
        return list(result.scalars().unique().all())

    async def get(self, campaign_id: UUID) -> Campaign | None:
        result = await self.session.execute(
            select(Campaign)
            .options(selectinload(Campaign.assets), selectinload(Campaign.copies))
            .execution_options(populate_existing=True)
            .where(Campaign.id == campaign_id)
        )
        return result.scalar_one_or_none()

    async def get_by_slug(self, slug: str) -> Campaign | None:
        result = await self.session.execute(
            select(Campaign)
            .options(selectinload(Campaign.assets), selectinload(Campaign.copies))
            .execution_options(populate_existing=True)
            .where(Campaign.slug == slug)
        )
        return result.scalar_one_or_none()

    async def create(self, campaign: Campaign) -> Campaign:
        self.session.add(campaign)
        await self.session.commit()
        return await self.get(campaign.id)

    async def save(self, campaign: Campaign) -> Campaign:
        await self.session.commit()
        return await self.get(campaign.id)


class AssetRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, asset: Asset) -> Asset:
        self.session.add(asset)
        await self.session.commit()
        await self.session.refresh(asset)
        return asset

    async def delete_generated(self, campaign_id: UUID) -> None:
        rows = await self.session.execute(
            select(Asset).where(Asset.campaign_id == campaign_id, Asset.kind.in_(("overlay", "video", "pack")))
        )
        for row in rows.scalars():
            await self.session.delete(row)
        await self.session.commit()


class CopyRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def upsert(self, campaign_id: UUID, channel: str, fmt: str, body: str) -> CopyVariant:
        result = await self.session.execute(
            select(CopyVariant).where(
                CopyVariant.campaign_id == campaign_id,
                CopyVariant.channel == channel,
                CopyVariant.format == fmt,
            )
        )
        row = result.scalar_one_or_none()
        if row is None:
            row = CopyVariant(campaign_id=campaign_id, channel=channel, format=fmt, body=body)
            self.session.add(row)
        else:
            row.body = body
        await self.session.commit()
        await self.session.refresh(row)
        return row
