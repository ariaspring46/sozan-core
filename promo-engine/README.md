# موتور تبلیغاتی سوزان (promo-engine)

سیستم مستقل تولید محتوای تبلیغاتی برای برند سوزان. کاملاً جدا از پروژهٔ `Sozan-Core` —
هیچ وابستگی به `backend/` یا `frontend/` ندارد. دارایی‌های برند، کانفیگ و کد همگی داخل همین پوشه‌اند.

قلب سیستم یک **persona** است: «موجود نماد برند» (فانوس آینده) که از اسناد هویت ساخته می‌شود
و صدای ثابت تولید محتوا را تعیین می‌کند.

## خروجی

هر بار تولید، یک پوشهٔ کمپین در `output/` می‌سازد:

```
output/sozan-{pillar}-{timestamp}/
├── brief.json          # تیتر، زیرتیتر، CTA، کپشن‌ها
├── raw/                # تصاویر خام برند (character + avatar)
├── out/
│   ├── ig-feed.png     # فید اینستاگرام (۱۰۸۰×۱۰۸۰)
│   ├── ig-story.png    # استوری اینستاگرام (۱۰۸۰×۱۹۲۰)
│   ├── ig-reel.mp4     # ریلز (Ken Burns، ۸ ثانیه)
│   ├── tg-post.png     # پست تلگرام (۱۰۸۰×۱۰۸۰)
│   ├── tg-wide.png     # کاور عریض تلگرام (۱۹۲۰×۱۰۸۰)
│   ├── tg-video.mp4    # ویدیو تلگرام (۱۹۲۰×۱۰۸۰)
│   └── captions.md     # کپشن‌ها + دربارهٔ سوزان
└── sozan-{pillar}-{ts}.zip
```

سه ستون محتوا: `shop` (فروشگاه در چت)، `gateway` (گیت‌وی ادمین)، `panel` (پنل فروشنده).

## نصب

```bash
cd promo-engine
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # کانفیگ را ویرایش کن
```

### وابستگی‌های سیستمی
- **ffmpeg** — برای ساخت ویدیو. اگر نباشد، تصاویر و کپشن‌ها ساخته می‌شوند ولی ویدیو نه.
- **مدل محلی** — endpoint سازگار با OpenAI روی `LLM_URL` (پیش‌فرض `http://127.0.0.1:9292/v1`).

## کانفیگ (`.env`)

| کلید | پیش‌فرض | توضیح |
|---|---|---|
| `LLM_URL` | `http://127.0.0.1:9292/v1` | endpoint مدل محلی |
| `LLM_MODEL` | `qwen3.5-9b` | نام مدل |
| `LLM_TOKEN` | `sk-local` | توکن (اگر لازم) |
| `BRAND_DIR` | `brand` | پوشهٔ دارایی‌های برند |
| `OUTPUT_DIR` | `output` | خروجی کمپین‌ها |
| `STATE_DIR` | `state` | وضعیت اتوماسیون |
| `FONTS_DIR` | `brand/fonts` | فونت Vazirmatn |
| `AUDIO_BED` | (خالی) | فایل صوتی اختیاری برای ویدیو |
| `CADENCE_MINUTES` | `360` | فاصلهٔ زمانی تولید خودکار (۶ ساعت) |
| `API_PORT` | `8020` | پورت API |

## استفاده

### CLI — تولید دستی

```bash
. .venv/bin/activate

# تولید با ستون خودکار (round-robin)
python scripts/generate.py

# ستون مشخص
python scripts/generate.py --pillar shop

# ستون + حال/قالب
python scripts/generate.py --pillar gateway --mood late-night

# وضعیت
python scripts/generate.py --status

# لیست کمپین‌ها
python scripts/generate.py --list
```

حال‌های موجود: `setup`, `wit`, `panel`, `gateway`, `late-night`, `local`, `privacy`, `shop`.

### زمان‌بندی — تولید خودکار

```bash
python scripts/schedule.py
```

یک حلقهٔ دائم که هر ۶۰ ثانیه چک می‌کند؛ اگر از آخرین تولید بیشتر از `CADENCE_MINUTES`
گذشته باشد، یک کمپین با ستون round-robin تولید می‌کند. مناسب اجرا در tmux یا systemd.

### API

```bash
uvicorn api:app --port 8020
```

| متد | مسیر | توضیح |
|---|---|---|
| `GET` | `/health` | سلامت |
| `GET` | `/persona` | persona ساختاریافتهٔ فانوس |
| `GET` | `/avatar` | تصویر avatar |
| `GET` | `/character` | تصویر کاراکتر |
| `GET` | `/status` | وضعیت اتوماسیون |
| `GET` | `/campaigns` | لیست کمپین‌ها |
| `POST` | `/generate` | تولید: `{pillar?, mood?}` |
| `GET` | `/output/{slug}/{filename}` | فایل تولیدشده |

## موجود نماد برند (persona)

persona از این اسناد ساخته می‌شود (در `brand/`):

- `IDENTITY.md` — لحن، وعده، کاراکتر، مخاطب، ممنوعات، امضا
- `CHARACTER.md` — خلاصهٔ فانوس آینده
- `pillars.md` — سه ستون محتوا (حس + CTA)
- `templates/*.md` — هشت قالب کپشن per حال
- `visual.md` — پالت و قواعد بصری

`engine/persona.py` این‌ها را می‌خواند، یک persona ساختاریافته می‌سازد، و `system_prompt(pillar, mood)`
یک پرامپت فارسی تولید می‌کند که صدای فانوس را در ستون مشخص الزام می‌کند و خروجی JSON با
شِما `{title, subtitle, cta, instagram, telegram, pillar, mood}` می‌طلبد.

## ساختار

```
promo-engine/
├── config.py          # تنظیمات (pydantic-settings)
├── api.py             # API مینیمال (FastAPI)
├── engine/
│   ├── llm.py         # کلاینت مدل محلی
│   ├── persona.py     # موجود نماد برند
│   ├── overlay.py     # تولید تصویر (Pillow)
│   ├── video.py       # ویدیو Ken Burns (ffmpeg)
│   ├── compose.py     # pipeline کمپین
│   └── generate.py    # اتوماسیون تولید + زمان‌بندی
├── scripts/
│   ├── generate.py    # CLI
│   └── schedule.py    # حلقهٔ زمان‌بندی
├── brand/             # دارایی‌های برند (self-contained)
├── output/            # کمپین‌های تولیدشده
└── state/promo.json   # وضعیت اتوماسیون
```