#!/usr/bin/env python3
"""زمان‌بندی اتوماسیون تبلیغاتی سوزان.

یک حلقهٔ دائم که هر ۶۰ ثانیه چک می‌کند آیا از آخرین تولید بیشتر از CADENCE_MINUTES
گذشته. اگر بله، یک کمپین برند تولید می‌کند (round-robin ستون‌ها).

اجرای مستقیم یا در systemd/tmux:
    python scripts/schedule.py
"""
from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.generate import run_scheduled, status  # noqa: E402

log = logging.getLogger("promo-schedule")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

CHECK_SECONDS = 60


async def loop() -> None:
    log.info("زمان‌بند اتوماسیون شروع شد. کدنس: %d دقیقه.", status().get("cadenceMinutes"))
    await asyncio.sleep(5)
    while True:
        try:
            result = await run_scheduled()
            if result is None:
                log.debug("هنوز وقت تولید نیست.")
            elif result.get("ok"):
                log.info("کمپین ساخته شد: %s (ستون %s)", result["slug"], result["pillar"])
            else:
                log.warning("تولید ناموفق: %s", result.get("error"))
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("خطا در حلقهٔ زمان‌بندی")
        await asyncio.sleep(CHECK_SECONDS)


def main() -> None:
    try:
        asyncio.run(loop())
    except KeyboardInterrupt:
        log.info("زمان‌بند متوقف شد.")


if __name__ == "__main__":
    main()