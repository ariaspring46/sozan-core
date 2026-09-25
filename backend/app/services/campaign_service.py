from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path
from uuid import UUID

from fastapi import HTTPException, status

from app.config import settings
from app.models.user import Asset, Campaign
from app.repositories.campaign_repository import AssetRepository, CampaignRepository, CopyRepository
from app.services.compose_pipeline import compose_campaign_dir, save_brief, zip_out
from app.services.tenant_lock import tenant_file_lock
from app.state_store import read_json, write_json


def _campaign_ids() -> list[str]:
    rows = read_json("campaign-ids.json", [])
    return [str(item) for item in rows] if isinstance(rows, list) else []


def _remember_campaign(campaign_id: UUID) -> None:
    with tenant_file_lock("campaigns"):
        rows = _campaign_ids()
        key = str(campaign_id)
        if key not in rows:
            rows.append(key)
            write_json("campaign-ids.json", rows)


def _owns_campaign(campaign_id: UUID) -> bool:
    return str(campaign_id) in _campaign_ids()


class CampaignService:
    def __init__(
        self,
        campaigns: CampaignRepository,
        assets: AssetRepository,
        copies: CopyRepository,
    ) -> None:
        self.campaigns = campaigns
        self.assets = assets
        self.copies = copies

    def _dir(self, slug: str) -> Path:
        return settings.campaigns_path / slug

    async def list_campaigns(self) -> list[Campaign]:
        allowed = set(_campaign_ids())
        rows = await self.campaigns.list_all()
        return [row for row in rows if str(row.id) in allowed]

    async def get(self, campaign_id: UUID) -> Campaign:
        if not _owns_campaign(campaign_id):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "کمپین پیدا نشد")
        row = await self.campaigns.get(campaign_id)
        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "کمپین پیدا نشد")
        return row

    async def create(
        self,
        *,
        slug: str,
        pillar: str,
        title: str,
        subtitle: str,
        cta: str,
        instagram_caption: str,
        telegram_caption: str,
        whatsapp_caption: str = "",
    ) -> Campaign:
        if await self.campaigns.get_by_slug(slug):
            raise HTTPException(status.HTTP_409_CONFLICT, "این شناسه قبلاً هست")
        folder = self._dir(slug)
        (folder / "raw").mkdir(parents=True, exist_ok=True)
        save_brief(
            folder,
            {
                "pillar": pillar,
                "title": title,
                "subtitle": subtitle,
                "cta": cta,
                "instagram_caption": instagram_caption,
                "telegram_caption": telegram_caption,
                "whatsapp_caption": whatsapp_caption,
            },
        )
        campaign = Campaign(slug=slug, pillar=pillar, title=title, subtitle=subtitle, cta=cta)
        campaign = await self.campaigns.create(campaign)
        _remember_campaign(campaign.id)
        await self.copies.upsert(campaign.id, "instagram", "feed", instagram_caption)
        await self.copies.upsert(campaign.id, "telegram", "channel_post", telegram_caption)
        await self.copies.upsert(campaign.id, "whatsapp", "message", whatsapp_caption)
        await self._index_raw(campaign.id, slug)
        await self._index_out(campaign.id, slug)
        return await self.get(campaign.id)

    async def _index_out(self, campaign_id: UUID, slug: str) -> None:
        out = self._dir(slug) / "out"
        if not out.exists():
            return
        mapping = {
            "ig-feed.png": ("overlay", "instagram", "feed"),
            "ig-story.png": ("overlay", "instagram", "story"),
            "ig-reel.mp4": ("video", "instagram", "reel"),
            "tg-post.png": ("overlay", "telegram", "channel_post"),
            "tg-wide.png": ("overlay", "telegram", "wide"),
            "tg-video.mp4": ("video", "telegram", "wide"),
            "captions.md": ("overlay", "both", "captions"),
        }
        for name, meta in mapping.items():
            path = out / name
            if path.is_file():
                kind, channel, fmt = meta
                await self.assets.add(
                    Asset(
                        campaign_id=campaign_id,
                        kind=kind,
                        channel=channel,
                        format=fmt,
                        rel_path=f"{slug}/out/{name}",
                    )
                )

    async def update_copy(
        self,
        campaign_id: UUID,
        *,
        title: str | None,
        subtitle: str | None,
        cta: str | None,
        instagram_caption: str | None,
        telegram_caption: str | None,
        whatsapp_caption: str | None = None,
    ) -> Campaign:
        campaign = await self.get(campaign_id)
        if title is not None:
            campaign.title = title
        if subtitle is not None:
            campaign.subtitle = subtitle
        if cta is not None:
            campaign.cta = cta
        await self.campaigns.save(campaign)
        folder = self._dir(campaign.slug)
        brief_path = folder / "brief.json"
        brief = json.loads(brief_path.read_text(encoding="utf-8")) if brief_path.exists() else {}
        brief.update(
            {
                "pillar": campaign.pillar,
                "title": campaign.title,
                "subtitle": campaign.subtitle,
                "cta": campaign.cta,
            }
        )
        if instagram_caption is not None:
            brief["instagram_caption"] = instagram_caption
            await self.copies.upsert(campaign.id, "instagram", "feed", instagram_caption)
        if telegram_caption is not None:
            brief["telegram_caption"] = telegram_caption
            await self.copies.upsert(campaign.id, "telegram", "channel_post", telegram_caption)
        if whatsapp_caption is not None:
            brief["whatsapp_caption"] = whatsapp_caption
            await self.copies.upsert(campaign.id, "whatsapp", "message", whatsapp_caption)
        save_brief(folder, brief)
        return await self.get(campaign_id)

    async def save_raw(self, campaign_id: UUID, filename: str, data: bytes) -> Asset:
        campaign = await self.get(campaign_id)
        dest = self._dir(campaign.slug) / "raw" / Path(filename).name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        rel = f"{campaign.slug}/raw/{dest.name}"
        return await self.assets.add(
            Asset(
                campaign_id=campaign.id,
                kind="raw",
                channel="both",
                format="still",
                rel_path=rel,
            )
        )

    def compose_files_sync(self, slug: str) -> dict[str, str]:
        folder = self._dir(slug)
        raw = folder / "raw"
        stills = (
            [path for path in raw.iterdir() if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}]
            if raw.is_dir()
            else []
        )
        if not stills:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "تصویر خام در کمپین نیست")
        audio = settings.audio_bed_path
        return compose_campaign_dir(folder, fonts_dir=settings.fonts_path, audio_bed=audio)

    async def compose(self, campaign_id: UUID) -> Campaign:
        campaign = await self.get(campaign_id)
        produced = await asyncio.to_thread(self.compose_files_sync, campaign.slug)
        await self.assets.delete_generated(campaign.id)
        mapping = {
            "ig-feed": ("overlay", "instagram", "feed"),
            "ig-story": ("overlay", "instagram", "story"),
            "ig-reel": ("video", "instagram", "reel"),
            "tg-post": ("overlay", "telegram", "channel_post"),
            "tg-wide": ("overlay", "telegram", "wide"),
            "tg-video": ("video", "telegram", "wide"),
            "captions": ("overlay", "both", "captions"),
        }
        for key, path in produced.items():
            kind, channel, fmt = mapping.get(key, ("overlay", "both", key))
            rel = str(Path(path).resolve().relative_to(settings.campaigns_path))
            await self.assets.add(
                Asset(campaign_id=campaign.id, kind=kind, channel=channel, format=fmt, rel_path=rel)
            )
        return await self.get(campaign_id)

    async def preview_outputs(self, campaign_id: UUID) -> list[dict]:
        campaign = await self.get(campaign_id)
        out = self._dir(campaign.slug) / "out"
        items: list[dict] = []
        for name, kind in (
            ("ig-feed.png", "image"),
            ("ig-story.png", "image"),
            ("ig-reel.mp4", "video"),
            ("tg-wide.png", "image"),
            ("tg-video.mp4", "video"),
        ):
            path = out / name
            if path.is_file():
                items.append({"kind": kind, "path": path, "name": name})
        return items

    async def export_zip(self, campaign_id: UUID) -> Path:
        campaign = await self.get(campaign_id)
        folder = self._dir(campaign.slug)
        if not (folder / "out").exists():
            await self.compose(campaign_id)
        archive = zip_out(folder)
        rel = str(archive.resolve().relative_to(settings.campaigns_path))
        await self.assets.add(
            Asset(campaign_id=campaign.id, kind="pack", channel="both", format="zip", rel_path=rel)
        )
        return archive

    async def _index_raw(self, campaign_id: UUID, slug: str) -> None:
        raw = self._dir(slug) / "raw"
        if not raw.exists():
            return
        for path in raw.iterdir():
            if path.is_file():
                await self.assets.add(
                    Asset(
                        campaign_id=campaign_id,
                        kind="raw",
                        channel="both",
                        format="still",
                        rel_path=f"{slug}/raw/{path.name}",
                    )
                )

    def resolve_file(self, rel_path: str) -> Path:
        base = settings.campaigns_path
        path = (base / rel_path).resolve()
        if base not in path.parents and path != base:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "مسیر نامعتبر است")
        if not path.is_file():
            raise HTTPException(status.HTTP_404_NOT_FOUND, "فایل نیست")
        return path

    async def import_disk_slug(self, slug: str) -> Campaign:
        folder = self._dir(slug)
        brief_path = folder / "brief.json"
        if not brief_path.exists():
            raise HTTPException(status.HTTP_404_NOT_FOUND, "کمپین روی دیسک نیست")
        brief = json.loads(brief_path.read_text(encoding="utf-8"))
        existing = await self.campaigns.get_by_slug(slug)
        if existing is None:
            return await self.create(
                slug=slug,
                pillar=brief.get("pillar", "local"),
                title=brief.get("title", slug),
                subtitle=brief.get("subtitle", ""),
                cta=brief.get("cta", ""),
                instagram_caption=brief.get("instagram_caption", ""),
                telegram_caption=brief.get("telegram_caption", ""),
                whatsapp_caption=brief.get("whatsapp_caption", ""),
            )
        _remember_campaign(existing.id)
        await self.update_copy(
            existing.id,
            title=brief.get("title"),
            subtitle=brief.get("subtitle"),
            cta=brief.get("cta"),
            instagram_caption=brief.get("instagram_caption"),
            telegram_caption=brief.get("telegram_caption"),
            whatsapp_caption=brief.get("whatsapp_caption"),
        )
        if not existing.assets:
            await self._index_raw(existing.id, slug)
            await self._index_out(existing.id, slug)
        return await self.get(existing.id)


def reset_generated_files(slug: str) -> None:
    folder = settings.campaigns_path / slug
    for name in ("overlays", "out"):
        target = folder / name
        if target.exists():
            shutil.rmtree(target)
