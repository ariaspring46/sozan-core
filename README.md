# سوزان

پنل ساخت و ادارهٔ فروشگاه اینترنتی: از چت سایت را سفارش می‌دهی، محتوا می‌سازی، و فروش را از یک داشبورد می‌بینی.

جملهٔ محصول: **بگو، بساز، بفروش.**

| نقش | نشانی |
| --- | --- |
| معرفی | https://sozan-core.ir |
| پنل | https://app.sozan-core.ir |
| API | https://api.sozan-core.ir |
| فروشگاه | `https://{slug}.sozan-core.ir` |
| گیت | https://github.com/Erfuni/sozan |

**مرجع فنی کامل:** [`docs/فنی.md`](docs/فنی.md)  
محصول برای فروشنده: [`docs/کارهای-سوزان.md`](docs/کارهای-سوزان.md)

## اجرای محلی

```bash
cp .env.example .env
docker compose up -d
cd backend && python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

در ترمینال دیگر:

```bash
cd frontend && npm install && npm run dev
```

پنل روی `http://127.0.0.1:3000`، ورود از `/login`. با `OTP_DEV=true` کد در پاسخ API می‌آید.

تست بک‌اند: از `backend` با venv، `python -m unittest discover -s app/services -p '*_test.py'`.
