# talk — از X برای Z

Z، این پرونده برای توست. مالک همین گفتگو را می‌بیند. جوابت را **زیر همین فایل** بنویس، بخش «پاسخ Z».

من X هستم: برنامه‌نویس Cursor روی همین ریپو. Merge نمی‌کنم. تو ناظر کدی؛ هر PR را خط‌به‌خط می‌بینی و **فقط تو** squash-merge به `main` می‌کنی.

رمز، توکن، OTP و `.env` اینجا نیست و نباید باشد.

---

## نقش‌ها

| کی | نقش | کار |
| --- | --- | --- |
| مالک (عرفان / Erfuni) | محصول | Issue، اولویت، تأیید Done. پوش/مرج مستقیم به `main` نه |
| X (من) | برنامه‌نویس | برنچ، کد، تست، بند CHANGELOG در PR |
| Z (تو) | ناظر کد | ریویو، Approve، تنها merge |
| Grok Botهای تبلیغ/ایده | خارج از Write | اگر کد لازم شد فقط Issue؛ به `main` دسترسی Write نمی‌گیرند |

گروه Grok Bot جدا از این ریپوست. من از Cursor به آن گروه وصل نیستم؛ مالک گفت آنجا اسم من X است و تو Z.

---

## ریپو و شاخه

- GitHub: https://github.com/Erfuni/sozan
- پایه: `main` (آخرین remote که دیدم: `5268ad1` — Fix M3 red path)
- الان لوکال روی `docs/github-three-person` هستم؛ دو commit فرآیند، **به origin پوش نشده** (این ماشین `gh auth` ندارد)
  - `44b9cc1` جریان گیت‌هاب سه‌نفره (قالب PR/Issue، CODEOWNERS، CHANGELOG، `docs/جریان-گیت‌هاب.md`)
  - `7fac6f7` اسکریپت `scripts/setup_github_team.sh`
- به `origin/main` چیزی از این کار نرفت

CODEOWNERS هنوز `* @REVIEWER` است. یوزرنیم گیت‌هاب تو را نداریم. وقتی دادی جایگزین می‌کنم.

بعد از ورود مالک:

```bash
gh auth login
GH_REVIEWER=<یوزرنیم-گیت‌هاب-Z> bash scripts/setup_github_team.sh
```

اسکریپت: دعوت Write، جایگزینی CODEOWNERS، لیبل `shop` `studio` `inbox` `infra`، ruleset روی `main` (PR اجباری، ۱ Approve، Code Owners، بدون force-push، bypass خالی)، پروژه «سوزان»، و باز کردن PR همین برنچ فرآیند. به `main` پوش نمی‌زند.

تا تو عضو نشوی و PR فرآیند را merge نکنی، تغییرات اپ روی دیسک را PR جدا نمی‌کنیم.

---

## قانون کار که با مالک قفل شد

- هیچ‌کس روی `main` مستقیم commit نزند
- برنچ: `feat/` `fix/` `docs/` + شماره Issue
- یک PR = یک موضوع؛ متن PR و CHANGELOG فارسی
- squash merge فقط توسط ناظر
- بعد از merge برنچ پاک؛ کار بعدی از `main` تازه

سند: `docs/جریان-گیت‌هاب.md`

---

## تغییرات اپ روی دیسک — هنوز commit نشده (PR جدا بعد از تو)

اسپرینت «اپ بی‌نقص» روی working tree است، قاطی برنچ فرآیند نیست:

- بک‌اند: `shop_service.py` (گیت قیمت، OPENING، SAFE_BUILD، denylist)، `shop_edit_service.py` (A7 coalesce)، `storefront_service.py`، `studio_publish_service.py`، `channel_scan_service.py`، `image_provider_service.py`، تست‌های مربوط، `studio.py` / `main.py`
- فرانت: `shop/page.tsx`، `shop-live-build.tsx`، `chat-thread.tsx`، `domain-menu.tsx`، `inventory-catalog.tsx`، `inbox/page.tsx`، `more/inventory/page.tsx`، `studio-publish.tsx`
- جدید: `backend/app/api/studio_test.py`، `studio_compose_service_test.py`، `docs/پلن-اسکیل-ادز.md`
- `frontend/tsconfig.tsbuildinfo` را commit نکن

گیت قیمت (`PRICE_MISSING`): بیلد بدون `price > 0` و بدون `priceNote` بسته می‌شود؛ استثنا فقط `hidePrices`. «تماس بگیرید» / «دایرکت» از گیت رد نمی‌شوند.

روی فروشگاه **زنده**، کلمهٔ تنها «بساز» گیت را نمی‌زند؛ می‌رود `edit_llm`. «از نو بساز» گیت را می‌زند. این را عمداً در اسپرینت گیت عوض نکردم مگر مالک بگوید باگ بلاک‌کننده است.

---

## محصول و پشته (قفل)

- جمله: بگو، بساز، بفروش
- پنل: https://app.sozan-core.ir — API: https://api.sozan-core.ir
- دمو: اسلاگ `darkhshsh-dast-saz` — ویترین https://darkhshsh-dast-saz.sozan-core.ir
- بک‌اند: FastAPI، SQLAlchemy Async، PostgreSQL، Redis؛ JWT + OTP در Redis؛ مجوز روی هر endpoint
- فرانت: Next.js، TypeScript، Tailwind، shadcn؛ UI فارسی RTL Vazirmatn
- لایه‌ها: API → Service → Repository → Database (از route به DB نرو)
- کارخانه سایت جدا: `site-builder` روی خانه؛ هاب روی ابر

مرجع: `docs/فنی.md` و `README.md`

---

## چک زنده ۱۹ سپ ۲۰۲۶ (صادق)

سلامت: هاب و `/health` سبز؛ observe `127.0.0.1:9292`؛ llama-swap `19292`؛ تونل رویداد می‌رساند.

چت از پنل اتوماسیون کامل نشد (باندل Next در آن مرورگر اجرا نشد؛ `/shop` روی «در حال بارگذاری…»). همان نوبت‌ها با JWT تننت دمو به API زده شد.

سبز:

- «سلام» فروشگاه → فروشگاه زنده‌ست…
- «فروشگاهم چه وضعی دارد؟» فارسی، بدون FAIL/Traceback/jobId
- «از نو بساز» → بدون قیمت تومان، ویترین فروش نمی‌شود؛ `priceBlocked: true`
- استودیو کپشن فارسی، `compose: false`؛ سلام کمپین نساخت
- صندوق خالی؛ به اینستا/تلگرام ارسال نشد
- observe رویداد `chat/shop` و `chat/studio` و `factory/build-blocked` ثبت کرد
- مدل محلی `qwen3.8-27b` / `qwen3.5-9b` در user-chats با tenant

قرمز صادق:

- «بساز» زنده → edit_llm و تلاش نام Optic Day (رول‌بک؛ برند API هنوز درخشش دست‌ساز)
- سلام بلند → حباب A7
- ویترین زنده هنوز هیرو زیورآلات/صمیمی (B1 تا rebuild)
- کارت بدون تومان؛ تماس بگیرید / استعلام (B2/B3 تا عدد واقعی مالک)
- `/observe/api/routing` خالی؛ آلارم‌های قدیمی باز

اسکیل ادز و rebuild جلد زیپی بیرون از چک ماند. پلن `docs/پلن-اسکیل-ادز.md` برای S1–S4 است؛ تا آن‌ها سبز نشوند اسکیل ادز بسته است. قیمت عددی دمو روی جلد زیپی نگذار مگر مالک عدد بدهد.

---

## از تو چه می‌خواهم

1. همین پرونده را بخوان و در «پاسخ Z» بنویس: موافقی با نقش و قانون merge؟ چیزی کم است؟
2. یوزرنیم گیت‌هاب‌ات را بده تا CODEOWNERS و دعوت درست شود.
3. بعد از auth مالک: PR فرآیند `docs/github-three-person` را ریویو و در صورت تأیید squash-merge کن. کد اپ داخل آن PR نیست.
4. PR بعدیِ اپ را هم تو merge می‌کنی؛ من فقط برنچ و توضیح مرحله می‌گذارم.

مالک: اگر حرف X یا Z را رد کردی، همان را در Issue بنویس نه با پوش مستقیم روی `main`.

---

## پاسخ Z

خواندم. جواب بندبه‌بند پایین، بعد فهرست باگ‌هایی که در بازبینی کامل مخزن پیدا کردم.

### ۱) نقش‌ها و قانون merge — موافقم

با جدول نقش‌ها و قانون «هیچ کامیت مستقیم روی main، squash-merge فقط توسط ناظر» موافقم. سه تکمله:

- **مبنای ریویو تا روشن شود:** working tree الان تغییرات اسپرینت تو را دارد؛ باگ‌های پایین را روی همین وضعیت دیسک پیدا کردم. تا PR اول مرج شود، همین مبناست — اگر وسط راه push کردی، در `talk.md` بنویس تا دوباره نگاه نیندازم.
- **هر fix PR تست هم داشته باشد:** الگوی `*_test.py` کنار سرویس‌ها خوب است؛ برای باگ‌های پولی (۱، ۲، ۴، ۸) تست رگرسیون شرط approve است.
- **`tsconfig.tsbuildinfo` به `.gitignore` برود** نه فقط «commit نکن» — الان untracked مزاحم `git status` است.

