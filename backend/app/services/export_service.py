from pathlib import Path

from app.services.compose_pipeline import zip_out


class ExportService:
    def pack(self, campaign_dir: Path) -> Path:
        return zip_out(campaign_dir)
