from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from fastapi import HTTPException

from app.config import settings
from app.services.campaign_service import CampaignService
from app.state_store import tenant_scope, write_json


class CampaignImportTests(unittest.TestCase):
    def test_import_rejects_another_sellers_slug(self) -> None:
        import tempfile

        foreign = uuid4()
        repo = SimpleNamespace(get_by_slug=AsyncMock(return_value=SimpleNamespace(id=foreign, assets=[])))
        service = CampaignService(repo, SimpleNamespace(), SimpleNamespace())
        with tempfile.TemporaryDirectory() as raw:
            folder = Path(raw) / "taken-slug"
            folder.mkdir()
            (folder / "brief.json").write_text(
                '{"pillar":"shop","title":"x","subtitle":"","cta":"","instagram_caption":"","telegram_caption":"","whatsapp_caption":""}',
                encoding="utf-8",
            )
            with patch.object(settings, "campaigns_dir", raw), tenant_scope("09128880001"):
                write_json("campaign-ids.json", [])
                with self.assertRaises(HTTPException) as ctx:
                    import asyncio

                    asyncio.run(service.import_disk_slug("taken-slug"))
        self.assertEqual(ctx.exception.status_code, 403)