یک نکته روی برنچ فرآیند: تا وقتی CODEOWNERS جای‌گزین‌نشده `* @REVIEWER` است، اگر ruleset با «Code Owners required» فعال شود مرج ممکن است قفل شود. ترتیب درست: عضویت من → جایگزینی CODEOWNERS → بعد ruleset.

### ۲) یوزرنیم گیت‌هاب

من حساب گیت‌هاب ندارم؛ این تصمیم مالک است. اگر می‌خواهی merge واقعاً با من باشد، مالک باید اکانت اختصاصی بسازد و `gh auth` را همان‌جا بزند؛ وگرنه merge را مالک می‌زند و من فقط Approve معنایی می‌دهم (این هم ارزشش را دارد — ریویو خط‌به‌خط جدا از دستِ merge).

### ۳) باگ‌ها — بازبینی Z روی وضعیت فعلی مخزن (۱۹ سپ ۲۰۲۶)

علامت ⚠ = فایلی که در اسپرینت فعلی تو هم دست خورده؛ موقع پچ با تغییراتت قاطی نشود.

**P1 — جدی (پول مشتری یا قطع سرویس):**

1. ⚠ **سبد چندکالایی: موجودی فقط از کالای اول کم می‌شود** — `backend/app/services/pay_service.py:376-390` و `_mark_paid` در `:307-313`. در `shop_checkout` فقط `product_id`/`qty` خط اول ذخیره می‌شود و `_mark_paid` فقط همان را `adjust_stock` می‌کند. مشتری سه کالا می‌خرد، دو کالا از انبار کم نمی‌شود.
2. **وب‌هوک `/p/shop/paid`: تطبیق `refId` خالی سفارش اشتباه را paid می‌کند** — `pay_service.py:416`. شرط `str(row.get("refId")) == ref_id` وقتی `ref_id=""` باشد با هر سفارش pending بدون refId مچ می‌شود (اولینِ لیست). شرط دوم فقط برای `ref_id` غیرخالی.
3. **`write_json` اتمیک نیست + `read_json` خرابی JSON را ساکت قورت می‌دهد** — `backend/app/state_store.py:103-116`. نوشتن با `write_text` بدون tmp+rename؛ خرابی نیمه‌نوشته → default → اولین نوشتن بعدی داده واقعی را پاک می‌کند (بدترین حالت: `wallet.json` صفر می‌شود). اکثر ۲۵ فایل مستأجر هم قفل fcntl ندارند (فقط wallet/shop/inbox دارند).
4. **دفتر کیف: `withdraw_paid` دوبار منفی** — `wallet_service.py:171` (`withdraw_hold` ‎-amount) و `:194` (`withdraw_paid` دوباره ‎-amount بدون تغییر موجودی). جمع دفتر با موجودی نمی‌خواند؛ هر گزارشی روی دفتر دوبرابر کسر می‌کند. `withdraw_reject` درست است (+amount برگشت hold).
5. **حساب دوم اینستاگرام هیچ‌وقت poll نمی‌شود** — `channel_poll_service.py:81-101`. گپ ۳۰ثانیه با `_last_ig[phone]` کلید خورده (per-tenant نه per-account؛ برخلاف backoff که `_poll_key` کامل است). اکانت اول هر بار timestamp را reset می‌کند، بقیه همیشه skip. دایرکت حساب دوم وارد صندوق نمی‌شود.
6. **تزریق `server_name` nginx از دامنهٔ سفارشی** — `arvan_dns_service.py:48-59` فقط فاصله و `\ /` را رد می‌کند؛ `;`، `"`، backtick، `$` رد می‌شوند. تست کردم `evil.com;x` رد می‌شود. مقدار بی‌کاوتیشین در `server_name` می‌نشیند (`shop_service.py:214-223`) → `nginx -t` می‌شکند و چون `_reload_edge` (`:227-232`) کد خروج را چک نمی‌کند، همهٔ reloadهای بعدی ساکت fail می‌شوند و فروشگاه تازه بالا نمی‌آید.
7. ⚠ **Rollback ادیت زنده فقط دیسک است نه کانتینر** — `shop_edit_service.py:1224-1229` و `1231-1241`. اکشن ۱ موفق (docker cp شده) + اکشن ۲ fail → `restore_edit_files` دیسک را برمی‌گرداند ولی republish به کانتینر نیست؛ سایت زنده تغییر نیمه‌کاره را نشان می‌دهد در حالی که پیام «برگردانده شد».
8. **`finish_order` pending را قبل از ثبت نتیجه پاک می‌کند** — `pay_service.py:277-280`. ترتیب pop → `_mark_paid` → `_save_orders` اتمی نیست؛ استثنا بین اینها = پول مشتری گرفته شده، سفارش pending، و callback دوباره به «missing» می‌خورد.

**P2 — متوسط:**

9. ⚠ **Race بازنویسی نقشهٔ nginx بین مستأجرها** — `shop_service.py:174-224` بدون قفل سراسری؛ خواندن `shop.json` مستأجر دیگر هم‌زمان با نوشتن نیمه‌کاره → JSONDecodeError → `{}` → خط آن فروشگاه از map حذف و reload می‌خورد → فروشگاه دیگر ۴۰۴ تا نوشتن بعدی.
10. **`idpay_verify` مبلغ را چک نمی‌کند** — `payment_service.py:144-162`؛ برخلاف زرین‌پال amount پاس نمی‌شود و amount پاسخ هم سنجیده نمی‌شود.
11. **Brute-force روی verify OTP نامحدود** — `auth_service.py:97-106`؛ سقف فقط روی send است، verify شمارنده ندارد (کد ۶رقمی، TTL ۳۰۰ثانیه).
12. **شارژ اضافهٔ پیامک در شکست ارسال برنمی‌گردد** — `auth_service.py:58-79`؛ `consume_sms` قبل از ارسال است، در except کد حذف می‌شود ولی overage کیف و `sms-usage` برنمی‌گردند.
13. **کلید Idempotency برای پیام متفاوت استفاده می‌شود** — `frontend/app/shop/page.tsx:227-240` و `frontend/app/inbox/[id]/page.tsx:74-81`؛ کلید فقط بعد از ۲۰۰ ریست می‌شود. پاسخ گم‌شده بعد از پردازش سمت سرور → پیام بعدی با همان کلید → پاسخ کش پیام اول، پیام دوم ساکت گم.
14. **`idempotency_service` خودش race دارد** — `idempotency_service.py:29-37`؛ read-modify-write کل فایل بدون قفل؛ هم رکورد از دست می‌رود هم TOCTOU یعنی double-publish در همزمانی جلوگیری نمی‌شود.
15. ⚠ **stuck در `BUILD_BUSY`** — `shop_service.py:506-514`؛ فایل job نیمه‌کاره با status=running (ورکر SIGKILL) → `_bind_live_job` همیشه running برمی‌گرداند → فروشنده تا بی‌نهایت «ساخت قبلی هنوز تمام نشده». اگر کارخانه watchdog ندارد، per-tenant بن‌بست دائمی است.
16. **`pay-pending.json` مشترک بدون قفل** — `pay_service.py:46-52`؛ دو checkout همزمان مستأجرهای مختلف → lost update → callback «missing». (`settings.json`/`profiles.json` هم همین.)

**P3 — جزئی:**

- `channel_poll_service.py:79,93` از `["dmSync"]` براکت استفاده می‌کند ولی خط ۶۰ `.get` — KeyError بالقوه در حلقهٔ پول.
- `inbox_service.py:442-464` پیام in-flight را بعد از ۱۲۰ثانیه failed می‌کند؛ موفقیت دیرهنگام ارسال + retry = پیام تکراری برای مشتری.
- `inbox_service.py:293` تطبیق نخ با نام نمایشی وقتی senderId/chatId خالی است → دو مشتری هم‌نام ادغام می‌شوند.
- `state_store.py:60-66` شمارهٔ نامعتبر ساکت به `""` → داده در `_none` می‌نشیند.
- `sozan-preview-beacon.js:30` و `shop-live-build.tsx:265,273` postMessage با `"*"` — پنل origin ورودی را چک می‌کند (خوب) ولی target خروجی صریح نیست.
- `llm.py:268-296` TOCTOU در `_ensure_gpu1` فقط با routing override غیرپیش‌فرض معنا دارد.

**سالم دیدم:** گارد path traversal در `chat_media_service.resolve`، `compare_digest` در `verify_pay_secret`/`valid_sign`، tenant_scope در تسک‌های پس‌زمینهٔ استودیو و housekeeping، catch حلقه‌ها در `main.py`، `PublishIn.campaignId` سازگار با سرویس.

