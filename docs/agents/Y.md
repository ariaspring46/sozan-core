# Y — فروشندهٔ خودکار (دایرکت) و دادهٔ آموزش

<!-- ساخته‌شده با tools/agent_context/build.py؛ دستی ویرایش نکنید. مرزها در tools/agent_context/roles.json -->

صندوق و پاسخ خودکار، عامل دایرکت (ابزار stock/order/payment_link، گارد عدد و ادعا)، سیاست فروش، حافظهٔ مشتری و Chroma، ماسک PII، لحن برند، و هستهٔ دادهٔ فاین‌تیون.

**گزارش:** فقط به ته `sales-agent-talk.md` اضافه کن (`cat >>`)؛ برای دیدن آخرین پیام‌ها فقط `tail -n 60`.

## بودجه (توکن تخمینی)

| بخش | توکن |
|---|---|
| هسته (اول هر کار بخوان) | 32.5k |
| سورس فعال (بخوان فقط آنچه کار لازم دارد) | 64.9k |
| سورس کم‌کاربرد (rare؛ فقط اگر کار نامش را برد) | 19.8k |
| تست‌های مالکیت (فقط تست مربوط را بخوان) | 35.7k |
| مال تو ولی هرگز نخوان | 30.9k |
| سقف کانتکست / رزرو عامل | 128.0k / 30.0k |

## هسته

- `backend/app/services/inbox_agent_service.py` (16.5k)
- `backend/app/services/inbox_service.py` (10.5k)
- `backend/app/services/sales_policy_service.py` (5.5k)

## مال تو (فقط همین‌ها را ویرایش کن)

- `backend/app/api/`: `inbox.py` (1.6k)
- `backend/app/services/`: `inbox_agent_service.py` (16.5k), `inbox_service.py` (10.5k), `sales_policy_service.py` (5.5k), `shop_memory_service.py` (2.8k), `voice_service.py` (1.6k), `customer_memory_service.py` (1.5k), `training_log.py` (1.5k), `claims_guard.py` (0.5k), `pii_mask.py` (0.5k)
- `frontend/app/inbox/`: `page.tsx` (4.3k)
- `frontend/app/inbox/[id]/`: `page.tsx` (2.1k)
- `frontend/app/sales/`: `page.tsx` (3.1k)
- `frontend/components/`: `sales-policy-form.tsx` (1.3k), `training-choice.tsx` (0.5k)
- `tools/`: `sales100_battery.py` (7.8k), `train_nightly.py` (3.4k)

**کم‌کاربرد (rare)** — مال تو، ولی فقط وقتی کار صریحاً به آن اشاره کند بخوان:

- `deploy/`: `sozan-battery.service` (0.1k), `sozan-battery.timer` (0.0k), `sozan-chroma.service` (0.2k)
- `tools/`: `draft_day_stats.py` (1.5k), `observe_weekly.py` (0.2k), `sales100_battery.json` (4.5k), `sales_tenant_reset.py` (1.4k), `synthetic_personas.py` (8.5k)
- `tools/agentic_probes/`: `p_dm_loop.py` (1.0k), `p_dm_numbers.py` (0.6k), `p_dm_paylink.py` (0.6k), `p_dm_paystock.py` (0.4k), `p_f7_memory.py` (0.7k)

**تست‌ها:** `inbox_dry_test.py`, `claims_guard_test.py`, `customer_memory_service_test.py`, `inbox_agent_service_test.py`, `inbox_service_test.py`, `pii_mask_test.py`, `sales_policy_service_test.py`, `shop_memory_service_test.py`, `training_log_test.py`, `voice_service_test.py`, `train_nightly_test.py`

**مال تو ولی نخوان** (ساختگی/حجیم؛ فقط با اسکریپت عوض کن): `sales-agent-talk.md` (30.9k)

## قرارداد بیرون از import (HTTP، فایل، سرویس)

- Chroma (فعلاً نصب نشده؛ `deploy/sozan-chroma.service`). کلید پایگاه فقط از `memory_key()`.
- مسیر `/settings/sales-policy` در `backend/app/api/settings.py` (صاحب X5) فرم سیاست فروش تو را ذخیره می‌کند؛ تغییر شکلش با هماهنگی X5.

## آنچه از دیگران لازم داری (فایلشان را باز نکن؛ امضا همین‌جاست)

