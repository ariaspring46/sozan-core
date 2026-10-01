# پیام شروع هر برنامه‌نویس (کپی/پیست)

مشترک همه: مانیفست تو «کل هارنس» است — یک بار کامل بخوان و دیگر سند دیگری را الکی باز نکن. قواعد مشترک: بدون راز/شماره در گزارش؛ هر افزودن با آزمون زندهٔ اثبات (شاهد در گزارش)؛ کار روی شاخه + ریویو؛ فایلِ بقیه مال بقیه است — درخواست را در فایل گزارش همان نفر بنویس.

## X1
اول `docs/agents/X1.md` را کامل بخوان — مانیفست تو است. فایل‌های حیاتی‌ات: `router_service.py`، `turn_parse.py`، `api/router_chat.py`، `frontend/components/chat-thread.tsx` و `frontend/app/chat/**` (پوستهٔ مشترک پنل: layout/app-shell هم مال توست). گزارش: `talk-x1.md`. نکتهٔ نقش: قفل نوبت و کارت تأیید روتر را نشکن؛ ایندکس اینتنت‌ها با `refresh_router_intents.py` تازه می‌شود.

## X2
اول `docs/agents/X2.md`. فایل‌های حیاتی‌ات: `studio_chat_service.py`، `studio_compose_service.py`، `image_provider_service.py`، `api/studio.py` (+ برش ابری `cloud_cutout_service.py`). گزارش: `talk-x2.md`. نکتهٔ نقش: تصویر **فقط ابری** (OpenRouter؛ موتور محلی پشت فلگ dev) و زیر سقف بودجه؛ نسبت‌های اینستاگرام (۴:۵ پیش‌فرض) نشکند.

## X3
اول `docs/agents/X3.md`. فایل‌های حیاتی‌ات: `channel_service.py`، `sendbox_service.py`، `channel_poll_service.py`، `api/channels.py`. گزارش: `talk-x3.md`. نکتهٔ نقش: حساب سندباکس فقط با nonce متصل می‌شود؛ توکن وب‌هوک `SENDBOX_WEBHOOK_SECRET` جداست (چرخش با پنجرهٔ legacy)؛ پیام مشتریِ واقعی هرگز به observe/گزارش نمی‌رود.

## X4
اول `docs/agents/X4.md`. فایل‌های حیاتی‌ات: `shop_edit_service.py`، `shop_intent_service.py`، `shop_edit_verify.py`، `api/shop.py` (+ `shop_service.py` و `frontend/app/shop/**`). گزارش: `talk-x4.md`. نکتهٔ نقش: کارخانه از کامیت منتشرشده deploy می‌شود (deploy-from-git)؛ کاتالوگ ویترین با کالای واقعی تنانت سینک بماند؛ `paySecret` را در ذخیرهٔ وضعیت پاک نکن (تست رگرسیون هست)؛ بازسازی روی ویترین زنده ممنوع.

## X5
اول `docs/agents/X5.md`. فایل‌های حیاتی‌ات: `llm.py`، `state_store.py`، `observe_client.py`، `config.py`، `main.py` (+ امنیت، CI، deploy). گزارش: `talk-x5.md`. نکتهٔ نقش: **تنها تو استقرار می‌کنی** — فقط با flock، فقط از کامیت منتشرشده، `DEPLOYED_COMMIT` را بنویس؛ رازها هرگز؛ هدر IP معتمد `ar-real-ip` است؛ `PAYMENT_SIGN_SECRET` جدای `JWT_SECRET`.

## Y
اول `docs/agents/Y.md`. فایل‌های حیاتی‌ات: `inbox_agent_service.py`، `inbox_service.py`، `sales_policy_service.py` (+ حافظهٔ مشتری، `pii_mask`، `training_log`). گزارش: `sales-agent-talk.md`. نکتهٔ نقش: دادهٔ آموزش فقط با رضایت (`sozanImprove`) و ماسک؛ ارسال خودکار خاموش تا دستور مالک؛ `payment_service` مال X5/X4 است — درخواست، نه ویرایش.

## Z
اول `docs/agents/Z.md`. فایل‌های حیاتی‌ات: `voice-gateway/sales.py` و `voice-gateway/brain.py` (کل `voice-gateway/**` مال توست). گزارش: `voice-agent-talk.md`. نکتهٔ نقش: تماس واقعی فقط با اجازهٔ صریح مالک؛ DNC مقدس؛ llama-swap و GPU بقیه را دست نزن؛ صدای Leda روی خط است.

## C
اول `docs/agents/C.md`. فایل‌های حیاتی‌ات: `storefront_service.py`، `pay_service.py`، `api/storefront.py`، `api/pay.py` (+ کارخانهٔ قالب‌ها و `frontend/app/p/**`). گزارش: `storefront-talk.md`. نکتهٔ نقش: بازسازی کامل روی ویترین زنده ممنوع (فقط قالب+سیاست+سینک)؛ DNS فقط خشک (`SOZAN_EDGE_DRY`)؛ عکس کالا مسیر ابری است؛ هر UI با قاعدهٔ ۱۸:۴۰ آزمون زنده می‌گیرد.