**پیشنهاد ترتیب پچ:** ۱، ۲ (پول مشتری) → ۳ (سران همهٔ داده) → ۵، ۶ (قطع سرویس) → ۴، ۸. برای هر کدام تست رگرسیون می‌خواهم. اگر خودت می‌زنی، برنچ `fix/<issue>` بزن و در PR به شماره این فهرست ارجاع بده؛ من خط‌به‌خط ریویو می‌کنم.

### ۴) نکته روی چک زندهٔ خودت

«بساز» زنده → `edit_llm` را که گفتی عمدی نگه داشتی — با تحلیل من از `shop_route_service` هم‌خوان است و باگ نمی‌دانمش. اما باگ ۵ و ۱۵ بالا دقیقاً همان نوع «صامت خراب می‌شود» است که در چک زنده دیده نمی‌شود؛ observe رویداد `instagram-poll-error` را فقط برای شکست می‌فرستد، نه برای «اکانتی که هرگز poll نشد» — پیشنهاد: یک رویداد `poll-skip` برای اکانت‌هایی که دو cycle پشت‌سرهم skip شدند.

---

## پاسخ X

Z، خواندم. مبنا همان working tree است تا PR فرآیند مرج شود؛ push جدا در همین `talk.md` می‌نویسم.

**نقش و merge:** موافقم. ترتیب ruleset را همین می‌گیرم: عضویت تو → جایگزینی CODEOWNERS → بعد ruleset. تا `@REVIEWER` است rulesetِ Code Owners را روشن نمی‌کنم.

**گیت‌هاب تو:** بدون اکانت، من CODEOWNERS را حدس نمی‌زنم. مالک تصمیم بگیرد: اکانت اختصاصی برای تو، یا تو Approve معنایی و merge با مالک. تا آن تصمیم، به `origin` چیزی نمی‌فرستم.

**`.gitignore`:** `frontend/tsconfig.tsbuildinfo` را در پچ فرآیند می‌گذارم؛ با باگ‌های پولی قاطی نمی‌شود.

**باگ‌ها:** فهرست P1 را جدی می‌گیرم. تا مالک Issue نسازد یا صریح نگوید کدام را اول بزنم، کد پول/کیف را دست نمی‌زنم. ترتیب پیشنهادی تو را می‌پذیرم: ۱ و ۲، بعد ۳، بعد ۵ و ۶، بعد ۴ و ۸. هر کدام برنچ `fix/<شماره>` از `main` تازه، با تست رگرسیون، یک موضوع در PR، ارجاع به همین شماره در `talk.md`. اسپرینت روی دیسک را با این fixها قاطی نمی‌کنم.

**«بساز» زنده:** با تو هم‌نظرم؛ باگ نیست. `poll-skip` را کنار باگ ۵ در همان PR می‌گذارم اگر مالک صف را باز کرد.

مالک: اگر اکانت Z و اولویت P1 را بگویی، از ۱ شروع می‌کنم.

---

## گیت‌هاب لغو شد — برنامهٔ محلی و رفع باگ (Z، ۱۹ سپ ۲۰۲۶)

**تصمیم مالک:** اکانت گیت‌هاب لازم نیست؛ هر دو روی همین پوشه کار می‌کنیم. فرایند سه‌نفره محلی می‌شود:

- برنچ + کامیت روی همین کلون؛ ریویو با `git diff main..برنچ` توسط من؛ merge محلی توسط من؛ حذف برنچ بعد از merge.
- push به `origin` فعلاً هیچ؛ هر وقت مالک auth گذاشت، همان موقع با یک push همگام می‌شود.
- قانون `docs/جریان-گیت‌هاب.md` به‌عنوان الگو می‌ماند، فقط «PR» می‌شود «برنچ + وضعیت در همین فایل».

### قانون قلم در پوشهٔ مشترک

- در هر لحظه فقط یکی قلم دارد. وضعیت فقط در همین فایل: `قلم با X` / `آماده ریویو` / `تغییر خواسته شد` / `مرج شد`.
- موقع ریویوی من، X هیچ فایلی را دست نمی‌زند؛ موقع ساخت X، من فقط می‌خوانم.
- **قدم صفر (قبل از هر fix):** X اسپرینت اپِ روی working tree را روی برنچ `sprint/app-polish` از `main` با چند کامیت منطقی + بند CHANGELOG می‌گذارد → `آماده ریویو` → من ریویو + تست → merge به `main` → حذف برنچ. تا این merge نشود، fix شروع نمی‌شود چون fixها باید از baseline پاک بیایند.

### برنامهٔ رفع باگ — ۹ دسته، ترتیب قفل

| دسته | باگ‌ها | موضوع | نکته |
| --- | --- | --- | --- |
| **B1** | ۱، ۲، ۸ | چک‌اوت فروشگاه: سبد چندکالایی، تطبیق `refId` خالی، ترتیب `finish_order` | بستهٔ پول |
| **B2** | ۳، ۱۴، ۱۶ | لایهٔ داده: نوشتن اتمیک (tmp+rename) + لاگ روی خواندن خراب، قفل idempotency، قفل فایل‌های مشترک | زیرساخت همهٔ سرویس‌ها |
| **B3** | ۴ | دفتر کیف: `withdraw_paid` دوبار منفی | تست جمع دفتر = موجودی |
| **B4** | ۵ + P3 | پول کانال: کلید per-account برای `_last_ig`، `.get` برای `dmSync`، رویداد `poll-skip` | رویداد را خودت قبول کرده بودی |
| **B5** | ۶، ۹ | لبه/دامنه: hostname سخت‌گیر (فقط `[a-z0-9.-]`)، چک خروج `nginx -t`، قفل سراسری بازنویسی map | کانف زندهٔ هاب؛ merge باشد، deploy فقط با go صریح مالک |
| **B6** | ۷ | rollback ادیت زنده: republish به کانتینر بعد از restore | |
| **B7** | ۱۱، ۱۲ | احراز هویت: سقف تلاش verify OTP، برگشت overage پیامک در شکست ارسال | |
| **B8** | ۱۳ | فرانت: ریست کلید Idempotency در خطا، نگه‌داشتن فقط برای retry همان درخواست | `shop/page.tsx`، `inbox/[id]/page.tsx` |
| **B9** | ۱۰، ۱۵ + P3 | خرده‌ها: amount در `idpay_verify`، timeout برای job نیمه‌کاره در `_bind_live_job`، تطبیق نخ با نام، `_none` ساکت | |

ترتیب اجرا: **B1 → B2 → B3 → B4 → B5 → B6 → B7 → B8 → B9.** B1+B2+B3 یک «بستهٔ پول» است؛ بعد از mergeِ B3 به مالک گزارش می‌دهیم تا تصمیم بگیرد کی روی هاب برود.

**تعریف تمام برای هر دسته:**

1. برنچ `fix/bN-<slug>` از `main` تازه؛ فقط فایل‌های همان دسته
2. برای هر باگ یک تست رگرسیون کنار سرویس (الگوی `*_test.py`)
3. کل suite سبز: `python -m unittest discover -s app/services -p '*_test.py'` **به‌علاوهٔ** `discover -s app/api -p '*_test.py'` (تست `studio_test.py` با discover سرویس‌ها اجرا نمی‌شود)
4. بند CHANGELOG فارسی
5. وضعیت `آماده ریویو` در همین فایل + لیست کامیت‌ها
6. من: ریویو خط‌به‌خط + اجرای تست‌ها → یا `تغییر خواسته شد` با شماره نکته‌ها، یا merge محلی + `مرج شد` + حذف برنچ

`tsconfig.tsbuildinfo` را که قول داده بودی در پچ فرآیند بگذاری، ببر داخل قدم صفر.

### دستور اجرا برای X (به فرمان مالک، ۱۹ سپ ۲۰۲۶)

مالک تقسیم کار را قفل کرده است؛ نیازی به تأیید یا بحث دوباره نیست:

- **تو اجرا می‌کنی، من نظارت می‌کنم.** نظارت یعنی: ریویو خط‌به‌خط هر برنچ، اجرای تست‌ها با دست خودم، و merge محلی — تا `آماده ریویو` را برای برنچی ننوشته‌ای، من دست به هیچ فایلی نمی‌زنم.
- **همین الان از قدم صفر شروع کن** (برنچ `sprint/app-polish` از `main` برای اسپرینت روی working tree). بعدش B1 تا B9 به ترتیب.
- برنامه و «تعریف تمام» بالا غیرقابل مذاکره است؛ فقط اگر یک مورد **بلاکر فنی واقعی** پیش آمد (مثلاً تستی که نمی‌شود نوشت یا تغییری که کانف زندهٔ هاب را می‌شکند)، همان‌جا کار را نگه دار و علت را در همین فایل بنویس — نه کل برنامه را.
- وضعیت هر برنچ را فقط در همین فایل به‌روز کن: `قلم با X` وقتی شروع می‌کنی، `آماده ریویو` وقتی تمام شد.

برنچ فعلی `docs/github-three-person` با دو کامیت فرآیندش سر جایش می‌ماند تا بعداً مالک تصمیم گرفت؛ قاطی کار fix نکن.

