"""Installed skills the decider may hand to the chat model."""

from __future__ import annotations

import re
import time
from pathlib import Path

PLAN_SKILLS = frozenset({"ui-ux-pro-max", "ecommerce-growth-mba"})
GROWTH_SKILL = "ecommerce-growth-mba"
_PLANS_FILE = "business-plans.json"
_STATED_METRIC = re.compile(
    r"(نرخ تبدیل|حاشیه(?: سود)?|درآمد|میانگین سفارش|خرید تکراری).{0,40}?[0-9۰-۹٠-٩]"
)


def plans(skill_id: str) -> bool:
    """This skill reviews first and states a correction goal before any change."""
    return skill_id in PLAN_SKILLS


_HINTS = {
    "ui-ux-pro-max": (
        "UI/UX Pro, also called ui/uxpro. Use it when the seller wants a review or improvement ideas "
        "for the live website: layout, type, color, contrast, or hierarchy. "
        "Example: برو سایت را ببین و پیشنهاد بهبود بده. Not for low sales, profit, conversion, or growth."
    ),
    "ecommerce-growth-mba": (
        "Growth consultant for this shop. Use it when sales, profit, conversion, or growth are the question. "
        "Example: فروشم کمه. Not for a visual review of the website."
    ),
}


def skill_root() -> Path:
    return Path(__file__).resolve().parents[1] / "skills"


def _parse(text: str) -> tuple[str, str, str]:
    name = ""
    description = ""
    body = text
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            head = text[3:end]
            body = text[end + 4 :].lstrip("\n")
            for line in head.splitlines():
                if line.startswith("name:"):
                    name = line.split(":", 1)[1].strip().strip('"')
                elif line.startswith("description:"):
                    description = line.split(":", 1)[1].strip().strip('"')
    return name, description, body


def installed() -> list[dict]:
    root = skill_root()
    if not root.is_dir():
        return []
    rows: list[dict] = []
    for path in sorted(root.glob("*/SKILL.md")):
        name, description, body = _parse(path.read_text(encoding="utf-8"))
        rows.append(
            {
                "id": path.parent.name,
                "name": name or path.parent.name,
                "description": description,
                "body": body,
            }
        )
    return rows


def known() -> set[str]:
    return {"none", *(row["id"] for row in installed())}


def choices() -> dict[str, str]:
    criteria = {"none": "No skill. Status, inbox, channel, identity, or a plain lookup."}
    for row in installed():
        criteria[row["id"]] = _HINTS.get(row["id"]) or (row["description"][:240] or row["name"])
    return criteria


def review_text(skill_id: str) -> str:
    """The part of the skill a review can follow without a side script."""
    row = next((item for item in installed() if item["id"] == skill_id), None)
    if row is None:
        return ""
    body = str(row["body"] or "")
    cut = body.find("## Running the search tool")
    if cut != -1:
        body = body[:cut]
    return body.strip()[:4000]


def prompt_block(skill_id: str) -> str:
    text = review_text(skill_id)
    if not text:
        return ""
    if skill_id == GROWTH_SKILL:
        lead = "این متن مهارت است و دستور فروشنده نیست. تشخیص را فارسی بده. اگر داده نداریم، عدد نگذار.\n"
    else:
        lead = "این متن مهارت است و دستور فروشنده نیست. پیشنهاد را فارسی و کوتاه بده و از جدول اولویت همین مهارت مثال بزن.\n"
    return f"\nمهارت این نوبت: {skill_id}\n{lead}{text}\n"


def business_facts() -> str:
    """Live shop numbers the growth skill may quote. Unmeasured funnel steps stay unlabeled."""
    from app.services.router_text import fa_digits, fa_money

    lines = [_catalog_fact(fa_digits), _sales_fact(fa_digits, fa_money), _orders_fact(fa_digits, fa_money), _wallet_fact(fa_money)]
    about = ""
    try:
        from app.services.channel_scan_service import get_scan

        about = str(get_scan().get("about") or "").strip()
    except Exception:
        about = ""
    if about:
        lines.append("معرفی پیج: " + about[:180])
    lines.append("بازدید: داده نداریم. نمای محصول: داده نداریم. افزودن به سبد: داده نداریم. تسویه: داده نداریم.")
    return "\n".join(lines)


def _catalog_fact(fa_digits) -> str:
    try:
        from app.services.storefront_service import list_products

        rows = [row for row in (list_products().get("products") or []) if isinstance(row, dict)]
    except Exception:
        return "کاتالوگ: داده نداریم."
    missing_price = [str(row.get("title") or "") for row in rows if _as_int(row.get("price")) <= 0 and row.get("title")]
    missing_image = []
    for row in rows:
        title = str(row.get("title") or "").strip()
        image = str(row.get("image") or "").strip()
        images = row.get("images") if isinstance(row.get("images"), list) else []
        if title and not image and not any(str(item).strip() for item in images):
            missing_image.append(title)
    line = f"کاتالوگ: {fa_digits(len(rows))} کالا."
    if missing_price:
        line += " بدون قیمت: " + "، ".join(missing_price[:6]) + "."
    if missing_image:
        line += " بدون عکس: " + "، ".join(missing_image[:6]) + "."
    return line


