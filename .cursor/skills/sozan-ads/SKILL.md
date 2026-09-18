---
name: sozan-ads
description: >-
  Builds Sozan Instagram and Telegram ad campaigns (Persian copy, stills without
  text, Ken Burns video via compose pipeline). Use when the user asks for a
  campaign, استوری, ریلز, پست تلگرام, تبلیغ اینستاگرام, یا ساخت تصویر/ویدیو تبلیغاتی سوزان.
---

# تبلیغات سوزان

قبل از هر کمپین این فایل‌ها را بخوان: `brand/IDENTITY.md`, `brand/visual.md`, `brand/pillars.md`, `brand/formats.md`. قالب کپشن در `brand/templates/`.

تصویر AI **بدون متن فارسی**. متن را پایپ‌لاین overlay می‌گذارد. لوگو از `brand/logo.png` و کاراکتر از `brand/character.png`.

## جریان

1. بریف یک‌جمله‌ای: هدف، مخاطب، CTA، دقیقاً یک ستون از `pillars.md`.
2. پوشه: `campaigns/<slug-latin>/` با `brief.json` و `raw/`.
3. کپی فارسی جدا برای اینستاگرام و تلگرام (از قالب ستون، سپس اختصاصی کن). در `brief.json` و بعداً `out/captions.md`.
4. ۳ تا ۵ still با ابزار GenerateImage:
   - فید/تلگرام مربعی: `aspect_ratio` `1:1`
   - استوری/ریلز: `9:16` (حداقل یک فریم)
   - عریض تلگرام: `16:9` (اختیاری)
   - فضای داخلی کم‌نور، چوب تیره، نور گرم؛ بدون متن، بدون مغز نئونی.
5. فایل‌ها را در `campaigns/<slug>/raw/` ذخیره کن (`feed-01.png`, `story-01.png`, …).
6. ترکیب:

```bash
cd backend && python scripts/compose_campaign.py --slug <slug>
```

7. به کاربر بده: مسیر `out/`، متن کپشن برای کپی، چک‌لیست انتشار دستی. خودکار پست نکن.

## brief.json

```json
{
  "pillar": "shop",
  "title": "روی سیستم خودت",
  "subtitle": "ابر اجباری در کار نیست",
  "cta": "از همین‌جا شروع کن",
  "instagram_caption": "",
  "telegram_caption": ""
}
```

`slug` فقط حروف لاتین، عدد، خط تیره.