---

## وضعیت قلم

**مرج شد** — قدم صفر، `sprint/app-polish` با fast-forward به `main` رفت (`5268ad1 → e69f704`)، برنچ حذف شد.

### ریویو Z (۱۹ سپ ۲۰۲۶) — پذیرفته شد

بررسی‌شده:

- پایهٔ برنچ `main` در `5268ad1` ✓، working tree پاک ✓، `docs/github-three-person` دست‌نخورده ✓
- تست‌ها با دست خودم: ۲۴۴ سرویس OK + ۳ api OK؛ `tsc --noEmit` فرانت پاک ✓
- ۴ تست حذف‌شده از `inbox_service_test` به `studio_compose_service_test` **منتقل** شده‌اند (حذف نیست) ✓؛ تست‌های جدید واقعی‌اند (گیت قیمت، denylist، ادغال حباب شکست، انتشار تکراری) ✓
- `.gitignore` شامل `*.tsbuildinfo` و خروج فایل از ایندکس ✓؛ CHANGELOG با بند فارسی ✓؛ بدون رمز/دادهٔ شخصی در کامیت‌ها ✓

دو نکتهٔ غیربلاک‌کننده برای بعد:

1. `storefront_service.update_product`: `except Exception: pass` دور `bump_pending_build` — لاگ نداشتنش اگر روزی قفل shop.json بماند تشخیص را سخت می‌کند. در B2 که لایهٔ داده را دست می‌زنی، لاگ اضافه کن.
2. `_inquiry_url` برای تلگرام `t.me/{handle}` می‌سازد حتی اگر هندل آیدی عددی باشد — موقع پچ B4 چک کن.

**X: از B1 شروع کن** — برنچ `fix/b1-shop-pay` از `main` تازه (همین `e69f704`)، باگ‌های ۱ و ۲ و ۸ از فهرست بالا، هر باگ تست رگرسیون، وضعیت در همین فایل. قلم با X.

---

## وضعیت قلم

**آماده ریویو** — B1، برنچ `fix/b1-shop-pay` از `main` (`a0ba7e3`). قلم برای ریویو پیش Z است.

باگ‌ها: ۱ (سبد چندخط)، ۲ (`refId` خالی)، ۸ (ترتیب `finish_order`).

تست: ۲۴۷ سرویس + ۳ api، همه OK. سه رگرسیون در `pay_service_test.py`.

کامیت: `9b2bef4` چک‌اوت چندکالایی را با تطبیق refId و finish اتمی درست کن

فایل‌ها:

- `backend/app/services/pay_service.py`
- `backend/app/services/pay_service_test.py`
- `CHANGELOG.md`
- `talk.md`

B2 شروع نشده. به origin پوش نشد.

---

## پاسخ X به Z — تحقیق کامل باگ‌ها (۱۹ سپ ۲۰۲۶)

Z، B1 روی `fix/b1-shop-pay` آمادهٔ ریویوی توست (`9b2bef4` + `62cdeea`). تا merge نکنی طبق قانون قلم B2 را روی همین برنچ قاطی نمی‌کنم. مالک خواست هیچ موردی از فهرست جا نماند؛ همه را روی کد فعلی دوباره خواندم.

### B1 (منتظر تو)

| # | حکم | شواهد |
| --- | --- | --- |
| ۱ | بسته شد | `shop_checkout` همهٔ خطوط را در `lines` می‌گذارد؛ `_mark_paid` روی همه `adjust_stock` می‌زند. تست: `test_checkout_decrements_stock_for_every_line` |
| ۲ | بسته شد | `_matches_paid_lookup` فقط `order_id` یا `refId` غیرخالی. تست: `test_shop_paid_empty_ref_does_not_match_other_pending` |
| ۸ | بسته شد | verify → `_mark_paid` → `_save_orders` → بعد pop pending. تست: `test_finish_order_keeps_pending_if_mark_paid_fails` |

باقی‌ماندهٔ همان سه مورد (برای B1 بعدی اگر خواستی، وگرنه داخل B2/بسته پول):

- `_mark_paid` هنوز `KeyError`/`ValueError` موجودی را `pass` می‌کند؛ پول گرفته می‌شود و یک خط سبد کم نمی‌شود.
- اگر `_save_orders` بعد از `_mark_paid` بشکند، کیف شارژ شده، دیسک pending است، retry دوباره `credit_sale` می‌زند. Idempotent کردن اعتبار روی `order_id` را در B2/B3 می‌گذارم مگر بگویی همان B1.

### هنوز باز — تأیید کد، هیچ‌کدام را انکار نکردم

**B2 — داده**

- ۳: `write_json` هنوز `write_text` مستقیم است؛ `read_json` روی JSON خراب `default` برمی‌گرداند بدون لاگ. قفل fcntl فقط wallet/shop/inbox (`tenant_lock.py`).
- ۱۴: `idempotency_service.put` کل فایل را بدون قفل read-modify-write می‌کند.
- ۱۶: `pay-pending.json` با `shared=True` بدون قفل؛ `profiles.json`/`settings.json` در `SHARED_FILES` همین‌اند.

نکتهٔ غیربلاک تو برای B2: لاگ به‌جای `except Exception: pass` دور `bump_pending_build`.

**B3 — کیف**

- ۴: `request_withdraw` دفتر `withdraw_hold` با `-amount`؛ `decide_withdraw(ok=True)` دوباره `withdraw_paid` با `-amount` بدون دست زدن به `available`. موجودی درست است، جمع دفتر دو برابر منفی است. `withdraw_reject` درست است.

**B4 — کانال**

- ۵: `_last_ig[phone]` per-tenant؛ اکانت دوم همان ۳۰ثانیه skip. `dmSync` اینستاگرام با `["dmSync"]` KeyError اگر کلید نباشد.
- P3 همان فایل: `.get` برای تلگرام، براکت برای اینستاگرام.
- `poll-skip` هنوز نیست.
- نکتهٔ تو: `_inquiry_url` برای تلگرام اگر هندل عددی باشد `t.me/{id}` — در B4 چک می‌کنم.

**B5 — لبه (فقط کد؛ deploy با go مالک)**

- ۶: `arvan_dns_service.hostname` فقط فاصله و `\ /` را رد می‌کند؛ `;` `` ` `` `$` `"` می‌مانند. `_reload_edge` `nginx -t` را `check=False` می‌گذارد و بعد reload می‌زند.
- ۹: `_write_shop_upstream` بدون قفل سراسری؛ خواندن `shop.json` بقیه هم‌زمان با نوشتن نیمه‌کاره.

**B6**

- ۷: روی fail، `restore_edit_files` دیسک را برمی‌گرداند؛ `publish_shop_runtime` / docker cp بعد از restore نیست.

**B7**

- ۱۱: `verify_otp` سقف تلاش ندارد؛ فقط send محدود است.
- ۱۲: `consume_sms` قبل از ارسال؛ در except فقط OTP پاک می‌شود، overage و `sms-usage` برنمی‌گردند.

**B8**

- ۱۳: `shop/page.tsx` کلید Idempotency را فقط بعد از موفقیت خالی می‌کند (`chatKey.current = ""` داخل try بعد از `apply`). در catch همان کلید برای پیام بعدی می‌ماند. `inbox/[id]/page.tsx` را همان الگو می‌دانم تا در B8 هر دو را با هم درست کنم.

**B9**

- ۱۰: `idpay_verify` مبلغ سفارش را نه می‌فرستد نه از پاسخ می‌سنجد؛ زرین‌پال amount دارد.
- ۱۵: `_bind_live_job` اگر job فعلی `BUILD_BUSY` باشد همان را نگه می‌دارد؛ timeout/watchdog نیست.
- P3 نخ: `_match_thread` با نام نمایشی وقتی `chatId`/`senderId` خالی است.
- P3 `_none`: `set_tenant` روی شمارهٔ نامعتبر `""` → `tenants/_none`.
- P3 postMessage `"*"` در beacon و `shop-live-build.tsx`.
- P3 `_ensure_gpu1` TOCTOU فقط با override غیرپیش‌فرض.

### چیزی که سالم ماند (هم‌نظر)

path traversal در `chat_media_service.resolve`، `compare_digest` در راز پرداخت، tenant_scope در تسک‌های پس‌زمینه، catch در `main.py`. «بساز» زنده هنوز باگ نیست.

### مورد اضافه که در فهرست ۱۶ نبود

- `finish_order` اگر سفارش روی دیسک نباشد (`row is None`) pending را پاک نمی‌کند — کلید یتیم تا TTL انسانی. خرد، در B1 یا B2 یک خط.

### بعد از merge B1

ترتیب قفل تو را بدون پرش اجرا می‌کنم: B2 → B3 → B4 → B5 (merge کد، deploy هاب فقط با go مالک) → B6 → B7 → B8 → B9. هر دسته برنچ جدا، تست رگرسیون، `آماده ریویو`. تا آن موقع فایل دیگری غیر از همین پاسخ را عوض نمی‌کنم.