**`backend/app/services/arvan_dns_service.py`** — صاحب: C
```
def edge_dry() -> bool
```
**`backend/app/services/pay_service.py`** — صاحب: C
```
async def create_order(*, title: str='', amount: int=0, product_id: str='', qty: int=1, customer: str='', channel: str='دایرکت', thread_id: str='', mobile: str='', lines: list[dict] | None=None) -> dict
def get_order(order_id: str) -> dict | None
def public_order(row: dict) -> dict
```
**`backend/app/services/storefront_service.py`** — صاحب: C
```
def list_products() -> dict
```
**`backend/app/services/persian_text.py`** — صاحب: X1
```
def guard_output(text: str, *, finish: str='', limit: int=800) -> str
```
**`backend/app/services/router_embed.py`** — صاحب: X1
```
def cosine(left: list[float], right: list[float]) -> float
```
**`frontend/components/app-shell.tsx`** — صاحب: X1
```
export function AppShell(
```
**`frontend/components/chat-thread.tsx`** — صاحب: X1
```
export type ChatMsg =
export function ChatThread(
```
**`frontend/components/empty-state.tsx`** — صاحب: X1
```
export function EmptyState(
```
**`frontend/components/field.tsx`** — صاحب: X1
```
export function Field({ label, children }: { label: string; children: React.ReactNode })
```
**`frontend/components/ui/button.tsx`** — صاحب: X1
```
export function Button(
```
**`frontend/components/ui/card.tsx`** — صاحب: X1
```
export function Card({ className, ...props }: HTMLAttributes<HTMLDivElement>)
```
**`frontend/components/ui/input.tsx`** — صاحب: X1
```
export function Input({ className, ...props }: InputHTMLAttributes<HTMLInputElement>)
```
**`frontend/components/ui/select.tsx`** — صاحب: X1
```
export function Select({ className, ...props }: SelectHTMLAttributes<HTMLSelectElement>)
```
**`frontend/lib/api.ts`** — صاحب: X1
```
export async function api<T>(path: string, init: RequestInit = {}): Promise<T>
```
**`frontend/lib/digits.ts`** — صاحب: X1
```
export function formatWhen(at: number): string
export function money(amount: number): string
export function parseNonNegativeInt(raw: string): number | null
```
**`frontend/lib/idempotency.ts`** — صاحب: X1
```
export function emptyIdempotencySlot(): IdempotencySlot
export function finishIdempotencyKey(slot: IdempotencySlot, err?: unknown): void
export function takeIdempotencyKey(slot: IdempotencySlot, stamp: string): string
```
**`frontend/lib/utils.ts`** — صاحب: X1
```
export function cn(...inputs: ClassValue[])
```
**`backend/app/services/channel_outbound_service.py`** — صاحب: X3
```
async def deliver(*, platform: str, sender_id: str, chat_id: str, text: str) -> None
```
**`backend/app/services/channel_service.py`** — صاحب: X3
```
IG_RECONNECT = 'این پیج را دوباره با ورود رسمی وصل کن.'
PLATFORMS = {key: spec['label'] for key, spec in SPECS.items()}
PLATFORMS = {key: spec['label'] for key, spec in SPECS.items()}
def iter_accounts() -> list[dict]
def sendbox_account_id(row: dict) -> str
def token_for(row: dict) -> str
def uses_hub_bot(row: dict) -> bool  # Telegram row with no bot of its own: it only borrows the shared hub bot to post.
```
**`backend/app/services/chat_media_service.py`** — صاحب: X3
```
def caption(kind: str) -> str
```
**`backend/app/services/telegram_service.py`** — صاحب: X3
```
async def pull_updates(*, token: str, handle: str='') -> dict
```
**`frontend/components/channel-alert.tsx`** — صاحب: X3
```
export function ChannelAlert({ inset = true }: { inset?: boolean })
```
**`backend/app/services/shop_service.py`** — صاحب: X4
```
def _shop() -> dict
def live_url(shop: dict) -> str
```
**`backend/app/config.py`** — صاحب: X5
```
settings = Settings()
Settings.jwt_secret: str = 'change-me-to-a-long-random-secret'
Settings.local_llm_token: str = 'sk-local'
Settings.local_llm_url: str = 'http://127.0.0.1:9292/v1'
```
**`backend/app/security.py`** — صاحب: X5
```
def require_permission(code: str)
```
**`backend/app/services/idempotency_service.py`** — صاحب: X5
```
def body_stamp(raw: bytes) -> str
def put(scope: str, key: str, payload: Any, stamp: str='') -> None
def recall(scope: str, key: str, stamp: str) -> Any | None
```
**`backend/app/services/llm.py`** — صاحب: X5
```
ARVAN_HOST_SUFFIX = 'arvancloudai.ir'
INBOX_TURN_BUDGET = 30.0
LLM_BAD_JSON = {'reply': 'مدل پاسخ خوانا نداد. پیام را کوتاه\u200cتر دوباره بفرست.', 'error': 'llm_bad_json'}
async def complete_json(system: str, user: str, *, surface: str='llm', max_tokens: int=700) -> dict
async def complete_tools(*, messages: list[dict], tools: list[dict], temperature: float=0.2, max_tokens: int=ROUTER_MAX_TOKENS, timeout: float | None=None, surface: str='router') -> dict  # Tool-call round. Router and inbox are cloud-first.
def spoken_model_reply(text: str) -> str
```
**`backend/app/services/observe_client.py`** — صاحب: X5
```
def emit_later(*, kind: str, title: str, payload: dict[str, Any] | None=None, surface: str='', component: str='', stage: str='', status: str='', conversation_id: str='', turn_id: str='', operation_id: str='', job_id: str='', scan_id: str='', parent_id: str='', event_id: str='', started_at: float | None=None, duration_ms: int | None=None) -> None
```
**`backend/app/services/pipeline_release.py`** — صاحب: X5
```
BEHAVIOR_VERSION = '2026.09.16-pipeline'
def hub_release_id() -> str
```
**`backend/app/services/plan_service.py`** — صاحب: X5
```
def current() -> dict
```
**`backend/app/services/profile_service.py`** — صاحب: X5
```
TONES = {'warm': {'id': 'warm', 'label': 'گرم و خودمونی', 'tone': 'گرم، کوتاه، فارسی روزمره', 'summary': 'فروشندهٔ صمیمی؛ واضح و بی\u200cتعارف.', 'sampleRepl...
TONES = {'warm': {'id': 'warm', 'label': 'گرم و خودمونی', 'tone': 'گرم، کوتاه، فارسی روزمره', 'summary': 'فروشندهٔ صمیمی؛ واضح و بی\u200cتعارف.', 'sampleRepl...
```
**`backend/app/services/settings_service.py`** — صاحب: X5
```
def allows_training() -> bool  # True unless this seller turned «کمک به بهتر شدن سوزان» off.
def get_settings() -> dict
```
**`backend/app/services/tenant_lock.py`** — صاحب: X5
```
def tenant_file_lock(name: str='shop') -> Iterator[None]
```
**`backend/app/state_store.py`** — صاحب: X5
```
def current_tenant() -> str
def read_json(name: str, default: Any, *, shared: bool=False) -> Any
def write_json(name: str, payload: Any, *, shared: bool=False) -> None
```

