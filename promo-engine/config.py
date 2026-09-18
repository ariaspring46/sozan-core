from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(ROOT / ".env"), extra="ignore")

    llm_url: str = "http://127.0.0.1:9292/v1"
    llm_model: str = "qwen3.5-9b"
    llm_token: str = "sk-local"
    brand_dir: str = "brand"
    output_dir: str = "output"
    state_dir: str = "state"
    fonts_dir: str = "brand/fonts"
    audio_bed: str = ""
    cadence_minutes: int = 360
    api_port: int = 8020

    @property
    def has_audio_bed(self) -> bool:
        return bool(self.audio_bed and self.audio_bed.strip())

    @property
    def brand_path(self) -> Path:
        return (ROOT / self.brand_dir).resolve()

    @property
    def output_path(self) -> Path:
        return (ROOT / self.output_dir).resolve()

    @property
    def state_path(self) -> Path:
        return (ROOT / self.state_dir).resolve()

    @property
    def fonts_path(self) -> Path:
        return (ROOT / self.fonts_dir).resolve()

    @property
    def audio_bed_path(self) -> Path | None:
        if not self.has_audio_bed:
            return None
        return (ROOT / self.audio_bed).resolve()

    @property
    def state_file(self) -> Path:
        return self.state_path / "promo.json"


settings = Settings()