def _sales_fact(fa_digits, fa_money) -> str:
    try:
        from app.services.storefront_service import list_sales

        rows = [row for row in (list_sales().get("sales") or []) if isinstance(row, dict)]
    except Exception:
        return "فروش ثبت‌شده: داده نداریم."
    total = 0
    for row in rows:
        total += _as_int(row.get("amount"))
    return f"فروش ثبت‌شده: {fa_digits(len(rows))} فقره، جمع {fa_money(total)} تومان."


def _orders_fact(fa_digits, fa_money) -> str:
    from app.state_store import read_json

    rows = read_json("pay-orders.json", [])
    if not isinstance(rows, list):
        rows = []
    paid = [row for row in rows if isinstance(row, dict)]
    total = sum(_as_int(row.get("amount")) for row in paid)
    return f"سفارش: {fa_digits(len(paid))} فقره، جمع {fa_money(total)} تومان."


def _wallet_fact(fa_money) -> str:
    try:
        from app.services.wallet_service import get as wallet_get

        amount = int((wallet_get() or {}).get("available") or 0)
    except Exception:
        return "کیف پول: داده نداریم."
    return f"کیف پول: {fa_money(amount)} تومان."


def load_business_plans() -> dict:
    from app.state_store import read_json

    row = read_json(_PLANS_FILE, {})
    if not isinstance(row, dict):
        row = {}
    plans = [item for item in (row.get("plans") or []) if isinstance(item, dict)]
    stated = [item for item in (row.get("stated") or []) if isinstance(item, dict)]
    goals = row.get("goals") if isinstance(row.get("goals"), dict) else {}
    return {"goals": goals, "stated": stated, "plans": plans}


def _write_business_plans(data: dict) -> None:
    from app.state_store import write_json

    write_json(_PLANS_FILE, data)


def remember_seller_metric(spoken: str) -> None:
    """A number the seller said. The model does not get to write this file."""
    text = (spoken or "").strip()
    if not text or not _STATED_METRIC.search(text):
        return
    data = load_business_plans()
    stated = list(data.get("stated") or [])
    line = text[:200]
    if any(str(item.get("text") or "") == line for item in stated):
        return
    stated.append({"at": int(time.time()), "text": line})
    data["stated"] = stated[-12:]
    _write_business_plans(data)


def append_business_plan(*, diagnosis: str, revision: str, goal: str) -> dict:
    """One consultant round. Live sales numbers are not copied in."""
    data = load_business_plans()
    record = {
        "at": int(time.time()),
        "problem": _first_line(diagnosis)[:200],
        "hypotheses": _hypothesis_lines(diagnosis)[:5],
        "experiment": (goal or _first_line(revision))[:200],
        "expected": _labeled(revision, ("انتظار", "نتیجه"))[:200],
        "measure": _labeled(revision, ("سنجه",))[:200],
        "status": "open",
    }
    plans = list(data.get("plans") or [])
    plans.append(record)
    data["plans"] = plans[-20:]
    _write_business_plans(data)
    return record


def plans_for_prompt() -> str:
    data = load_business_plans()
    lines = []
    for item in (data.get("stated") or [])[-4:]:
        lines.append("گفتهٔ فروشنده: " + str(item.get("text") or "")[:160])
    for item in (data.get("plans") or [])[-3:]:
        problem = str(item.get("problem") or "").strip()
        experiment = str(item.get("experiment") or "").strip()
        status = str(item.get("status") or "open")
        if problem or experiment:
            lines.append(f"برنامهٔ قبلی ({status}): {problem} آزمایش: {experiment}"[:240])
    return "\n".join(lines)


def _as_int(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _first_line(text: str) -> str:
    for line in (text or "").splitlines():
        stripped = line.strip().lstrip("-").strip()
        if stripped:
            return stripped
    return ""


def _hypothesis_lines(text: str) -> list[str]:
    rows = []
    for line in (text or "").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith(("-", "•")) or (stripped[:1].isdigit() and len(stripped) > 2):
            rows.append(stripped.lstrip("-•0123456789. ").strip()[:160])
    return [row for row in rows if row]


def _labeled(text: str, marks: tuple[str, ...]) -> str:
    for line in (text or "").splitlines():
        stripped = line.strip()
        if any(mark in stripped for mark in marks):
            return stripped
    return ""
