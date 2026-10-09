"""Seller-chat tools for the shop's business: orders, the sales report, the catalog, price/stock/discount edits and
replies to customers. Each one registers itself in router_tools with its own handler, card sentence and pre-card check.

A tool takes its arguments from the chat model when the model filled them, else from the seller's sentence. The check,
the card and the run all build the same plan from (arguments, sentence), and the run reads the catalog or the inbox
again, so a confirmed card never writes to a product or a thread that has gone since.
"""

from __future__ import annotations

import re
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.services.router_text import fa_digits, fa_money, fold, price_problem
from app.services.router_tools import Tool, register

TEHRAN = ZoneInfo("Asia/Tehran")
NAMES = frozenset({"orders", "sales_report", "products", "edit_product", "set_discount", "reply_customer"})

_ORDER_FA = {
    "paid": "پرداخت‌شده",
    "pending": "در انتظار پرداخت",
    "awaiting_receipt": "رسید منتظر بررسی",
    "receipt_rejected": "رسید ردشده",
    "failed": "ناموفق",
}
_CHANGE = re.compile(r"(?:ب?کن|کنید|بشه|بشود|شود|بذار|بزار|بگذار|بزن|عوض|تغییر|برسون|بردار|حذف)(?![\u0600-\u06FF])")
_ALL = re.compile(r"(?<![\u0600-\u06FF])(?:همه|همهٔ|همه‌ی|همه ی|کل|تمام)(?![\u0600-\u06FF])")
_OUT_OF_STOCK = re.compile(r"تموم\s*شد|تمام\s*شد|ناموجود|موجود\s*نیست")
_STOCK_ADD = re.compile(r"اضافه|بیشتر|دیگه\s*(?:اومد|رسید|آوردم)|رسید|اومد")
_NO_DISCOUNT = re.compile(r"تخفیف.{0,40}(?:بردار|حذف|برداشته|صفر\s*کن)|بدون\s*تخفیف|تخفیف\s*نخوره")
_PERCENT = re.compile(r"(\d{1,3})\s*(?:درصد|درصدی|٪|%)")
_SALES = re.compile(r"گزارش\s*فروش|فروش(?!گاه|نده).{0,12}(?:امروز|دیروز|هفته|ماه|چقد)|(?:چقدر|چقد|چند).{0,10}(?:فروختم|فروختیم|فروش(?!گاه))|درآمد")
_ORDERS = re.compile(r"سفارش")
_REPLY = re.compile(
    r"(?:^|\s)(?:به|برای)\s+(?P<who>\S+(?:\s+\S+)?)\s+(?:بگو|بنویس|بفرست|پیام\s*بده|جواب\s*بده)(?:\s*(?:که|:))?\s*(?P<text>.+)$"
    r"|(?:جواب|پاسخ)\s+(?P<who2>\S+(?:\s+\S+)?)\s+(?:رو|را)\s+بده(?:\s*(?:که|:))?\s*(?P<text2>.+)$"
)
_POINTER = re.compile(r"(?<![\u0600-\u06FF])(?:اون|همون|همین|این)(?![\u0600-\u06FF])|(?:قیمت|موجودی|تخفیف)ش")
_PAGE = re.compile(r"سایت|صفحه|نشون|نشان|نمایش|مخفی|پنهان|قایم")
_LATEST = frozenset({"آخر", "آخری", "آخرین", "مشتری آخر", "آخرین مشتری", "آخرین نفر"})
_NAME_DROP = frozenset(
    "قیمت قیمتش موجودی موجودیش تعداد تخفیف درصد درصدی رو را به بکن کن کنید بشه بشود شود بذار بزار بگذار بزن بده تومان "
    "تومن هزار میلیون کالا کالای محصول روی از تا عدد دانه عدد عوض تغییر برای و بردار حذف بدون دیگه دیگر اضافه کم "
    "ناموجود تموم تمام شد شده موجود نیست نداریم ش رسید اومد بیشتر بخوره بخورد".split()
)


def _loose(value: str) -> str:
    return fold(value).replace(" ", "")