---

## وضعیت قلم

**مرج شد** — B1، `fix/b1-shop-pay` با fast-forward به `main` (`a0ba7e3 → 6693e1a`)، برنچ حذف شد.

### ریویو Z از B1 (۱۹ سپ ۲۰۲۶) — پذیرفته شد + تحقیق تکمیلی

**B1:** سه فیکس سر جاست: `lines` روی سفارش + `_stock_lines` در `_mark_paid`، `_matches_paid_lookup` فقط با مقدار غیرخالی، و ترتیب جدید verify → mark → save → pop (شاخهٔ paid هم حالا pending را پاک می‌کند). تست‌ها واقعی‌اند؛ هر دو suite را خودم زدم: ۲۴۷ سرویس + ۳ api OK. دو باقیمانده که خودت نوشتی (stock-pass در `_mark_paid`، double-credit اگر `_save_orders` بعد از credit بشکند) → در B2/B3 با idempotent-کردن اعتبار روی `order_id`. یتیم pending در `row is None` هم تأیید؛ یک خط داخل B2.

**یافتهٔ جدید — B0 (فوق‌العاده، قبل از B2):**

- **`PATCH /settings` تنظیمات هاب را برای همهٔ مستأجرها می‌نویسد.** `api/settings.py` مدل `SettingsIn` شامل `mockSms`/`adminPhone`/`otpTtlSeconds`/`gatewayPublicUrl` را از هر کاربر با `campaigns:write` می‌پذیرد و `save_settings` (settings_service.py:127-158) آن را با `write_json(..., shared=True)` در `settings.json` مشترک می‌نویسد. **سناریوی takeover:** هر فروشنده `mockSms=true` ست می‌کند → `POST /auth/otp/send` برای شمارهٔ هر قربانی `dev_code` را در پاسخ می‌دهد (auth_service.py:47-49؛ shop_otp_service.py:44 همین) → ورود به حساب هر کاربر. گارد ادمین کیف از env می‌خواند (api/wallet.py:22-24) پس `adminPhone` امروز اثر ادمینی ندارد، ولی نباید tenant-writable باشد. **فیکس:** کلیدهای STUDIO_KEYS فقط با گارد ادمین هاب (env `ADMIN_PHONE`) پذیرفته شوند؛ PATCH مستأجر فقط کلیدهای خودش را بزند.

**تکمیلهای تحقیق (به دسته‌ها اضافه شد):**

- **B7 + یک مورد:** `shop_otp_service` نه rate-limit ارسال دارد نه سقف تلاش verify (برخلاف OTP پنل که فقط send محدود است) — SMS-bombing و brute-force کد خریدار. با باگ ۱۱ در همان برنچ.
- **B8 + یک فایل:** الگوی کلید Idempotency «ریست فقط در موفقیت» در `app/studio/page.tsx` هم هست (۳ کلید: chat/publish/regen) — هر سه صفحه با هم: shop، inbox/[id]، studio.
- تأیید سالم: گارد مسیر فایل کمپین (`rel_path.startswith(slug)`)، zip از `compose_pipeline`، گارد ادمین کیف مبتنی بر env.

**X: از B0 شروع کن** — برنچ `fix/b0-settings-guard` از `main` (همین `6693e1a`)، گارد ادمین روی کلیدهای استودیو + تست رگرسیون (tenant که mockSms می‌فرستد 403 بگیرد و فایل مشترک تغییر نکند). بعدش B2 طبق ترتیب. قلم با X.

---

## پلن نهایی رفع باگ — مطابقت Z↔X و ترتیب قفل (Z، ۱۹ سپ ۲۰۲۶)

### مطابقت‌سازی فهرست‌ها

فهرست من (۱۶ + P3) در برابر تحقیق X: **هیچ موردی اختلافی نیست** — X همه را روی کد تأیید کرد، هیچ‌یک را رد نکرد. سهSource نهایی:

- فهرست اولیهٔ Z (۱۶ + P3) — همه تأیید X
- افزودنی X: کلید یتیم pending در `finish_order` وقتی `row is None` (تأیید Z)
- افزودنی Z پس از جاروی دوم: **B0** (نوشتن تنظیمات مشترک توسط مستأجر)، بی‌سقفیِ OTP فروشگاه، الگوی کلید idempotency در studio

| # | باگ | X | وضعیت |
| --- | --- | --- | --- |
| ۱ | سبد چندکالایی فقط کالای اول | ✓ | **بسته (B1، مرج شد)** |
| ۲ | تطبیق refId خالی | ✓ | **بسته (B1)** |
| ۸ | ترتیب finish_order | ✓ | **بسته (B1)** — دو باقیمانده → B3 |
| — | *B0: PATCH /settings تنظیمات مشترک (takeover با mockSms)* | جدید Z | **باز — اول از همه** |
| ۳ | write_json غیراتمیک + read_json ساکت | ✓ | باز — B2 |
| ۱۴ | idempotency بدون قفل | ✓ | باز — B2 |
| ۱۶ | فایل‌های shared بدون قفل (۵ نقطه) | ✓ | باز — B2 |
| — | *کلید یتیم pending در row-is-none* | جدید X | باز — B2 (یک خط) |
| ۴ | دفتر withdraw_paid دوبار منفی | ✓ | باز — B3 |
| — | *اعتبار idempotent روی order_id (double-credit) + stock-pass در _mark_paid* | باقیماندهٔ B1 | باز — B3 |
| ۵ | _last_ig per-tenant + dmSync براکت + poll-skip | ✓ | باز — B4 |
| ۶ | تزریق server_name + nginx -t بی‌چک | ✓ | باز — B5 |
| ۹ | race نقشهٔ nginx | ✓ | باز — B5 |
| ۷ | rollback بدون republish کانتینر | ✓ | باز — B6 |
| ۱۱+۱۲ | سقف verify OTP + برگشت overage پیامک | ✓ | باز — B7 |
| — | *OTP فروشگاه: بدون rate-limit و سقف تلاش* | جدید Z | باز — B7 |
| ۱۳ | کلید idempotency فرانت (shop + inbox/[id] + **studio**) | ✓ (+تکملهٔ Z) | باز — B8 |
| ۱۰ | amount در idpay_verify | ✓ | باز — B9 |
| ۱۵ | stuck در BUILD_BUSY | ✓ | باز — B9 |
| P3ها | نخ هم‌نام، _none ساکت، postMessage «*»، TOCTOU گارد GPU1، _inquiry_url عددی، لاگ bump_pending_build | ✓ | باز — پخش در B2/B4/B5/B9 |

هم‌نظر سالم: path traversal رسانه، compare_digest راز/امضا، tenant_scope پس‌زمینه، catch حلقه‌ها، گارد فایل کمپین، «بساز» زنده.

### ترتیب اجرای قفل‌شده

**B0 → B2 → B3 → B4 → B5 → B6 → B7 → B8 → B9** (B1 انجام شد)

**B0 — `fix/b0-settings-guard` (فوری، پیش از همه):**
- `api/settings.py` + `settings_service.save_settings`: کلیدهای `STUDIO_KEYS` (mockSms/adminPhone/otpTtlSeconds/gatewayPublicUrl) فقط با شمارهٔ `ADMIN_PHONE` env پذیرفته شود؛ در غیر این صورت 403 و فایل مشترک دست‌نخورده. سقف معقول روی `otpTtlSeconds` (مثلاً 60–900) هم همین‌جا.
- تست: tenant با `campaigns:write` که mockSms می‌فرستد → 403 و `settings.json` مشترک تغییر نمی‌کند؛ ادمین می‌تواند.

**B2 — `fix/b2-data-layer`:** نوشتن اتمیک tmp+rename در `write_json` + لاگ هشدار در `read_json` خراب؛ قفل فایل مشترک (قفل سراسری جدا از tenant_lock) برای هر ۵ نقطهٔ shared؛ قفل دور `idempotency_service`؛ پاک‌کردن کلید یتیم pending؛ لاگ به‌جای `except: pass` دور `bump_pending_build`.

**B3 — `fix/b3-wallet-ledger`:** `withdraw_paid` بدون کسر دوباره (دفتر = موجودی، تست جمع)؛ `credit_sale` idempotent روی `order_id`؛ خط سبد کم‌ناشده لاگ/رویداد observe به‌جای pass.

**B4 — `fix/b4-channel-poll`:** کلید `_last_ig` per-account؛ `.get("dmSync")` همه‌جا؛ رویداد `poll-skip` بعد از دو cycle؛ هندل عددی تلگرام در `_inquiry_url`.

**B5 — `fix/b5-edge-hostname`:** `hostname` فقط `[a-z0-9.-]`؛ چک خروج `nginx -t` و توقف قبل از reload؛ نوشتن اتمیک + قفل سراسری نقشه/names؛ **deploy هاب فقط با go صریح مالک**.

**B6 — `fix/b6-edit-rollback`:** بعد از `restore_edit_files` در مسیر fail، فایل‌های ترن با `publish_shop_runtime` به کانتینر برگردند.

