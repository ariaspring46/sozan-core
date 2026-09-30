---
name: qa-library
description: "Use when testing or verifying Sozan software: Playwright/Cypress E2E, API testing, unit tests (Jest/pytest), visual regression, performance (k6), security testing, accessibility (WCAG), CI/CD pipelines, and agentic browser testing. Pick the matching skill folder under skills/ and follow it."
---

# QA Library — مجموعهٔ تست سوزان

روتر این کتابخانه: بستهٔ نوع کار، پوشهٔ درست را زیر `skills/` باز کن و همان را دنبال کن.

| کار | پوشه |
| --- | --- |
| E2E مرورگر | `skills/playwright-e2e` یا `skills/cypress-e2e` |
| تست API | `skills/playwright-api` یا `skills/api-testing-rest` |
| تست واحد | `skills/jest-unit` یا `skills/pytest-patterns` |
| عملکرد | `skills/k6-performance` |
| رگرسیون بصری / دسترس‌پذیری / امنیت / CI-CD / مرورگر عامل‌محور | پوشه‌های هم‌نام زیر `skills/` |

قواعد سوزان بالاتر از این راهنماهاست: هیچ تستی به دادهٔ واقعی مشتری/شمارهٔ واقعی نمی‌زند؛ تست پنلی فقط روی تنانت آزمایشی یا نمونهٔ خشک (`SOZAN_EDGE_DRY=1`)؛ شاهد هر تست (کد HTTP، اسکرین‌شات، پاسخ) در گزارش می‌آید (قاعدهٔ ۱۸:۴۰ مالک). موتورها (Playwright و…) در محیط نصب نیستند مگر X نصب کند — قبل از هر نصب وابستگی جدید با مالک/X هماهنگ شود.
