"""متن هایلایت‌های آموزشی اینستاگرام سوزان را با OpenRouter می‌سازد.

اجرا:  OPENROUTER_API_KEY=... python3 generate.py   (مدل: HIGHLIGHT_MODEL، پیش‌فرض google/gemini-2.5-flash)
خروجی: content.json (بعد: python3 render.py)
فقط از facts.txt می‌نویسد؛ هر اسلاید با قاعده‌های لحن و طول بررسی می‌شود و اگر رد شد دوباره خواسته می‌شود.
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
MODEL = os.environ.get("HIGHLIGHT_MODEL", "google/gemini-2.5-flash")
KEY = os.environ.get("OPENROUTER_API_KEY", "").strip()

# هر هایلایت یک بخش از آموزش اپ است: شناسه، نام روی دایرهٔ هایلایت، و موضوعی که مدل باید آموزش بدهد.
SECTIONS = [
    ("start", "شروع", "ورود با شمارهٔ موبایل و کد پیامکی، معرفی کسب‌وکار (نام پیج یا کانال، یا افزودن کالا)، سه قدم تا اولین فروشگاه"),
    ("shop", "فروشگاه", "ساخت فروشگاه در چت: گفتن رنگ و حس، سؤال‌های سوزان پیش از ساخت، «بساز»، ویرایش با زدن روی هر قسمت صفحه، «برگشت»، نشانی اختصاصی و وصل دامنهٔ شخصی"),
    ("products", "کالاها", "خواندن کالا از پیج اینستاگرام یا کانال تلگرام عمومی، افزودن دستی با عکس و قیمت، پیج خصوصی، فروشگاه بدون قیمت، انبار و موجودی"),
    ("studio", "استودیو", "ساخت عکس پست و کپشن جدا برای اینستاگرام، تلگرام و واتساپ از همان چت؛ دانلود یا ارسال با تأیید خودت"),
    ("inbox", "پیام‌ها", "صندوق پیام مشتری: دایرکت اینستاگرام و پیام تلگرام یک‌جا؛ جواب دستی، پیش‌نویس با لحن تو (پرو)، جواب خودکار (پرو مکس) و سپردن کار به تو"),
    ("pay", "پرداخت", "لینک پرداخت کنار جواب مشتری؛ درگاه زرین‌پال یا آیدی‌پی خودت (مستقیم به حسابت، بی‌کارمزد سوزان)، کارت‌به‌کارت با رسید، درگاه سوزان با ۲٪ کارمزد و برداشت به شبا"),
    ("channels", "کانال‌ها", "وصل کردن اینستاگرام با ورود رسمی و بدون پسورد، تلگرام با بات، واتساپ با حساب رسمی کسب‌وکار؛ هر کانال چه کاری می‌کند"),
]

SYSTEM = """تو نویسندهٔ آموزش‌های کوتاه اینستاگرام برای «سوزان» هستی؛ دستیار فروش فروشنده‌های ایرانی.
قاعده‌ها (هیچ استثنایی ندارد):
- فقط از «واقعیت‌ها» استفاده کن. هر چیزی که در واقعیت‌ها نیست ننویس: نه امکان تازه، نه عدد، نه قیمت پلن، نه وعدهٔ فروش یا درآمد.
- مخاطب را «تو» خطاب کن، جمله‌های کوتاه، فارسی روان و گرم، بی‌اصطلاح فنی (نه بیلد، نه هاب، نه OTP، نه API، نه هوش مصنوعی).
- اعداد با رقم فارسی. بی‌ایموجی. بی‌هشتگ.
- اگر امکانی به پلن بستگی دارد، نام پلن را در همان اسلاید بگو.
- هر هایلایت ۴ اسلاید است: اسلاید ۱ می‌گوید این بخش به چه دردت می‌خورد؛ اسلایدهای ۲ و ۳ قدم‌های کار؛ اسلاید ۴ یک نکته یا جواب یک نگرانی رایج.
- عنوان هر اسلاید حداکثر ۲۸ نویسه، متن حداکثر ۱۳۰ نویسه، نکته (اختیاری) حداکثر ۶۰ نویسه.
فقط JSON برگردان، بی‌توضیح:
{"slides":[{"title":"…","body":"…","tip":"…"}]}"""

BANNED = re.compile(r"بیلد|هاب|OTP|API|هوش مصنوعی|درآمد|میلیون|تضمین|#|[0-9]")


def ask(messages: list[dict]) -> str:
    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions",
        data=json.dumps(
            {"model": MODEL, "messages": messages, "temperature": 0.5, "response_format": {"type": "json_object"}}
        ).encode(),
        headers={
            "Authorization": f"Bearer {KEY}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://sozan-core.ir",
            "X-Title": "Sozan highlights",
        },
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        body = json.load(resp)
    return body["choices"][0]["message"]["content"]


def problems(slides: object) -> list[str]:
    if not isinstance(slides, list) or len(slides) != 4:
        return ["دقیقاً ۴ اسلاید لازم است"]
    out = []
    for i, s in enumerate(slides, 1):
        if not isinstance(s, dict):
            out.append(f"اسلاید {i} شیء نیست")
            continue
        title, body, tip = (str(s.get(k) or "").strip() for k in ("title", "body", "tip"))
        if not title or len(title) > 28:
            out.append(f"اسلاید {i}: عنوان خالی یا بیش از ۲۸ نویسه (الان {len(title)})")
        if not body or len(body) > 130:
            out.append(f"اسلاید {i}: متن خالی یا بیش از ۱۳۰ نویسه (الان {len(body)})")
        if len(tip) > 60:
            out.append(f"اسلاید {i}: نکته بیش از ۶۰ نویسه (الان {len(tip)}؛ کوتاه‌ترش کن)")
        bad = BANNED.findall(title + body + tip)
        if bad:
            out.append(f"اسلاید {i}: واژه یا نویسهٔ ممنوع {sorted(set(bad))}")
    return out


def main() -> None:
    if not KEY:
        sys.exit("OPENROUTER_API_KEY تنظیم نشده است.")
    facts = (HERE / "facts.txt").read_text(encoding="utf-8")
    result = {"model": MODEL, "highlights": []}
    for sid, name, topic in SECTIONS:
        messages = [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": f"واقعیت‌ها:\n{facts}\n\nهایلایت «{name}». موضوع: {topic}"},
        ]
        for attempt in range(5):
            raw = ask(messages)
            try:
                slides = json.loads(raw).get("slides")
            except (json.JSONDecodeError, AttributeError):
                slides = None
            issues = problems(slides) if slides is not None else ["JSON معتبر نیست"]
            if not issues:
                break
            messages += [{"role": "assistant", "content": raw}, {"role": "user", "content": "درست کن: " + "؛ ".join(issues)}]
        else:
            sys.exit(f"{name}: بعد از ۵ بار هنوز مشکل دارد: {issues}")
        result["highlights"].append({"id": sid, "name": name, "slides": slides})
        print(f"✓ {name}")
    (HERE / "content.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print("content.json نوشته شد. حالا: python3 render.py")


if __name__ == "__main__":
    main()