**B7 — `fix/b7-otp-hardening`:** سقف تلاش verify پنل (مثلاً ۵ در ۵ دقیقه در Redis)؛ برگشت overage و مصرف در شکست ارسال؛ rate-limit ارسال + سقف تلاش OTP فروشگاه.

**B8 — `fix/b8-frontend-idempotency`:** هر سه صفحه (shop، inbox/[id]، studio) — کلید فقط برای retry همان درخواست؛ در خطا/شروع پیام جدید کلید تازه. `tsc --noEmit` در DoD.

**B9 — `fix/b9-leftovers`:** amount در `idpay_verify`؛ timeout/job-stale در `_bind_live_job`؛ نخ هم‌نام؛ `_none` ساکت؛ target origin در postMessage؛ TOCTOU `_ensure_gpu1` اگر ارزان بود.

### تعریف تمام (همهٔ دسته‌ها)

برنچ تازه از `main`، فقط فایل‌های همان دسته، تست رگرسیون برای هر باگ، هر دو suite سبز (`discover` سرویس + api)، `tsc --noEmit` برای دسته‌های فرانت، بند CHANGELOG فارسی، وضعیت `آماده ریویو` در همین فایل. ریویو Z = diff خط‌به‌خط + اجرای تست با دست خودم → merge محلی یا `تغییر خواسته شد`.

**دروازهٔ دیپلوی:** بعد از mergeِ B3، مالک تصمیم می‌گیرد بستهٔ پول (B0+B1+B2+B3) کی به هاب برود. B5 جدا و فقط با go صریح.

**X: شروع با B0. قلم با X.**

---

## وضعیت قلم

**آماده ریویو** — B0، برنچ `fix/b0-settings-guard`، کامیت `ea375a8` از `main` (`9548fd8`). Merge نکن تا Z diff و تست را ببیند.

### X → Z — B0 تمام

کلیدهای `STUDIO_KEYS` (`mockSms` / `adminPhone` / `otpTtlSeconds` / `gatewayPublicUrl`) روی `settings.json` مشترک فقط با شمارهٔ مدیر هاب (`settings.admin_phone` / `ADMIN_PHONE`).

- سرویس: `save_settings(..., hub_admin=False)` برای این کلیدها `PermissionError`؛ `otpTtlSeconds` خارج از ۶۰–۹۰۰ → `ValueError`
- API: `_is_hub_admin` با `normalize_phone`؛ مستأجر `campaigns:write` → `403` و فایل دست‌نخورده؛ `PermissionError`→۴۰۳، `ValueError`→۴۰۰
- `onboard_service.save_settings` فقط نام/شعار می‌فرستد؛ پیش‌فرض `hub_admin=False` سالم است
- تست: سرویس ۳ مورد + API ۲ مورد (tenant 403 + فایل ثابت؛ ادمین `09120000000` می‌تواند)
- suite: ۲۵۰ سرویس + ۵ api سبز

بعد از تأیید تو، B2 را از `main` تازه شروع می‌کنم. B1 باقیمانده‌ها هنوز در B3 است. Deploy هاب نه.

---

## وضعیت قلم

**مرج شد** — B0، `fix/b0-settings-guard` با fast-forward به `main` (`9548fd8 → a8005b5`)، برنچ حذف شد. ریویو Z در `backend/talk.md` هم هست؛ از این به بعد فقط همین فایل ریشه.

### ریویو Z از B0 — پذیرفته شد (کپی در ریشه)

- پایهٔ برنچ `main` در `9548fd8` ✓؛ گارد دو لایه ✓؛ بازهٔ TTL ✓؛ onboard فقط نام/شعار ✓؛ تست‌ها واقعی ✓؛ ۲۵۰+۵ سبز ✓
- نکتهٔ غیربلاک: `adminPhone` در فایل مشترک مرده است (منبع حقیقت env است) — جفت‌کردن با env جدا طرح می‌شود، داخل B2 نیست.

**X: B2 شروع شد.** برنچ `fix/b2-data-layer` از `main` (`24ab54f`). قلم با X. `adminPhone` را دست نمی‌زنم.

---

## وضعیت قلم

**آماده ریویو** — B2، برنچ `fix/b2-data-layer`، کامیت `a9d55c0` از `main` (`24ab54f`). Merge نکن تا Z diff و تست را ببیند.

### X → Z — B2 تمام

1. `write_json` با tmp + `os.replace`؛ `read_json` روی JSON خراب `WARNING` می‌دهد بعد default
2. `shared_lock()` روی `_global.lock` (reentrant) دور نوشتن shared؛ RMW در `pay-pending` / `billing-pending` / `settings.json` / `llm-routing` / `image-probe`
3. قفل `tenant_file_lock("idempotency")` دور get/put
4. `finish_order` وقتی `row is None` کلید pending را `_drop_pending` می‌کند
5. `storefront_service.update_product`: `log.exception` به‌جای `pass`

`adminPhone` مرده را دست نزدم. Deploy هاب نه.

تست: نوشتن همزمان shared (۸×۲۰ کلید سالم)، فایل خراب + لاگ، دو put همزمان idempotency، یتیم pending، لاگ bump. suite: ۲۵۵ سرویس + ۵ api سبز.

---

## وضعیت قلم

**مرج شد** — B2، `fix/b2-data-layer` با fast-forward به `main` (`24ab54f → ac55ff6`)، برنچ حذف شد.

### ریویو Z از B2 — پذیرفته شد

- پایهٔ برنچ `main` در `24ab54f` ✓؛ working tree پاک ✓
- `_write_atomic` استاندارد: mkstemp در همان پوشه + fsync + `os.replace` و پاک‌کردن tmp در خطا — نیمه‌نوشته دیگر ممکن نیست ✓
- `shared_lock` reentrant per-thread (depth در threading.local) + RLock فرایند + flock بین‌فرایندی روی `_global.lock`؛ مسیر خطای flock هم قفل فرایند را آزاد می‌کند ✓
- هر ۵ نقطهٔ RMW مشترک قفل شد: `pay-pending` (`_put/_drop_pending`)، `billing-pending` (همین)، `settings.json` (کل `save_settings` داخل قفل)، `llm-routing`، `image-probe` (الگوی double-check بعد از probe — تمیز) ✓
- `write_json` برای فایل shared خودش قفل می‌گیرد — فراخوانی‌های آینده هم پوشش دارند ✓
- `idempotency` get/put داخل `tenant_file_lock("idempotency")` ✓
- کلید یتیم pending در `row is None` پاک می‌شود ✓؛ `log.exception` جای `pass` در `update_product` ✓
- تست‌ها واقعی: همزمانی ۸×۲۰ shared و ۶×۱۵ idempotency با barrier، JSON خراب + assertLogs، یتیم pending، لاگ bump ✓
- هر دو suite با دست خودم: **۲۵۵ سرویس + ۵ api، همه OK** ✓
- چک deadlock: هیچ مسیری قفل tenant-سپس-global و global-سپس-tenant را تو در تو نمی‌گیرد؛ `save_settings` داخل قفل global فقط `plan.json` مستأجر را بدون قفل می‌نویسد — بی‌خطر

**مالک: بستهٔ پول (B0+B1+B2+B3) با mergeِ B3 کامل و آمادهٔ دیپلوی است؛ زمان rsync/restart هاب با تو.**

---

## X: B3 و B4 پشت‌سرهم سبز شدند — دستور اجرا

طبق فرمان مالک هر دو را پشت‌سرهم می‌زنی؛ دو برنچ جدا، هرکدام جداگانه `آماده ریویو`:

**اول — `fix/b3-wallet-ledger` از `main` تازه (همین `ac55ff6`):**

1. `withdraw_paid` دیگر `-amount` روی دفتر نمی‌گذارد — hold منفی می‌ماند و paid صرفاً رویداد بدون مبلغ است؛ تست «جمع دفتر = available و pendingWithdraw» بعد از withdraw/paid/reject
2. `credit_sale` idempotent روی `order_id`: اگر دفتر `sale_sozan`/`sale_external` با همان `orderId` بود، دوباره اعتبار و دفتر نزن و همان wallet برگردد (بستن double-credit باقیماندهٔ B1) — تست: دوبار `_mark_paid` با همان order فقط یک‌بار کیف را زیاد می‌کند
3. `_mark_paid`: شکست `adjust_stock` بی‌صدا نماند — `log.warning` + رویداد observe `stock-shortage` با productId
4. در همین برنچ: `finish_order` اگر `_mark_paid` استثنا بدهد، pending نماند (pop در `finally` یا برگرداندن کلید برای retry با محافظت idempotency بند ۲)

**بعد — `fix/b4-channel-poll` از `main` تازه (بعد از merge B3):**

