"""Three-turn sales prompt benchmark against the live ornith-phone model."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("GIFT_CODE_SPOKEN", "سوزان سی")
os.environ.setdefault("LLM_URL", "http://127.0.0.1:19292/v1")
os.environ.setdefault("LLM_MODEL", "ornith-phone")

from brain import Brain
from sales import HELLO_LINE, sales_open


TURNS = ("من آرایشگاه دارم", "چجوری شروع کنم", "تخفیف دارید؟")


def main() -> None:
    brain = Brain()
    brain.wait_until_ready(20)
    brain.warm_sales(sales_open(), HELLO_LINE)
    print("warmed")
    for heard in TURNS:
        started = time.monotonic()
        bits = []
        for bit in brain.sales_stream(heard):
            bits.append(bit)
            if len(bits) >= 2:
                break
        took = time.monotonic() - started
        stats = brain.last_sales_stats or {}
        text = " ".join(str(bit.get("sentence") or "") for bit in bits)
        print(
            f"heard={heard!r} first_token={float(stats.get('first_token_s') or 0):.2f} "
            f"elapsed={took:.2f} prompt_n={stats.get('prompt_n')} "
            f"predicted_n={stats.get('predicted_n')} line={text[:80]}"
        )
        brain.commit_assistant(text or "باشه.")


if __name__ == "__main__":
    main()
