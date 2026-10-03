from __future__ import annotations

from app.services.shop_intent_service import classify_actions

ONBOARDING = "onboarding"
READY_TO_BUILD = "ready-to-build"
BUILDING = "building"
LIVE_CLEAN = "live-clean"
LIVE_DIRTY = "live-dirty"
REBUILDING = "rebuilding"
FAILED = "failed"

BUILD_BUSY = ("running", "queued")
EDIT_TYPES = {
    "edit_llm",
    "set_colors",
    "set_brand",
    "replace_text",
    "delete_text",
    "hero_image",
    "add_product",
    "remove_product",
    "set_header",
    "add_nav_link",
    "create_page",
    "hide_prices",
    "show_prices",
    "catalog_from_page",
    "revert",
}


def shop_state(shop: dict, *, brief_ready: bool) -> str:
    status = str(shop.get("status") or "idle")
    slug = str(shop.get("slug") or "")
    pending = int(shop.get("pendingBuild") or 0)
    if status in BUILD_BUSY:
        return REBUILDING if slug else BUILDING
    if status == "failed":
        return FAILED
    if slug and status == "ready":
        return LIVE_DIRTY if pending > 0 else LIVE_CLEAN
    if brief_ready:
        return READY_TO_BUILD
    return ONBOARDING


def classify_turn(prompt: str, view_target: str = "", view_path: str = "") -> dict:
    actions = classify_actions(prompt, view_target, view_path)
    first = actions[0] if actions else {"type": "answer"}
    kind = str(first.get("type") or "answer")
    if kind in {"reject_foreign", "reply_only"}:
        route = "reject"
    elif kind in {"greet", "answer"}:
        route = "answer"
    elif kind == "ask_clarify":
        route = "clarify"
    elif kind in EDIT_TYPES:
        route = "edit"
    else:
        route = kind
    return {
        "route": route,
        "confidence": 1.0 if kind != "edit_llm" else 0.4,
        "evidence": kind,
        "needsClarification": kind == "ask_clarify",
        "actions": actions,
    }


def bump_site_revision(shop: dict) -> int:
    next_rev = int(shop.get("siteRevision") or 0) + 1
    shop["siteRevision"] = next_rev
    return next_rev
