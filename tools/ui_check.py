#!/usr/bin/env python3
"""Static UI/UX checks for the seller panel (frontend/). No npm needed; runs in CI.

Rules (each failure prints file:line and the rule id):
  U1  frontend/app/layout.tsx renders <html lang="fa" dir="rtl">.
  U2  every <img> has an alt attribute (alt="" for decoration).
  U3  every <a target="_blank"> has rel with noopener or noreferrer.
  U4  no console.log / debugger in app/, components/, lib/.
  U5  hex colours only in the design-token files and the allow-list below; use Tailwind tokens elsewhere.
  U6  the API host appears only in lib/api.ts and lib/site-host.ts; pages call api()/getApiBase().
  U7  icon-only <button> (no text child) has aria-label or title.

  python3 tools/ui_check.py          # exit 1 on any violation
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONT = ROOT / "frontend"
SCAN_DIRS = ("app", "components", "lib")
HEX_ALLOWED = {
    "app/globals.css",
    "tailwind.config.js",
    "lib/theme.ts",
    # Decorative scene and the colour-preset palette of the shop editor: colours are the content.
    "components/login-coder-scene.tsx",
    "components/shop-editor.tsx",
}
API_HOST_ALLOWED = {"lib/api.ts", "lib/site-host.ts", "lib/public-plans.ts"}
HEX = re.compile(r"(?<![\w&])#[0-9a-fA-F]{3}(?:[0-9a-fA-F]{3})?(?:[0-9a-fA-F]{2})?\b")


def tags(text: str, name: str):
    """Yield (line, tag_text, rest_of_text) for each <name ...> opening tag, brace-aware."""
    for match in re.finditer(rf"<{name}\b", text):
        depth, i = 0, match.end()
        while i < len(text):
            ch = text[i]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
            elif ch == ">" and depth == 0:
                break
            i += 1
        yield text.count("\n", 0, match.start()) + 1, text[match.start() : i + 1], text[i + 1 :]


def check() -> list[str]:
    problems: list[str] = []
    layout = FRONT / "app" / "layout.tsx"
    if not re.search(r'<html[^>]*lang="fa"[^>]*dir="rtl"', layout.read_text(encoding="utf-8")):
        problems.append("U1 frontend/app/layout.tsx: <html lang=\"fa\" dir=\"rtl\"> missing")
    for folder in SCAN_DIRS:
        for path in sorted((FRONT / folder).rglob("*")):
            if path.suffix not in {".ts", ".tsx", ".css"}:
                continue
            rel = path.relative_to(FRONT).as_posix()
            text = path.read_text(encoding="utf-8")
            if path.suffix == ".tsx":
                for line, tag, _rest in tags(text, "img"):
                    if not re.search(r"\balt\s*=", tag):
                        problems.append(f"U2 {rel}:{line}: <img> without alt")
                for line, tag, _rest in tags(text, "a"):
                    if re.search(r'target\s*=\s*["{]\s*["\']?_blank', tag) and not re.search(r"rel\s*=\s*[\"{][^>]*?(noopener|noreferrer)", tag):
                        problems.append(f"U3 {rel}:{line}: target=_blank without rel=noopener/noreferrer")
                for line, tag, rest in tags(text, "button"):
                    if re.search(r"\baria-label\s*=|\btitle\s*=", tag):
                        continue
                    inner = rest.split("</button>", 1)[0]
                    # Text = anything left after removing child tags: literal words or a {expression}.
                    if not re.sub(r"<[^<>]*?/?>", "", inner).strip():
                        problems.append(f"U7 {rel}:{line}: icon-only <button> without aria-label")
            for n, raw in enumerate(text.splitlines(), 1):
                code = raw.split("//", 1)[0] if path.suffix != ".css" else raw
                if re.search(r"\bconsole\.log\(|\bdebugger\b", code):
                    problems.append(f"U4 {rel}:{n}: console.log/debugger")
                if rel not in HEX_ALLOWED and HEX.search(code):
                    problems.append(f"U5 {rel}:{n}: hex colour outside design tokens ({HEX.search(code).group(0)})")
                if rel not in API_HOST_ALLOWED and "api.sozan-core.ir" in code:
                    problems.append(f"U6 {rel}:{n}: API host hard-coded; use getApiBase()")
    problems.extend(check_keyboard())
    return problems


def check_keyboard() -> list[str]:
    """U8: the Android keyboard resizes the page, and the shell follows the visible viewport.

    The approach in production since PR 26 (2026-10-03, tested with tools/ui_back_probe.mjs on Android sizes):
    `interactive-widget=resizes-content` in the viewport meta, and useAppViewport measures visualViewport against the
    tallest height seen per width (Android shrinks innerHeight too, so innerHeight alone cannot tell the keyboard),
    sets --app-height and toggles `sozan-keyboard`. The earlier viewportFrame/--keyboard-inset variant of this rule
    (32c5d87) described code that never reached main or the hub.
    """
    problems: list[str] = []
    layout = (FRONT / "app" / "layout.tsx").read_text(encoding="utf-8")
    hook = (FRONT / "lib" / "use-app-viewport.ts").read_text(encoding="utf-8")
    css = (FRONT / "app" / "globals.css").read_text(encoding="utf-8")
    if 'interactiveWidget: "resizes-content"' not in layout:
        problems.append("U8 frontend/app/layout.tsx: viewport must use interactiveWidget resizes-content")
    if "visualViewport" not in hook or "tallest" not in hook:
        problems.append("U8 frontend/lib/use-app-viewport.ts: keyboard must be measured against the tallest height per width")
    if "--app-height" not in hook or "sozan-keyboard" not in hook:
        problems.append("U8 frontend/lib/use-app-viewport.ts: --app-height and the sozan-keyboard class must be set")
    if "--app-height" not in css:
        problems.append("U8 frontend/app/globals.css: the shell must size itself from --app-height")
    return problems


def _viewport_frame(vv_height: float, inner_height: float, offset_top: float, vk_height: float, closed_height: float) -> dict:
    """Mirror of viewportFrame in frontend/lib/use-app-viewport.ts."""
    threshold = 120
    vv = round(vv_height)
    inner = round(inner_height)
    top = round(offset_top)
    cap = round(max(inner, vv) * 0.7)
    vk = min(cap, max(0, round(vk_height)))
    closed = round(closed_height) or max(vv, inner)
    vv_inset = max(0, inner - vv - top)
    shrunk = closed - vv
    took = vv_inset > threshold or shrunk > threshold
    inset = 0 if took or vk <= threshold else vk
    opened = took or inset > threshold
    closed_next = max(vv, inner) if vk <= threshold and vv >= closed - 40 else closed
    return {"app": vv, "inset": inset, "open": opened, "closed": closed_next}


def main() -> int:
    problems = check()
    for line in problems:
        print(line)
    print(f"ui_check: {len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
