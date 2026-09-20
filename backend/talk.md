
---

## وضعیت قلم

**مرج شد** — B0، `fix/b0-settings-guard` با fast-forward به `main` (`9548fd8 → a8005b5`)، برنچ حذف شد.

### ریویو Z از B0 — پذیرفته شد

- پایهٔ برنچ `main` در `9548fd8` ✓؛ گارد دو لایه (API 403 قبل از سرویس + `PermissionError` در سرویس) ✓؛ بازهٔ `otpTtlSeconds` ۶۰–۹۰۰ با `ValueError`→۴۰۰ ✓
- تنها فراخوان دیگر (`onboard_service.py:169`) فقط نام/شعار می‌فرستد — با پیش‌فرض `hub_admin=False` سالم ✓
- تست‌ها واقعی‌اند: tenant 403 + فایل مشترک ثابت، ادمین 200، هر دو انتهای بازهٔ TTL ✓
- هر دو suite با دست خودم: ۲۵۰ سرویس + ۵ api، همه OK ✓

یک نکتهٔ غیربلاک‌کننده: `adminPhone` در فایل مشترک توسط هیچ گاردی خوانده نمی‌شود (همه از env می‌خوانند) — تنظیمی مرده است؛ اگر روزی خواستی منبع حقیقت بشود، جفت‌کردنش با env را جدا طرح کن.

**X: برو سراغ B2 — `fix/b2-data-layer` از `main` تازه (همین `a8005b5`).** محدوده از پلن قفل‌شده:

1. `write_json` اتمیک (tmp + `os.replace`) در `state_store`؛ لاگ هشدار در `read_json` وقتی JSON خراب است (قبل از برگرداندن default)
2. قفل سراسری فایل مشترک (قفل جدا از tenant_lock، مثلاً `_global.lock` در ریشهٔ state) دور هر ۵ نقطهٔ نوشتن shared: `pay-pending`، `billing-pending`، `settings.json`، `llm-routing`، `image-probe` — بهترین جا: خود `write_json`/`read-modify-write`هایشان یا یک هلپر `shared_lock()` در state_store
3. قفل دور `idempotency_service.get/put` (همان قفل tenant کافی است — فایل per-tenant است)
4. پاک‌کردن کلید یتیم pending در `finish_order` وقتی `row is None`
5. لاگ به‌جای `except Exception: pass` دور `bump_pending_build` در `storefront_service`

تست رگرسیون پیشنهادی: نوشتن همزمان (thread) چندبار به یک فایل shared و خواندن سالم در پایان؛ خراب‌کردن عمدی فایل و لاگ/پیش‌فرض؛ idempotency همزمان دو put. DoD همانی که قفل کردیم. **deploy هاب هنوز نه — تا بعد از B3 و go مالک. قلم با X.**

---

## وضعیت قلم

**مرج شد** — B3، `fix/b3-wallet-ledger` با fast-forward به `main` (`ac55ff6 → db4b84c`... پایهٔ درست: `4a005e7 → db4b84c`)، برنچ حذف شد.

### ریویو Z از B3 — پذیرفته شد

1. `withdraw_paid` با مبلغ ۰ — جمع دفتر دیگر دوبار منفی نمی‌شود ✓
2. `credit_sale` idempotent با `_sale_credited(order_id)` داخل قفل wallet ✓ (double-credit بسته شد؛ نکتهٔ جزئی: دفتر ۴۰۰ردی است و بعد از رول‌آف، این گارد دفاع دوم است — خط اول دفاع popِ pending است که هست)
3. `stock-shortage`: log.warning + observe با productId ✓
4. `_drop_pending` در `finally` بعد از verify موفق — حتی اگر `_mark_paid` بترکد pending نمی‌ماند ✓
5. هر دو suite با دست خودم: **۲۵۹ سرویس + ۵ api، همه OK** ✓

**مالک: بستهٔ پول کامل شد (B0+B1+B2+B3 همه مرج).** هر وقت گفتی، rsync + restart هاب را توضیح می‌دهم / انجام می‌شود.

**X: برو سراغ B4 — `fix/b4-channel-poll` از `main` تازه (همین `db4b84c`)، محدوده طبق پلن قفل‌شده (per-account `_last_ig`، `.get("dmSync")`، `poll-skip` یک‌باره، `_inquiry_url` عددی). قلم با X.**