1. `_last_ig` با کلید per-account (`_poll_key`) — tenant با دو اکانت اینستاگرام باید هر دو را در یک بازهٔ ۳۰ثانیه‌ای poll کند (تستش را بنویس)
2. هر سه خواندن `dmSync` با `.get("dmSync")` — براکت‌های خط ۷۹ و ۹۳ فعلی
3. رویداد observe `poll-skip` وقتی اکانتی دو cycle پشت‌سرهم به‌خاطر گپ skip شد — فقط اولین بار، نه هر ۴ ثانیه
4. `_inquiry_url` برای تلگرام با هندل فقط-رقمی: خالی برگردان یا username واقعی رد شو

قلم با X. Deploy هاب هنوز نه — بعد از merge B3 به مالک اطلاع می‌دهیم.

---

## وضعیت قلم

**قلم با X** — B3، برنچ `fix/b3-wallet-ledger` از `main` (`4a005e7`). B4 بعد از merge همین برنچ.

---

## وضعیت قلم

**آماده ریویو** — B3، برنچ `fix/b3-wallet-ledger`، کامیت `db4b84c` از `main` (`4a005e7`). Merge نکن تا Z diff و تست را ببیند.

### X → Z — B3 تمام

1. `withdraw_paid` مبلغ ۰ (hold منفی می‌ماند)؛ تست جمع دفتر = `available` بعد از hold/paid/reject
2. `credit_sale` اگر `sale_sozan`/`sale_external` با همان `orderId` باشد همان wallet را برمی‌گرداند — تست دوبار credit و دوبار `_mark_paid`
3. `_mark_paid`: `log.warning` + `emit_later(title="stock-shortage", payload.productId)`
4. بعد از verify موفق، `_drop_pending` در `finally` — حتی اگر `_mark_paid` استثنا بدهد pending نمی‌ماند (تست B1 عوض شد)

`adminPhone` و B4 دست نخورده. Deploy هاب نه — بعد از merge تو به مالک می‌گوییم بستهٔ پول کامل است.

suite: ۲۵۹ سرویس + ۵ api سبز.

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

---

## وضعیت قلم

**آماده ریویو** — B4، برنچ `fix/b4-channel-poll`، کامیت `7fd6964` از `main` (`64ba485`). Merge نکن تا Z diff و تست را ببیند.

### X → Z — B4 تمام

1. `_last_ig` با `_poll_key`؛ دو اکانت اینستاگرام در یک بازهٔ ۳۰ثانیه هر دو poll می‌شوند
2. هر سه `dmSync` با `.get`
3. `poll-skip` بعد از دو cycle گپ، فقط بار اول
4. `_inquiry_url` تلگرام اگر هندل فقط رقم باشد خالی است

suite: ۲۶۱ سرویس + ۵ api سبز. Deploy هاب نه. توکن بات در گروه/talk نیست.

---

## وضعیت قلم

**مرج شد** — B4، `fix/b4-channel-poll` با fast-forward به `main` (`64ba485 → 55a4453`)، برنچ حذف شد.

### ریویو Z از B4 — پذیرفته شد

1. `_last_ig` حالا per-account با `_poll_key` — دو اکانت اینستاگرام در یک بازهٔ ۳۰ثانیه هر دو poll می‌شوند (تست واقعی دارد) ✓
2. هر سه `dmSync` با `.get` ✓
3. `poll-skip`: بعد از دو cycle گپ متوالی، فقط یک‌بار؛ `_mark_ig_polled` شمارنده و نشانگر را ریست می‌کند ✓
4. `_inquiry_url` تلگرام با هندل فقط-رقمی → رشتهٔ خالی ✓
5. هر دو suite با دست خودم: **۲۶۱ سرویس + ۵ api، همه OK** ✓

**X: برو سراغ B5 — `fix/b5-edge-hostname` از `main` تازه (همین `55a4453`).** محدوده: `hostname` فقط `[a-z0-9.-]` (تست `evil.com;x` و backtick و `$` رد شود)، چک خروج `nginx -t` و توقف قبل از reload با لاگ، نوشتن اتمیک + قفل `shared_lock` دور بازنویسی نقشه/names. **فقط کد و تست — deploy هاب جدا و فقط با go صریح مالک.** قلم با X.

---

## وضعیت قلم

**آماده ریویو** — B5، برنچ `fix/b5-edge-hostname`، کامیت `5ab7861` از `main` (`9802ed6`). Merge نکن تا Z diff و تست را ببیند.

### X → Z — B5 تمام

1. `hostname` فقط `[a-z0-9.-]`؛ `evil.com;x` و backtick و `$` و `"` رد می‌شوند
2. `nginx -t` اگر غیرصفر باشد reload نمی‌شود و WARNING می‌نویسد
3. نقشه و names با tmp+replace داخل `shared_lock`

فقط کد. Deploy هاب نه. suite: ۲۶۲ سرویس + ۵ api سبز.

---

## وضعیت قلم

**مرج شد** — B5، `fix/b5-edge-hostname` با fast-forward به `main` (`9802ed6 → 5ab7861`)، برنچ حذف شد.

### ریویو Z از B5 — پذیرفته شد

1. `hostname` allowlist `[a-z0-9.-]` + ردِ `-` لبه‌ای و `..` — `;` و backtick و `$` و `"` همه رد می‌شوند (تست `evil.com;x` و backtick واقعی) ✓
2. `_reload_edge` خروج `nginx -t` را می‌سنجد؛ شکست → `log.warning` با stderr و بدون reload ✓
3. نقشه و `server_name` با `_atomic_text` (fsync + replace) داخل `shared_lock` نوشته می‌شوند — هم race بین‌مستأجری بسته شد هم نیمه‌نوشته ✓
4. هر دو suite با دست خودم: **۲۶۲ سرویس + ۵ api، همه OK** ✓

**مالک: deploy هاب حالا منطقی‌ترین لحظه است** — B0 تا B5 همه مرج‌اند. فقط B5 روی کانف زندهٔ nginx اثر دارد؛ اگر go دادم مراحل rsync + nginx -t + restart را می‌نویسم/اجرا می‌کنم.

**X: برو سراغ B6 — `fix/b6-edit-rollback` از `main` تازه (همین `5ab7861`).** محدوده: بعد از `restore_edit_files` در مسیر fail (هر دو نقطهٔ داخل حلقه و بعد از حلقه در `_run_action_list`)، فایل‌های ترن با `publish_shop_runtime` به کانتینر برگردند؛ تست: اکشن اول موفقِ منتشرشده بعد از rollback در کانتینر هم برگشته باشد. قلم با X.

---

## وضعیت قلم

**آماده ریویو** — B6، برنچ `fix/b6-edit-rollback`، کامیت `9b069b9` از `main` (`3ae821b`). Merge نکن تا Z diff و تست را ببیند.

### X → Z — B6 تمام

1. بعد از `restore_edit_files` در هر دو نقطهٔ fail داخل حلقه و بعد از حلقه، `publish_shop_runtime` فایل‌های `public/` ترن را به کانتینر برمی‌گرداند
2. تست: اکشن اول موفقِ منتشرشده بعد از rollback در کانتینر هم رنگ قبلی است نه زرشکی

فقط کد. Deploy هاب نه. suite: ۲۶۳ سرویس + ۵ api سبز.

---

## وضعیت قلم

**مرج شد** — B6، `fix/b6-edit-rollback` با fast-forward به `main` (`3ae821b → 9b069b9`)، برنچ حذف شد.

### ریویو Z از B6 — پذیرفته شد

1. `_restore_and_republish`: بعد از restore، فایل‌های `public/` از خود اسنپ‌شات برگردانده‌شده جمع + `published_rels` ترن + dedupe → `publish_shop_runtime` به کانتینر — سایت زنده دیگر تغییر نیمه‌کاره را نشان نمی‌دهد ✓
2. هر دو مسیر fail (break داخل حلقه و بعد از حلقه) از همان هلپر استفاده می‌کنند ✓
3. تست `test_mixed_fail_republishes_restored_runtime` واقعی است: کانتینر شبیه‌سازی‌شده و ادعای برگشتن تغییر منتشرشده ✓
4. هر دو suite با دست خودم: **۲۶۳ سرویس + ۵ api، همه OK** ✓

**X: برو سراغ B7 — `fix/b7-otp-hardening` از `main` تازه (همین `9b069b9`).** محدوده: (۱) سقف تلاش verify OTP پنل — مثلاً ۵ تلاش در ۵ دقیقه در Redis با کلید `otp:vl:{phone}`، پاک‌شدن با verify موفق؛ (۲) برگشت overage و مصرف `sms-usage` در شکست ارسال (consume در `finally` پس از نتیجه یا refund در مسیر خطا)؛ (۳) OTP فروشگاه (`shop_otp_service`): rate-limit ارسال و سقف تلاش verify مثل پنل. تست برای هر سه. قلم با X.

---

## وضعیت قلم

**آماده ریویو** — B7، برنچ `fix/b7-otp-hardening`، کامیت `8800f98` از `main` (`cbf38b2`). Merge نکن تا Z diff و تست را ببیند.

### X → Z — B7 تمام

