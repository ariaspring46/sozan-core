# talk-x1 — گزارش X1

قاعده‌ها: هر بار اول فایل را تازه از دیسک بخوان و فقط به ته آن اضافه کن. عنوان گزارش: `## X1 — <موضوع> (<تاریخ تهران با TZ=Asia/Tehran>)`.
مرز فایل‌ها، core/owns/rare و بودجهٔ کانتکست: `docs/agents/X1.md` (مانیفست ساخته‌شده از `tools/agent_context/roles.json`).
قواعد همیشگی: بدون راز/توکن/شماره در فایل؛ استقرار فقط با flock و از کامیت منتشرشده (deploy-from-git)؛ هر افزودن با آزمون زندهٔ اثبات (قاعدهٔ ۱۸:۴۰ مالک)؛ پنجرهٔ گزارش‌ها فقط append.

---
## X1 — خواندن contracts.json و یک تناقض مرزی (2026-10-01 23:05 Tehran)
- done: contracts.json (۲۷۲۵ خط) کامل خوانده شد؛ قراردادهای متعلق به X1 استخراج شد (read_chat_payload، router_chat::router، guard_output، sanitize_persian، cosine، bind_thread_id، clear_dead_busy، remember_content، thread_campaign_id، parse_turn، ChatMsg، ChatThread).
- ملاحظه: contracts.json (تازه‌تر، کامیت c0d4db6) و roles.json پوستهٔ مشترک پنل (app-shell، ui/*، lib/api.ts، digits، idempotency، utils، empty-state، field، getting-started، theme-toggle، sozan-mark) را مال U می‌دانند؛ اما X1.md و پیام شروع مالک (03b21b0: «پوستهٔ مشترک پنل هم مال توست») آن‌ها را مال X1 می‌دانند. build.py --check سبز است.
- needs: مالک — مرز قطعی را تأیید کند: پوستهٔ پنل با X1 است یا U؟ تا تعیین تکلیف، بدون تأیید در آن فایل‌ها دست نمی‌زنم.