def _int(value: object) -> int | None:
    if value is None or value == "" or isinstance(value, bool):
        return None
    try:
        return int(float(str(value).translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")).replace(",", "").replace("٬", "")))
    except ValueError:
        return None


def _quote(title: str) -> str:
    return f"«{title}»"


def _ago(at: int, now: float) -> str:
    gap = max(0, int(now) - int(at or 0))
    if gap < 3600:
        return f"{fa_digits(max(1, gap // 60))} دقیقه پیش"
    if gap < 86400:
        return f"{fa_digits(gap // 3600)} ساعت پیش"
    return f"{fa_digits(gap // 86400)} روز پیش"


# ---------------------------------------------------------------- read: orders, sales, catalog


def orders_text(now: float | None = None) -> str:
    from app.services.pay_service import list_orders

    rows = list_orders(limit=400)
    if not rows:
        return "هنوز سفارشی ثبت نشده."
    now = time.time() if now is None else now
    counts: dict[str, int] = {}
    for row in rows:
        status = str(row.get("status") or "pending")
        counts[status] = counts.get(status, 0) + 1
    parts = [f"{fa_digits(counts[key])} {label}" for key, label in _ORDER_FA.items() if counts.get(key)]
    lines = ["سفارش‌ها: " + "، ".join(parts) + "."]
    lines.append("آخرین‌ها:")
    for row in rows[:5]:
        label = _ORDER_FA.get(str(row.get("status") or ""), "در انتظار پرداخت")
        title = str(row.get("title") or "سفارش")[:40]
        lines.append(f"• {title} — {fa_money(row.get('amount'))} تومان — {label} — {_ago(int(row.get('at') or 0), now)}")
    if counts.get("awaiting_receipt"):
        lines.append(f"{fa_digits(counts['awaiting_receipt'])} رسید منتظر تأیید توست؛ از صفحهٔ سفارش‌ها بررسی کن.")
    return "\n".join(lines)


def sales_text(now: float | None = None) -> str:
    from app.services.storefront_service import list_sales

    rows = [row for row in list_sales().get("sales") or [] if str(row.get("status") or "paid") == "paid"]
    now = time.time() if now is None else now
    today = datetime.fromtimestamp(now, TEHRAN).replace(hour=0, minute=0, second=0, microsecond=0)
    windows = (
        ("امروز", today.timestamp()),
        ("۷ روز اخیر", (today - timedelta(days=6)).timestamp()),
        ("۳۰ روز اخیر", (today - timedelta(days=29)).timestamp()),
    )
    lines = []
    for label, start in windows:
        picked = [row for row in rows if int(row.get("at") or 0) >= start]
        total = sum(int(row.get("amount") or 0) for row in picked)
        lines.append(f"فروش {label}: {fa_digits(len(picked))} سفارش، {fa_money(total)} تومان")
    month = [row for row in rows if int(row.get("at") or 0) >= windows[2][1]]
    if not month:
        return "\n".join(lines) + "\nدر ۳۰ روز اخیر فروشی ثبت نشده."
    tally: dict[str, int] = {}
    for row in month:
        title = str(row.get("title") or "").strip()[:30]
        if title:
            tally[title] = tally.get(title, 0) + 1
    best = sorted(tally.items(), key=lambda item: -item[1])[:3]
    if best:
        lines.append("پرفروش‌ترین‌های ۳۰ روز: " + "، ".join(f"{title} ({fa_digits(n)})" for title, n in best))
    return "\n".join(lines)


def _products() -> list[dict]:
    from app.services.storefront_service import list_products

    return [row for row in list_products().get("products") or [] if isinstance(row, dict) and str(row.get("title") or "").strip()]


def _product_line(row: dict) -> str:
    price = int(row.get("price") or 0)
    discount = int(row.get("discount") or 0)
    if price <= 0:
        shown = str(row.get("priceLabel") or "بدون قیمت")
    elif discount:
        shown = f"{fa_money(price)} تومان، با {fa_digits(discount)}٪ تخفیف {fa_money(row.get('finalPrice'))}"
    else:
        shown = f"{fa_money(price)} تومان"
    stock = int(row.get("stock") or 0)
    return f"• {row.get('title')} — {shown} — موجودی {fa_digits(stock)}"


def _name_in(spoken: str) -> str:
    words = []
    for raw in re.split(r"[\s،؛:؟?!.«»\"']+", spoken or ""):
        word = raw.strip()
        if not word or word in _NAME_DROP or re.fullmatch(r"[\d۰-۹٪%,٬.]+", word):
            continue
        words.append(word)
    return " ".join(words)


def _stems(word: str) -> set[str]:
    out = {word}
    for suffix in ("های", "ها", "ای", "ا"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            out.add(word[: -len(suffix)])
    return out


def _name_words(name: str, spoken: str) -> list[set[str]]:
    return [_stems(_loose(word)) for word in (name or _name_in(spoken)).split() if len(_loose(word)) >= 3]


def find_products(name: str, spoken: str = "") -> list[dict]:
    """The catalog rows the seller named: an exact title, else the longest title written in the name or the sentence,
    else the titles holding every word of the name («انگشتر» alone is every ring). A row that holds only some of the
    words is never returned: with «انگشتر فیروزه» gone, «انگشتر نقره» must not take its new price."""
    rows = _products()
    named = _loose(name)
    if named:
        exact = [row for row in rows if _loose(row["title"]) == named]
        if exact:
            return exact[:1]
    for blob in (named, _loose(spoken)):
        inside = [row for row in rows if len(_loose(row["title"])) >= 2 and _loose(row["title"]) in blob] if blob else []
        if inside:
            longest = max(len(_loose(row["title"])) for row in inside)
            return [row for row in inside if len(_loose(row["title"])) == longest]
    words = _name_words(name, spoken)
    if not words:
        return []
    return [row for row in rows if all(any(stem in _loose(row["title"]) for stem in forms) for forms in words)]


def _resolve(name: str, spoken: str) -> list[dict]:
    """find_products, and for «قیمتش» / «اون کالا» the product the chat just talked about."""
    rows = find_products(name, spoken)
    if rows or name or not _POINTER.search(spoken or ""):
        return rows
    from app.services.router_service import _last_product

    hit = _last_product(_products())
    return [hit] if hit else []


def _similar(name: str, spoken: str) -> list[dict]:
    words = _name_words(name, spoken)
    return [row for row in _products() if any(any(stem in _loose(row["title"]) for stem in forms) for forms in words)]


def products_text(query: str = "", spoken: str = "") -> str:
    rows = _products()
    if not rows:
        return "کاتالوگ هنوز کالایی ندارد."
    hits = find_products(query, spoken) if (query or _name_in(spoken)) else []
    if hits:
        return "\n".join(_product_line(row) for row in hits[:8])
    empty = [row for row in rows if int(row.get("stock") or 0) <= 0]
    lines = [f"کاتالوگ {fa_digits(len(rows))} کالا دارد؛ {fa_digits(len(empty))} تا موجودی ندارد."]
    lines += [_product_line(row) for row in rows[:8]]
    if len(rows) > 8:
        lines.append(f"و {fa_digits(len(rows) - 8)} کالای دیگر.")
    return "\n".join(lines)


def discount_text() -> str:
    marked = [row for row in _products() if int(row.get("discount") or 0) > 0]
    if not marked:
        return "الان هیچ کالایی تخفیف ندارد. بگو مثلاً «روی انگشتر فیروزه ۲۰ درصد تخفیف بذار»."
    return "کالاهای با تخفیف:\n" + "\n".join(_product_line(row) for row in marked[:10])


# ---------------------------------------------------------------- write: price and stock


def _which(rows: list[dict], name: str, spoken: str = "") -> str:
    if rows:
        return "کدام کالا؟ " + "، ".join(_quote(str(row.get("title"))) for row in rows[:5])
    if not name:
        return "کدام کالا؟ نامش را همان‌طور که در کاتالوگ است بگو."
    near = _similar(name, spoken)
    hint = (" شبیهش: " + "، ".join(_quote(str(row.get("title"))) for row in near[:4])) if near else ""
    return f"کالای {_quote(name)} را در کاتالوگ پیدا نکردم.{hint}"


def _after(spoken: str, word: str) -> str:
    at = spoken.find(word)
    return spoken[at + len(word):] if at >= 0 else ""


def _edit_values(args: dict, spoken: str) -> tuple[int | None, int | None, int | None]:
    """New price, new stock, and stock to add: the model's arguments first, else the sentence."""
    from app.services.shop_intent_service import _price_toman

    text = spoken or ""
    price = _int(args.get("price"))
    if price is None and "قیمت" in text:
        price = _price_toman(_after(text, "قیمت")) or None
    stock = _int(args.get("stock"))
    add = _int(args.get("addStock"))
    if stock is None and add is None and "موجود" in text and not _OUT_OF_STOCK.search(text):
        number = re.search(r"(\d+)", fold(_after(text, "موجود"))) or re.search(r"(\d+)\s*(?:تا|عدد|دانه|دونه)", fold(text))
        if number and _STOCK_ADD.search(text):
            add = int(number.group(1))
        elif number:
            stock = int(number.group(1))
    elif stock is None and add is None and _OUT_OF_STOCK.search(text):
        stock = 0
    return price, stock, add


def _edit_plan(args: dict, spoken: str) -> dict:
    text = spoken or ""
    price, stock, add = _edit_values(args, text)
    name = str(args.get("product") or "").strip()
    rows = _resolve(name, text)
    if len(rows) != 1:
        return {"problem": _which(rows, name or ("" if _POINTER.search(text) else _name_in(text)), text)}
    row = rows[0]
    if price is None and stock is None and add is None:
        if "موجود" in text:
            return {"problem": f"موجودی {_quote(row['title'])} چند تا شود؟"}
        return {"problem": f"برای {_quote(row['title'])} قیمت یا موجودی تازه را بگو."}
    old_price = int(row.get("price") or 0)
    if price is not None:
        problem = price_problem(text, price) if price > 0 else "قیمت باید بیشتر از صفر باشد."
        if problem:
            return {"problem": problem}
        if old_price and price * 100 < old_price:
            return {"problem": f"{fa_money(price)} تومان برای {_quote(row['title'])}؟ عدد را با «هزار» یا «میلیون» بگو."}
    old_stock = int(row.get("stock") or 0)
    if add is not None:
        stock, add = old_stock + add, None
    if stock is not None and stock < 0:
        return {"problem": "موجودی کمتر از صفر نمی‌شود."}
    patch = {}
    if price is not None and price != old_price:
        patch["price"] = price
    if stock is not None and stock != old_stock:
        patch["stock"] = stock
    if not patch:
        return {"problem": f"{_quote(row['title'])} همین الان {fa_money(old_price)} تومان با موجودی {fa_digits(old_stock)} است."}
    return {"id": str(row.get("id")), "title": str(row["title"]), "patch": patch, "oldPrice": old_price, "oldStock": old_stock}


def _edit_words(plan: dict) -> str:
    parts = []
    if "price" in plan["patch"]:
        parts.append(f"قیمت از {fa_money(plan['oldPrice'])} به {fa_money(plan['patch']['price'])} تومان")
    if "stock" in plan["patch"]:
        parts.append(f"موجودی از {fa_digits(plan['oldStock'])} به {fa_digits(plan['patch']['stock'])}")
    return " و ".join(parts)


def _sync_note() -> str:
    from app.services import catalog_sync_service

    try:
        out = catalog_sync_service.sync_live()
    except Exception:
        return " کاتالوگ عوض شد ولی سایت به‌روز نشد؛ از صفحهٔ کاتالوگ دوباره ذخیره کن."
    if out.get("live"):
        return " روی سایت هم به‌روز شد."
    if out.get("reason") == "no-build-dir":
        return " سایت هنوز ساخته نشده؛ بعد از ساخت همین را نشان می‌دهد."
    return " در ساخت بعدی روی سایت می‌آید."


async def _edit_product(spoken: str, args: dict) -> tuple[str, dict]:
    from app.services import storefront_service

    plan = _edit_plan(args, spoken)
    if plan.get("problem"):
        return plan["problem"], {}
    try:
        storefront_service.update_product(plan["id"], plan["patch"])
    except (KeyError, ValueError) as exc:
        return f"{_quote(plan['title'])} عوض نشد: {exc}", {}
    return f"{_quote(plan['title'])}: {_edit_words(plan)} شد." + _sync_note(), {}


# ---------------------------------------------------------------- write: discount


def _discount_plan(args: dict, spoken: str) -> dict:
    text = spoken or ""
    percent = _int(args.get("percent"))
    if percent is None:
        if _NO_DISCOUNT.search(text):
            percent = 0
        else:
            found = _PERCENT.search(fold(text))
            percent = int(found.group(1)) if found else None
    if percent is None:
        return {"problem": "چند درصد تخفیف؟"}
    if percent < 0 or percent > 90:
        return {"problem": "تخفیف باید بین ۱ تا ۹۰ درصد باشد."}
    name = str(args.get("product") or "").strip()
    every = bool(args.get("all")) or (not name and bool(_ALL.search(text)))
    if every:
        rows = [row for row in _products() if int(row.get("discount") or 0) != percent]
        if not rows:
            return {"problem": "همهٔ کالاها همین الان همین تخفیف را دارند." if _products() else "کاتالوگ هنوز کالایی ندارد."}
        return {"ids": [str(row.get("id")) for row in rows], "titles": [], "percent": percent, "all": True}
    rows = _resolve(name, text)
    if len(rows) != 1:
        if not rows and not name and (not _name_in(text) or _POINTER.search(text)):
            return {"problem": "روی کدام کالا؟ یا بگو «همهٔ کالاها»."}
        return {"problem": _which(rows, name or _name_in(text), text)}
    row = rows[0]
    if int(row.get("discount") or 0) == percent:
        return {"problem": f"{_quote(row['title'])} همین الان {fa_digits(percent)}٪ تخفیف دارد." if percent else f"{_quote(row['title'])} تخفیفی ندارد."}
    return {"ids": [str(row.get("id"))], "titles": [str(row["title"])], "percent": percent, "all": False, "price": int(row.get("price") or 0)}


def _discount_card(plan: dict) -> str:
    percent = plan["percent"]
    if plan["all"]:
        if not percent:
            return f"تخفیف {fa_digits(len(plan['ids']))} کالا برداشته شود؟"
        return f"{fa_digits(percent)}٪ تخفیف روی {fa_digits(len(plan['ids']))} کالا گذاشته شود؟"
    title = _quote(plan["titles"][0])
    if not percent:
        return f"تخفیف {title} برداشته شود؟"
    line = f"{fa_digits(percent)}٪ تخفیف روی {title} گذاشته شود؟"
    if plan.get("price"):
        line += f"\nقیمت {fa_money(plan['price'])} ← {fa_money(plan['price'] * (100 - percent) // 100)} تومان"
    return line


async def _set_discount(spoken: str, args: dict) -> tuple[str, dict]:
    from app.services import storefront_service

    plan = _discount_plan(args, spoken)
    if plan.get("problem"):
        return plan["problem"], {}
    done = 0
    for product_id in plan["ids"]:
        try:
            storefront_service.update_product(product_id, {"discount": plan["percent"]})
            done += 1
        except (KeyError, ValueError):
            continue
    if not done:
        return "تخفیف روی هیچ کالایی ننشست؛ کاتالوگ عوض شده. دوباره بگو.", {}
    what = _quote(plan["titles"][0]) if not plan["all"] else f"{fa_digits(done)} کالا"
    head = f"تخفیف {what} برداشته شد." if not plan["percent"] else f"{fa_digits(plan['percent'])}٪ تخفیف روی {what} نشست."
    return head + _sync_note(), {}


# ---------------------------------------------------------------- write: reply to a customer


def _reply_parts(args: dict, spoken: str) -> tuple[str, str]:
    who = str(args.get("customer") or "").strip().lstrip("@")
    body = str(args.get("text") or "").strip()
    if who and body:
        return who, body
    match = _REPLY.search(spoken or "")
    if match:
        who = who or (match.group("who") or match.group("who2") or "").strip().lstrip("@")
        body = body or (match.group("text") or match.group("text2") or "").strip()
    return who, body.strip(" «»\"'")


def _threads() -> list[dict]:
    from app.services.inbox_service import list_threads

    return [row for row in list_threads().get("threads") or [] if isinstance(row, dict) and row.get("id")]


def find_threads(who: str) -> list[dict]:
    rows = _threads()
    if not rows:
        return []
    if who in _LATEST or _loose(who) in {_loose(item) for item in _LATEST}:
        waiting = [row for row in rows if row.get("lastRole") == "inbound"]
        return (waiting or rows)[:1]
    named = _loose(who)
    if not named:
        return []
    exact = [row for row in rows if _loose(str(row.get("sender") or "")) == named]
    if exact:
        return exact[:1]
    return [row for row in rows if named in _loose(str(row.get("sender") or ""))]


def _reply_plan(args: dict, spoken: str) -> dict:
    who, body = _reply_parts(args, spoken)
    if not _threads():
        return {"problem": "صندوق هنوز گفتگویی ندارد."}
    if not who:
        return {"problem": "برای کدام مشتری؟ نامش را همان‌طور که در صندوق است بگو."}
    rows = find_threads(who)
    if not rows:
        recent = "، ".join(_quote(str(row.get("sender") or "")) for row in _threads()[:4])
        return {"problem": f"در صندوق گفتگویی با {_quote(who)} پیدا نکردم. آخرین‌ها: {recent}"}
    if len(rows) > 1:
        return {"problem": "کدام؟ " + "، ".join(_quote(str(row.get("sender") or "")) for row in rows[:5])}
    if not body:
        return {"problem": f"چه چیزی برای {_quote(str(rows[0].get('sender') or who))} بفرستم؟"}
    row = rows[0]
    return {
        "thread": str(row["id"]),
        "sender": str(row.get("sender") or who),
        "where": str(row.get("platformLabel") or row.get("platform") or "صندوق"),
        "text": body[:1000],
    }


async def _reply_customer(spoken: str, args: dict) -> tuple[str, dict]:
    from app.services import inbox_service

    plan = _reply_plan(args, spoken)
    if plan.get("problem"):
        return plan["problem"], {}
    try:
        await inbox_service.reply(plan["thread"], plan["text"], deliver=True)
    except Exception:
        return f"پیام برای {_quote(plan['sender'])} فرستاده نشد؛ در صندوق با علامت خطا مانده تا دوباره بفرستی.", {}
    return f"پیام برای {_quote(plan['sender'])} در {plan['where']} فرستاده شد.", {}


# ---------------------------------------------------------------- routing the seller's sentence (before the model)


def asks_sales(text: str) -> bool:
    return bool(_SALES.search(text or "")) and not _CHANGE.search(text or "")


def route(spoken: str) -> str:
    """A tool only when the sentence is plainly one of these jobs; anything else goes on to the model."""
    text = spoken or ""
    if "؟" in text or "?" in text:  # a question never opens a write card
        return _read_route(text)
    if _REPLY.search(text) and not re.search(r"پست|کپشن|استوری|تبلیغ|عکس", text):
        who, body = _reply_parts({}, text)
        if body and find_threads(who):
            return "reply_customer"
    if "تخفیف" in text and (_CHANGE.search(text) or "بده" in text) and (_PERCENT.search(fold(text)) or _NO_DISCOUNT.search(text)):
        return "set_discount"
    if not _PAGE.search(text):
        # «قیمت‌ها را پنهان کن» is a page edit. «اضافه» is a new product («هودی را با قیمت ... اضافه کن»), unless it
        # adds stock to a product the catalog already has («۳ تا انگشتر فیروزه رسید، به موجودی اضافه کن»).
        adding = "اضافه" in text
        stocky = "موجود" in text or bool(_OUT_OF_STOCK.search(text))
        if stocky and (not adding or ("موجود" in text and find_products("", text))):
            if _CHANGE.search(text) or _OUT_OF_STOCK.search(text) or _STOCK_ADD.search(text):
                return "edit_product"
        if "قیمت" in text and not adding and _CHANGE.search(text) and _edit_values({}, text)[0] is not None:
            return "edit_product"
    return _read_route(text)


def _read_route(text: str) -> str:
    if _ORDERS.search(text) and not _CHANGE.search(text):
        return "orders"
    if asks_sales(text):
        return "sales_report"
    return ""


async def _orders(spoken: str, args: dict) -> tuple[str, dict]:
    return orders_text(), {}


async def _sales(spoken: str, args: dict) -> tuple[str, dict]:
    return sales_text(), {}


async def _catalog(spoken: str, args: dict) -> tuple[str, dict]:
    return products_text(str(args.get("query") or ""), spoken), {}


def _edit_card(args: dict, spoken: str) -> str:
    plan = _edit_plan(args, spoken)
    return "" if plan.get("problem") else f"{_quote(plan['title'])}: {_edit_words(plan)} شود؟"


def _discount_summary(args: dict, spoken: str) -> str:
    plan = _discount_plan(args, spoken)
    return "" if plan.get("problem") else _discount_card(plan)


def _reply_card(args: dict, spoken: str) -> str:
    plan = _reply_plan(args, spoken)
    if plan.get("problem"):
        return ""
    return f"این پیام برای {_quote(plan['sender'])} در {plan['where']} فرستاده شود؟\n«{plan['text']}»"


def _edit_check(args: dict, spoken: str) -> str:
    return str(_edit_plan(args, spoken).get("problem") or "")


def _discount_check(args: dict, spoken: str) -> str:
    return str(_discount_plan(args, spoken).get("problem") or "")


def _reply_check(args: dict, spoken: str) -> str:
    return str(_reply_plan(args, spoken).get("problem") or "")


def _schema(name: str, description: str, properties: dict | None = None) -> dict:
    return {
        "type": "function",
        "function": {"name": name, "description": description, "parameters": {"type": "object", "properties": properties or {}}},
    }


register(Tool(name="orders", schema=_schema("orders", "سفارش‌های فروشگاه: پرداخت‌شده، منتظر پرداخت، رسید منتظر بررسی."), groups=("sales",), run=_orders))
register(Tool(name="sales_report", schema=_schema("sales_report", "عدد فروش امروز، ۷ و ۳۰ روز اخیر و پرفروش‌ترین کالاها. مشاوره نیست."), groups=("sales",), run=_sales))
register(
    Tool(
        name="products",
        schema=_schema("products", "دیدن قیمت، موجودی و تخفیف کالاهای کاتالوگ.", {"query": {"type": "string"}}),
        groups=("catalog",),
        run=_catalog,
    )
)
register(
    Tool(
        name="edit_product",
        schema=_schema(
            "edit_product",
            "عوض کردن قیمت یا موجودی کالایی که در کاتالوگ هست. کالای تازه add_product است.",
            {
                "product": {"type": "string"},
                "price": {"type": "integer", "description": "تومان"},
                "stock": {"type": "integer"},
                "addStock": {"type": "integer"},
            },
        ),
        level="write",
        rank=0,
        groups=("catalog",),
        run=_edit_product,
        summary=_edit_card,
        check=_edit_check,
    )
)
register(
    Tool(
        name="set_discount",
        schema=_schema(
            "set_discount",
            "درصد تخفیف یک کالا یا همهٔ کالاها. ۰ یعنی برداشتن تخفیف.",
            {"product": {"type": "string"}, "percent": {"type": "integer"}, "all": {"type": "boolean"}},
        ),
        level="write",
        rank=0,
        groups=("catalog",),
        run=_set_discount,
        summary=_discount_summary,
        check=_discount_check,
    )
)
register(
    Tool(
        name="reply_customer",
        schema=_schema(
            "reply_customer",
            "فرستادن حرف فروشنده به یک مشتری در صندوق. متن را از جملهٔ فروشنده بردار و چیزی اضافه نکن.",
            {"customer": {"type": "string"}, "text": {"type": "string"}},
        ),
        level="write",
        rank=0,
        groups=("inbox",),
        run=_reply_customer,
        summary=_reply_card,
        check=_reply_check,
    )
)