**API بک‌اند که صفحه‌هایت صدا می‌زنند** (شکل پاسخ را از صاحبش بپرس، فایل را کامل نخوان):

- `/channels` ← `backend/app/api/channels.py` (X3)
- `/settings`, `/settings/sales-policy` ← `backend/app/api/settings.py` (X5)
- `/sales` ← `backend/app/api/storefront.py` (C)
- `/wallet/orders` ← `backend/app/api/wallet.py` (X5)

## قرارداد تو با دیگران (بدون هماهنگی امضا را عوض نکن)

- `backend/app/api/inbox.py`: `router` ← X5
- `backend/app/services/claims_guard.py`: `check` ← X2
- `backend/app/services/inbox_service.py`: `expire_stale_sending` ← X5؛ `handle_inbound` ← X3؛ `list_publish_audience` ← X1, X2؛ `list_threads` ← X1؛ `rearm_pending_auto_replies` ← X5؛ `save_auto_reply` ← X1؛ `unread_count` ← X1
- `backend/app/services/pii_mask.py`: `mask_pii` ← X5
- `backend/app/services/sales_policy_service.py`: `public_policy` ← X5؛ `save_policy` ← X5
- `backend/app/services/training_log.py`: `log_example` ← X1, X2, X4؛ `log_label` ← X5
- `backend/app/services/voice_service.py`: `apply_tone` ← X1, X3؛ `get_voice` ← X3, X5؛ `learn` ← X3؛ `merge_summary` ← X3
- `frontend/components/sales-policy-form.tsx`: `SalesPolicyForm` ← X5
- `frontend/components/training-choice.tsx`: `TrainingChoice` ← X5

## قاعدهٔ مصرف توکن

1. اول هر کار: همین فایل + فقط فایل‌های «هسته» که به کار مربوط است. فایل بزرگ را با `grep -n` پیدا کن و با `sed -n 'a,bp'` فقط بازه را بخوان.
2. فایل دیگران را باز نکن؛ امضای لازم بالاست. اگر امضا کافی نبود، از صاحبش در فایل گزارشش بپرس.
3. تست: فقط ماژول خودت، مثلاً `python -m unittest app.services.<module>_test`؛ سوییت کامل فقط پیش از PR، و فقط خلاصه: `... 2>&1 | tail -5`.
4. هرگز این‌ها را نخوان: `.zcode/**`, `.cursor/**`, `backend/app/data/router_intent_vectors.json`, `voice-gateway/sales-train.jsonl`, `voice-gateway/sales-holdout.jsonl`, `frontend/package-lock.json`, `frontend/tsconfig.tsbuildinfo`, `docs/ui-audit-live/**`, `docs/festival/**`, `docs/*.patch`, `talk.md`, `sales-agent-talk.md`, `voice-agent-talk.md`, `storefront-talk.md`, `CHANGELOG.md`.
5. خروجی ابزار را کوتاه کن: `| head`، `| tail`، `git diff --stat` پیش از `git diff`.
