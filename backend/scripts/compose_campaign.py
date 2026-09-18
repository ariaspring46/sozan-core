from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings  # noqa: E402
from app.services.compose_pipeline import compose_campaign_dir  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Compose Sozan campaign overlays and Ken Burns video")
    parser.add_argument("--slug", required=True)
    args = parser.parse_args()
    campaign_dir = settings.campaigns_path / args.slug
    audio = settings.audio_bed_path
    produced = compose_campaign_dir(campaign_dir, fonts_dir=settings.fonts_path, audio_bed=audio)
    for key, path in produced.items():
        print(f"{key}\t{path}")


if __name__ == "__main__":
    main()
