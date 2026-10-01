# Z — دستیار صوتی تلفن

<!-- ساخته‌شده با tools/agent_context/build.py؛ دستی ویرایش نکنید. مرزها در tools/agent_context/roles.json -->

گیت‌وی SIP و RTP، STT/TTS، مغز تماس (پشتیبانی و فروش)، ماشین حالت فروش، شبیه‌ساز و ارزیابی، کمپین تماس.

**گزارش:** فقط به ته `voice-agent-talk.md` اضافه کن (`cat >>`)؛ برای دیدن آخرین پیام‌ها فقط `tail -n 60`.

## بودجه (توکن تخمینی)

| بخش | توکن |
|---|---|
| هسته (اول هر کار بخوان) | 30.9k |
| سورس فعال (بخوان فقط آنچه کار لازم دارد) | 78.6k |
| سورس کم‌کاربرد (rare؛ فقط اگر کار نامش را برد) | 21.2k |
| تست‌های مالکیت (فقط تست مربوط را بخوان) | 14.4k |
| مال تو ولی هرگز نخوان | 169.6k |
| سقف کانتکست / رزرو عامل | 128.0k / 30.0k |

## هسته

- `voice-gateway/sales.py` (15.5k)
- `voice-gateway/brain.py` (15.4k)

## مال تو (فقط همین‌ها را ویرایش کن)

- `voice-gateway/`: `main.py` (18.2k), `sales.py` (15.5k), `brain.py` (15.4k), `sip.py` (9.8k), `audio_codec.py` (4.1k), `sozanvoice.md` (3.8k), `meaning.py` (3.3k), `knowledge.py` (3.2k), `heard_bank.py` (2.4k), `campaign_run.py` (1.3k), `voice_status.py` (1.2k), `.env.example` (0.5k)

**کم‌کاربرد (rare)** — مال تو، ولی فقط وقتی کار صریحاً به آن اشاره کند بخوان:

- `voice-gateway/` (10 فایل، 20.8k)
- `voice-gateway/systemd/`: `sozan-voice-llm.service` (0.3k), `sozan-voice.service` (0.1k)

**تست‌ها:** `loopback_test.py`, `test_voice.py`

**مال تو ولی نخوان** (ساختگی/حجیم؛ فقط با اسکریپت عوض کن): `voice-agent-talk.md` (50.4k), `voice-gateway/sales-holdout.jsonl` (4.0k), `voice-gateway/sales-train.jsonl` (115.2k)

## قرارداد بیرون از import (HTTP، فایل، سرویس)

- HTTP به هاب: `GET {SOZAN_API}/billing/plans` (قیمت پلن‌ها؛ صاحب X5، `backend/app/api/billing.py`) و `GET {SOZAN_API}/health` (فیلد `paymentReady`؛ صاحب X5، `backend/app/main.py`).
- llama-swap روی ماشین خانه: فقط اسلات `ornith-phone` و `/v1/audio/speech`، `/v1/embeddings` (bge-m3، فقط خواندنی). به اسلات‌های دیگر و ری‌استارت llama-swap دست نزن.
- فایل DNC: `~/local-ai/config/sozan-dnc.txt`؛ لاگ تماس `~/local-ai/sozan-voice-log/calls.jsonl` (دسترسی 600).

## آنچه از دیگران لازم داری (فایلشان را باز نکن؛ امضا همین‌جاست)

هیچ.

## قرارداد تو با دیگران (بدون هماهنگی امضا را عوض نکن)

هیچ‌کس مستقیم صدا نمی‌زند.

## قاعدهٔ مصرف توکن

1. اول هر کار: همین فایل + فقط فایل‌های «هسته» که به کار مربوط است. فایل بزرگ را با `grep -n` پیدا کن و با `sed -n 'a,bp'` فقط بازه را بخوان.
2. فایل دیگران را باز نکن؛ امضای لازم بالاست. اگر امضا کافی نبود، از صاحبش در فایل گزارشش بپرس.
3. تست: فقط ماژول خودت، مثلاً `python -m unittest app.services.<module>_test`؛ سوییت کامل فقط پیش از PR، و فقط خلاصه: `... 2>&1 | tail -5`.
4. هرگز این‌ها را نخوان: `.zcode/**`, `.cursor/**`, `backend/app/data/router_intent_vectors.json`, `voice-gateway/sales-train.jsonl`, `voice-gateway/sales-holdout.jsonl`, `frontend/package-lock.json`, `frontend/tsconfig.tsbuildinfo`, `docs/ui-audit-live/**`, `docs/festival/**`, `docs/*.patch`, `talk.md`, `sales-agent-talk.md`, `voice-agent-talk.md`, `storefront-talk.md`, `CHANGELOG.md`.
5. خروجی ابزار را کوتاه کن: `| head`، `| tail`، `git diff --stat` پیش از `git diff`.
