"""Recent turns and channel facts. The subject of a sentence comes from parse_turn, not from a second scan here.

A short channel follow-up keeps its platform inside channel_tool.
"""

from __future__ import annotations

from app.services.pii_mask import mask_pii

def recent_block(rows: list, n: int = 8) -> str:
    lines = []
    for row in [item for item in rows if isinstance(item, dict)][-n:]:
        if row.get("role") not in {"user", "assistant"}:
            continue
        text = " ".join(str(row.get("text") or "").split())
        if not text:
            continue
        who = "سوزان" if row.get("role") == "assistant" else "فروشنده"
        lines.append(f"{who}: {mask_pii(text)[:200]}")
    return "\n".join(lines)


def facts() -> list[str]:
    from app.services.channel_scan_service import scan_outcome
    from app.services.channel_tool import connected_lines

    lines = connected_lines()
    scanned = scan_outcome()
    if scanned:
        lines.append(scanned)
    lines.append("سوزان پیج عمومی اینستاگرام و کانال عمومی تلگرام را می‌خواند.")
    return lines