1. verify پنل: کلید `otp:vl:{phone}`، ۵ تلاش در ۳۰۰ثانیه؛ موفق → پاک
2. شکست send: `refund_sms` overage و `sms-usage` را برمی‌گرداند
3. OTP فروشگاه: `shop-otp:rl:` و `shop-otp:vl:` همان سقف‌ها؛ API روی حد → ۴۲۹

فقط کد. Deploy هاب نه. suite: ۲۷۱ سرویس + ۵ api سبز.

---

## اسنپ‌شات وضعیت پروژه — Z، ۲۰ سپ ۲۰۲۶

### بسته‌شده (همه روی main، تست‌شده با دست Z)

| دسته | باگ‌ها | کامیت merge | موضوع |
| --- | --- | --- | --- |
| B0 | takeover تنظیمات مشترک | `a8005b5` | گارد هاب روی `PATCH /settings` + بازهٔ TTL |
| B1 | ۱، ۲، ۸ | `6693e1a` | سبد چندکالایی، refId خالی، ترتیب finish |
| B2 | ۳، ۱۴، ۱۶ | `ac55ff6` | نوشتن اتمیک + `shared_lock` + قفل idempotency |
| B3 | ۴ | `8b36429` | دفتر برداشت + اعتبار idempotent + stock-shortage |
| B4 | ۵ | `9802ed6` | پول per-account + poll-skip + هندل عددی |
| B5 | ۶، ۹ | `3ae821b` | hostname سخت‌گیر + nginx -t + نقشهٔ اتمیک/قفل |
| B6 | ۷ | `cbf38b2` | rollback کانتینر زنده |

**حساب:** ۹ باگ از ۱۶ + ۲ P3 بسته شد. suite الان: ۲۶۳ سرویس + ۵ api.

### در جریان

- **B7 — `fix/b7-otp-hardening` (قلم با X):** سقف تلاش verify پنل، refund پیامک، rate-limit OTP فروشگاه

### صف

- **B8 — فرانت:** کلید idempotency سه صفحه (shop / inbox/[id] / studio) + `tsc --noEmit`
- **B9 — خرده‌ها:** amount در idpay، stuck BUILD_BUSY، نخ هم‌نام، `_none` ساکت، postMessage origin، TOCTOU گارد GPU1

### دروازه‌ها

- **Deploy هاب:** با go مالک — الان B0–B6 روی main آماده‌اند؛ B5 (nginx) روی کانف زنده اثر دارد. بعد از mergeِ B7 هم تازه است.
- **تریگر تلگرام:** رویدادمحور شد — `scripts/team_poller.sh` در بک‌گراند long-poll می‌کند؛ پیام برسد Z همان لحظه بیدار می‌شود (کرون ۲دقیقه‌ای حذف شد). state بات: `backend/data/team-bot/` (token/chat-id/offset، همه gitignored).

**قلم با X (B7). Merge فقط با Z.**

---

## وضعیت قلم

**مرج شد** — B7، `fix/b7-otp-hardening` با fast-forward به `main` (`cbf38b2 → 5e898ee`)، برنچ حذف شد.

### ریویو Z از B7 — پذیرفته شد

1. verify پنل: `otp:vl:{phone}` با ۵ تلاش/۳۰۰ثانیه، پاک‌شدن کلید در verify موفق ✓
2. refund دوطرفه: `refund_sms(charged)` در هر دو مسیر خطای ارسال (پنل + فروشگاه) — شمارش مصرف کم و overage با بند دفتر «برگشت پیامک ارسال‌نشده» برمی‌گردد ✓
3. OTP فروشگاه: `shop-otp:rl:` و `shop-otp:vl:` با همان سقف‌ها؛ `OtpLimitError` → ۴۲۹ در API ✓
4. هر دو suite با دست خودم: **۲۷۱ سرویس + ۵ api، همه OK** ✓

نکتهٔ غیربلاک: شمارندهٔ `shop-otp:rl` حتی در mock/dev پر می‌شود — بی‌ضرر، فقط یادت باشد موقع دیباگ dev.

**X: برو سراغ B8 — `fix/b8-frontend-idempotency` از `main` تازه (همین `5e898ee`).** محدوده: هر سه صفحه (`app/shop/page.tsx`، `app/inbox/[id]/page.tsx`، `app/studio/page.tsx` — سه کلید chat/publish/regen). رفتار درست: کلید تازه برای هر درخواست جدید؛ کلید فقط وقتی حفظ شود که همان درخواست با همان بدنه دوباره زده می‌شود (retry). ساده‌ترین الگوی درست: کلید را در ابتدای هر send بساز و فقط در خطای شبکه‌ایِ «مطمئن نبودن پردازش» نگه دار؛ یا هر send کلید تازه بگیرد و فقط دکمهٔ retry همان پیام از کلید قبلی استفاده کند. `tsc --noEmit` در DoD. قلم با X.

---

## وضعیت قلم

**آماده ریویو** — B8، برنچ `fix/b8-frontend-idempotency`، کامیت `b6641a4` از `main` (`8775b92`). Merge نکن تا Z diff و تست را ببیند.

### X → Z — B8 تمام

1. فروشگاه (چت + بیلد)، صندوق، استودیو (چت / publish / regen): کلید فقط اگر stamp بدنه یکی باشد reuse می‌شود
2. موفقیت و خطای HTTP کلید را خالی می‌کنند؛ فقط خطای شبکهٔ بی‌پاسخ نگه می‌دارد
3. `tsc --noEmit` سبز

فقط کد. Deploy هاب نه. suite بک‌اند: ۲۷۱ سرویس + ۵ api سبز.

### پروتکل ارتباط تلگرام (به‌روز — ۲۰ سپ ۲۰۲۶)

- **شنیدن:** پیام‌های گروه (گزارش‌های X و رله‌های مالک) — پولر رویدادمحور همان‌جاست
- **گفتن:** پیام خروجی Z فقط به **دایرکت مالک** (`@qwertyerfan`، state در `backend/data/team-bot/dm-chat-id`) و همیشه با امضای «از طرف z»
- گروه دیگر از Z خروجی نمی‌گیرد مگر تصمیم مالک برخلاف باشد

---

## وضعیت قلم

**مرج شد** — B8، `fix/b8-frontend-idempotency` با fast-forward به `main` (`8775b92 → b6641a4`)، برنچ حذف شد.

### ریویو Z از B8 — پذیرفته شد

1. هلپر `lib/idempotency.ts`: slot با stamp اثر انگشت درخواست؛ `take` فقط برای همان stamp کلید می‌دهد، وگرنه کلید تازه ✓
2. `finish` در موفقیت پاک می‌کند؛ در خطا فقط اگر «خطای شبکهٔ نامطمئن» باشد (Failed to fetch / TypeError / Abort) کلید می‌ماند تا retry همان درخواست idempotent باشد — خطای قطعی سرور کلید تازه می‌دهد ✓ (دقیقاً الگوی توافق‌شده)
3. هر سه صفحه مهاجرت کردند: shop (chat+build)، inbox/[id]، studio (chat/publish/regen) — stampها شامل فایل (name+size) ✓
4. `tsc --noEmit` پاک + هر دو suite بک‌اند OK (تغییر بک‌اند نبود، برای اطمینان زدم) ✓

**X: برو سراغ B9 — آخرین دسته. `fix/b9-leftovers` از `main` تازه (همین `b6641a4`).** محدوده: (۱) `idpay_verify` مبلغ سفارش را بفرستد و amount پاسخ را بسنجد؛ (۲) `_bind_live_job`: job نیمه‌کارهٔ older-than (مثلاً ۳۰ دقیقه بدون تغییر فایل) → failed؛ (۳) `_match_thread` با نام نمایشی فقط اگر دقیقاً برابر و بدون سایر نامزد؛ (۴) `set_tenant` روی شمارهٔ نامعتبر: به‌جای `_none`، هشدار لاگ + پرتاب خطا در مسیرهایی که مستأجر الزامی است — حداقل لاگ؛ (۵) postMessage: target origin صریح (بک‌گراند: فقط وقتی href معلوم است). TOCTOU گارد GPU1 را رها کن — با routing پیش‌فرض بی‌اثر است. قلم با X.

---

## وضعیت قلم

**آماده ریویو** — B9، برنچ `fix/b9-leftovers`، کامیت `3fba931` از `main` (`e47d88f`). Merge نکن تا Z diff و تست را ببیند.

### X → Z — B9 تمام

1. `idpay_verify` مبلغ سفارش را می‌فرستد و با amount پاسخ می‌سنجد
2. جاب `running`/`queued` بدون تغییر فایل بعد از ۳۰ دقیقه → failed
3. `_match_thread` با نام فقط اگر دقیقاً یک نامزد باشد
4. `set_tenant` شمارهٔ نامعتبر: WARNING و ValueError؛ `_none` ساخته نمی‌شود
5. postMessage پیش‌نمایش origin صریح؛ beacon فقط با origin معلوم. GPU1 TOCTOU دست نخورد

فقط کد. Deploy هاب نه. `tsc --noEmit` سبز. suite: ۲۷۶ سرویس + ۵ api سبز.
