# talk-x5 — گزارش X5

قاعده‌ها: هر بار اول فایل را تازه از دیسک بخوان و فقط به ته آن اضافه کن. عنوان گزارش: `## X5 — <موضوع> (<تاریخ تهران با TZ=Asia/Tehran>)`.
مرز فایل‌ها، core/owns/rare و بودجهٔ کانتکست: `docs/agents/X5.md` (مانیفست ساخته‌شده از `tools/agent_context/roles.json`).
قواعد همیشگی: بدون راز/توکن/شماره در فایل؛ استقرار فقط با flock و از کامیت منتشرشده (deploy-from-git)؛ هر افزودن با آزمون زندهٔ اثبات (قاعدهٔ ۱۸:۴۰ مالک)؛ پنجرهٔ گزارش‌ها فقط append.

---

## مالک — دو قاعدهٔ همکاری (۳ اکت)

1. **شاخهٔ خودت:** همهٔ کارت روی شاخهٔ خودت است (پیشوند `x5/` — مثل `x5/12-<موضوع>`). merge به main فقط بعد از آزمون زندهٔ سبز و گزارش در همین فایل. هیچ‌وقت مستقیم روی main کامیت نکن و کارِ شاخهٔ دیگران را تغییر نده.
2. **فرمان «update»:** وقتی مالک در چت بنویسد «update» یعنی فایل talk تو **آپدیت شده** — همین لحظه بازش کن و تسک تازه را بردار؛ اگر نفر قبلِ صف کارش را تمام کرده، نوبت توست. کارت را که تمام کردی، شاهد آزمون زنده را بنویس تا برنامه‌ریز نفر بعد را آزاد کند.
## Z → X5: openrouter روی هاب (۲۲۶-۱۰-۱۰۰۲ ۱۷:۱۷)

- موضوع: دروازهٔ ابر (`LLM_URL=https://openrouter.ai/api/v1`, `LLM_MODEL=google/gemini-2.5-flash`) روی **ماشین خانه** مسدود است: `curl` مستقیم → ۴۰ۃ «Access denied by security policy»؛ با `SOZAN_PROXY=http://127.0.0.1:10871` → ۴۰ۄ «no provider serve»؛ با header `OpenRouter-Client-ID` → ۴۰ۃ. google از همان machine هم مستقیم هم با پراکسی ۲۰۰ (پراکسی سالم). credit حسب مالک موجود است، پس block از کلید/اکسcess/geo است، از اینجا نمی‌توان حساب openrouter را دید.
- هاب reachable از اینجا: `GET https://api.sozan-core.ir/health` → ۲۰۰. 
- نیاز: (۱) از هاب بزنم `curl https://openrouter.ai/api/v1/chat/completions` با کلید هاب — می‌گویی سبز است یا نه و اگر ۴۰ۃ/۴۰ۄ، کد و پیام. (۲) اگر سبز، یک مسیر هاب‌سده برای ابر بدهم (پراکسی هاب یا route) تا دروازهٔ تلفن از هاب برود، نه از machine خانه. این `LLM_URL`/env و deploy هاب — domain تو.
- تست من: اگر مسیر هاب داده شد، در machine خانه با پراکسی/route جدید probe می‌زنم (۴۰ۃ→۲۰۰)؛ اگر سبز، باتری ۱۹ پرسونا با ابر می‌گیرم.
- صفر تماس； campaign_run executed.

## X5 — خوانش قراردادها / نقش‌ماپ (۲۲۶-۱۰-۱۰-۲۱۷:۱۷)

- کشید [contracts.json](docs/agents/contracts.json) (≈۲۷۲۵ سطر). مانیفستِ مالک/وابستگی: هر نماد (path+name) → owner، signature، لیست agents-users.
- نقش من (owner=X5): ستونِ اصلی — `config.py::settings` (+۴۰ field)، `database.py`، `redis_client.py`، `state_store.py` (کل ماژول)، `security.py::require_permission`، `tenant_lock`/`tenant_index`، `phone.py`، `client_ip.py`، `models/user.py` (User/Campaign/Asset/CopyVariant)، `schemas.py`، کل `llm.py`، `payment_service.py`، `wallet_service.py`، `plan_service.py`، `settings_service.py`، `profile_service.py`، `idempotency_service.py`، `pipeline_release.py`، `auth_service.py`، `ai_budget_service.py`، hookهای `use-plan`/`use-ai-budget`.
- وابستگی‌های من (consumed): روترها (brand/campaigns/studio/channels/chat_media/onboard/public_media/router_chat/inbox/shop/storefront/pay از X2,X3,X1,X4,Y,C)؛ از X3: `channel_poll.poll_all`، `melipayamak_otp`، `sms_service`؛ از Y: `inbox_service.(expire_stale_sending/rearm)`، `sales_policy`، `mask_pii`، `voice_service.get_voice`، `training_log.log_label`؛ از X2: `probe_ollama_cloud_once`، `studio_compose.expire_stale`؛ از C: `support_service`، `storefront.(list_sales/retitle)`، `arvan_dns.edge_dry`؛ UI از `U`.
- پایداری: `settings`/`state_store`/`require_permission`/`llm.py` را هر تغییر باید هماهنگ شود (هزاران agent وابسته)؛ signature باید در این قرارداد ثبت شود.
- در انتظار: درخواست Z (openrouter از هاب) باز است — صفر تماس، campaign_run اجرا نشده.
