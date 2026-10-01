# C — ویترین، کاتالوگ، سفارش مشتری، دامنه، پشتیبانی و پایش

<!-- ساخته‌شده با tools/agent_context/build.py؛ دستی ویرایش نکنید. مرزها در tools/agent_context/roles.json -->

هر چه به سایت زندهٔ فروشگاه و مشتری‌اش برمی‌گردد: کاتالوگ و موجودی، همگام‌سازی با ویترین، سفارش و پرداخت مشتری (/p/)، دامنه و DNS آروان، تنظیمات فروشگاه، تیکت پشتیبانی، و بیرون از مخزن: کارخانه، قالب‌ها و پایش.

**گزارش:** فقط به ته `storefront-talk.md` اضافه کن (`cat >>`)؛ برای دیدن آخرین پیام‌ها فقط `tail -n 60`.

## بودجه (توکن تخمینی)

| بخش | توکن |
|---|---|
| هسته (اول هر کار بخوان) | 19.8k |
| سورس فعال (بخوان فقط آنچه کار لازم دارد) | 56.2k |
| سورس کم‌کاربرد (rare؛ فقط اگر کار نامش را برد) | 0.0k |
| تست‌های مالکیت (فقط تست مربوط را بخوان) | 16.5k |
| مال تو ولی هرگز نخوان | 26.4k |
| سقف کانتکست / رزرو عامل | 128.0k / 30.0k |

## هسته

- `backend/app/services/storefront_service.py` (5.5k)
- `backend/app/services/pay_service.py` (7.8k)
- `backend/app/api/storefront.py` (2.9k)
- `backend/app/api/pay.py` (3.6k)

## مال تو (فقط همین‌ها را ویرایش کن)

- `backend/app/api/`: `pay.py` (3.6k), `storefront.py` (2.9k)
- `backend/app/services/`: `pay_service.py` (7.8k), `storefront_service.py` (5.5k), `arvan_dns_service.py` (3.9k), `catalog_sync_service.py` (2.4k), `shop_otp_service.py` (1.8k), `support_service.py` (1.6k)
- `frontend/app/more/inventory/`: `page.tsx` (0.2k)
- `frontend/app/more/support/`: `page.tsx` (4.2k)
- `frontend/app/p/[id]/`: `page.tsx` (0.8k)
- `frontend/components/`: `shop-settings-form.tsx` (8.6k), `product-editor.tsx` (5.1k), `inventory-catalog.tsx` (4.2k), `domain-menu.tsx` (3.4k)
- `frontend/lib/`: `site-host.ts` (0.1k)

**تست‌ها:** `pay_status_rate_test.py`, `arvan_dns_service_test.py`, `catalog_sync_service_test.py`, `pay_service_test.py`, `shop_otp_service_test.py`, `storefront_service_test.py`, `support_service_test.py`

**مال تو ولی نخوان** (ساختگی/حجیم؛ فقط با اسکریپت عوض کن): `storefront-talk.md` (26.4k)

## قرارداد بیرون از import (HTTP، فایل، سرویس)

- کار اصلی بیرون از مخزن: `/home/demon/local-ai/smoke-workspace/site-builder/**` (قالب‌ها، گیت کیفیت، `tools/sozan_factory_fastpath.py`). خروجی JSON زیرفرمان `status` و فایل job را X4 می‌خواند؛ قالبشان قرارداد است.
- ویترین زنده این مسیرهای هاب را صدا می‌زند و همه مال توست: `/p/catalog-ids`، `/p/shop-config`، `/p/shop/checkout`، `/p/shop/paid`، `/p/otp/*`، `/p/tickets`، `/catalog/*`.
- ابزارهای `tools/monitor/**` و `tools/storefront/**` روی شاخهٔ `feat/storefront-c` هستند؛ بعد از merge خودکار مال تو می‌شوند.

## آنچه از دیگران لازم داری (فایلشان را باز نکن؛ امضا همین‌جاست)

**`backend/app/services/persian_text.py`** — صاحب: X1
```
def sanitize_persian(text: str, *, limit: int=80) -> str
```
**`frontend/components/app-shell.tsx`** — صاحب: X1
```
export function AppShell(
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
**`frontend/components/ui/textarea.tsx`** — صاحب: X1
```
export function Textarea({ className, ...props }: TextareaHTMLAttributes<HTMLTextAreaElement>)
```
**`frontend/lib/api.ts`** — صاحب: X1
```
export async function api<T>(path: string, init: RequestInit = {}): Promise<T>
export function catalogImageUrl(name: string): string
export function fileUrl(campaignId: string, relPath: string): string
export function getApiBase(): string
```
**`frontend/lib/digits.ts`** — صاحب: X1
```
export function money(amount: number): string
export function parseNonNegativeInt(raw: string): number | null
export function priceText(price: number, label?: string): string
```
**`backend/app/services/product_image_service.py`** — صاحب: X2
```
def remove_if_unreferenced(name: str) -> bool
def store(data: bytes, content_type: str, filename: str) -> str
```
**`frontend/components/sozan-mark.tsx`** — صاحب: X2
```
export function SozanMark({ className, glow = true }: { className?: string; glow?: boolean })
```
**`backend/app/services/channel_scan_service.py`** — صاحب: X3
```
def _looks_like_product_title(title: str) -> bool
def _scan_dir() -> Path
def _unattributed_dir() -> Path
def product_title_from_caption(caption: str, brand: str='') -> str | None
```
**`backend/app/services/chat_media_service.py`** — صاحب: X3
```
def save(filename: str, data: bytes, content_type: str, *, sweep: bool=True) -> dict
```
**`backend/app/services/sms_service.py`** — صاحب: X3
```
def resolve_sms(overlay: dict | None=None) -> dict[str, str]
async def send_otp(*, provider: str, api_key: str, template_id: str, token_name: str, phone: str, code: str) -> None
```
**`backend/app/services/telegram_alert_service.py`** — صاحب: X3
```
async def seller_ticket_alert(ticket_id: str, subject: str, tenant: str) -> None
```
**`backend/app/services/shop_edit_service.py`** — صاحب: X4
```
def build_dir_for(shop: dict) -> Path | None
def has_runtime_overlay(root: Path | None) -> bool
def publish_shop_runtime(shop: dict, root: Path, rels: list[str]) -> None
def write_catalog_json(root: Path, products: list[dict]) -> Path
```
**`backend/app/services/shop_service.py`** — صاحب: X4
```
PROTECTED_SHOP_SLUGS = frozenset({'joahr-froshi', 'cahrm-srai-pars'})
def _bump_pending(shop: dict) -> dict
def _factory_category_slug(category_fa: str) -> str
def _factory_item_sub(title: str, category_fa: str) -> tuple[str, str]
def _shop() -> dict
def _shop_is_live(shop: dict) -> bool
def bump_pending_build() -> None
```
**`backend/app/client_ip.py`** — صاحب: X5
```
def client_ip(request: Request) -> str
```
**`backend/app/config.py`** — صاحب: X5
```
settings = Settings()
Settings.arvan_api_key: str = ''
Settings.arvan_origin_ip: str = ''
Settings.arvan_origin_port: int = 80
Settings.arvan_zone: str = 'sozan-core.ir'
Settings.jwt_secret: str = 'change-me-to-a-long-random-secret'
Settings.otp_dev: bool = False
Settings.otp_ttl_seconds: int = 300
Settings.panel_url: str = 'https://app.sozan-core.ir'
Settings.payment_sign_secret: str = ''
Settings.public_api_url: str = 'https://api.sozan-core.ir'
Settings.shop_otp_daily_cap: int = 200
```
**`backend/app/phone.py`** — صاحب: X5
```
def normalize_digits(raw: str) -> str  # Persian/Arabic-Indic digits to ASCII, other characters untouched.
def normalize_phone(raw: str) -> str
```
**`backend/app/redis_client.py`** — صاحب: X5
```
redis_client = Redis.from_url(settings.redis_url, decode_responses=True)
redis_client = Redis.from_url(settings.redis_url, decode_responses=True)
redis_client = Redis.from_url(settings.redis_url, decode_responses=True)
redis_client = Redis.from_url(settings.redis_url, decode_responses=True)
redis_client = Redis.from_url(settings.redis_url, decode_responses=True)
redis_client = Redis.from_url(settings.redis_url, decode_responses=True)
```
**`backend/app/security.py`** — صاحب: X5
```
def require_permission(code: str)
```
**`backend/app/services/auth_service.py`** — صاحب: X5
```
OTP_SEND_LIMIT = 5
OTP_SEND_WINDOW = 900
OTP_VERIFY_LIMIT = 5
OTP_VERIFY_WINDOW = 300
def otp_test_reveal_allowed(phone: str) -> bool  # کد فقط برای شماره‌های ساختگیِ تست و فقط در پنجرهٔ تست در پاسخ می‌آید.
```
**`backend/app/services/observe_client.py`** — صاحب: X5
```
def emit_later(*, kind: str, title: str, payload: dict[str, Any] | None=None, surface: str='', component: str='', stage: str='', status: str='', conversation_id: str='', turn_id: str='', operation_id: str='', job_id: str='', scan_id: str='', parent_id: str='', event_id: str='', started_at: float | None=None, duration_ms: int | None=None) -> None
```
**`backend/app/services/payment_service.py`** — صاحب: X5
```
PAYMENT_LATER = 'پرداخت به\u200cزودی فعال می\u200cشود'
def commission_toman(amount: int, bps: int | None=None) -> int
async def idpay_request(*, amount_toman: int, description: str, callback_url: str, order_id: str, api_key: str, sandbox: bool=False, name: str='', phone: str='') -> dict
async def idpay_verify(*, order_id: str, authority: str, api_key: str, sandbox: bool=False, amount_toman: int=0) -> dict
def resolve_sale_gateway(row: dict | None=None) -> dict
async def zarinpal_request(*, amount_toman: int, description: str, callback_url: str, mobile: str='', merchant: str='') -> dict
async def zarinpal_verify(*, amount_toman: int, authority: str, merchant: str='') -> dict
```
**`backend/app/services/settings_service.py`** — صاحب: X5
```
def get_settings() -> dict
```
**`backend/app/services/tenant_index_service.py`** — صاحب: X5
```
def load() -> dict
def rebuild(all_rows: list[tuple[str, dict]]) -> dict  # Full rebuild from (phone, {shop, orders}) pairs.
def slug_owner(index: dict, slug: str) -> str | None
```
**`backend/app/services/tenant_lock.py`** — صاحب: X5
```
def tenant_file_lock(name: str='shop') -> Iterator[None]
```
**`backend/app/services/wallet_service.py`** — صاحب: X5
```
def consume_sms() -> dict
def credit_sale(*, amount: int, commission: int, order_id: str, note: str, owner: str) -> dict
def refund_sms(charged: int=0) -> dict
```
**`backend/app/state_store.py`** — صاحب: X5
```
def current_tenant() -> str
def iter_tenants() -> list[str]
def read_json(name: str, default: Any, *, shared: bool=False) -> Any
def shared_lock() -> Iterator[None]
def tenant_scope(phone: str) -> Iterator[None]
def write_json(name: str, payload: Any, *, shared: bool=False) -> None
```
**`frontend/components/auth-image.tsx`** — صاحب: X5
```
export function AuthImage(
```

**API بک‌اند که صفحه‌هایت صدا می‌زنند** (شکل پاسخ را از صاحبش بپرس، فایل را کامل نخوان):

- `/billing/coupon-preview`, `/billing/subscribe` ← `backend/app/api/billing.py` (X5)
- `/settings`, `/settings/support/hub`, `/settings/support/my-tickets`, `/settings/support/seller-ticket` ← `backend/app/api/settings.py` (X5)

## قرارداد تو با دیگران (بدون هماهنگی امضا را عوض نکن)

- `backend/app/api/pay.py`: `router` ← X5
- `backend/app/api/storefront.py`: `router` ← X5
- `backend/app/services/arvan_dns_service.py`: `check_cname` ← X4؛ `cname_target` ← X4؛ `edge_dry` ← X4, X5, Y؛ `ensure_shop_record` ← X4؛ `hostname` ← X4؛ `is_zone_host` ← X4؛ `public_host` ← X4؛ `start_cname_setup` ← X4؛ `zone` ← X4
- `backend/app/services/catalog_sync_service.py`: `sync_live` ← X1, X4
- `backend/app/services/pay_service.py`: `create_order` ← Y؛ `ensure_pay_secret` ← X4؛ `get_order` ← Y؛ `public_order` ← Y
- `backend/app/services/storefront_service.py`: `add_product` ← X4؛ `clear_scanned_catalog` ← X3؛ `count_scanned_handle` ← X3؛ `list_products` ← X1, X2, X3, X4, Y؛ `list_sales` ← X5؛ `price_label` ← X4؛ `referenced_image_names` ← X2؛ `remove_product_by_title` ← X1, X4؛ `remove_scanned_handle` ← X3؛ `retitle_scanned_from_captions` ← X5؛ `upsert_scanned_product` ← X3
- `backend/app/services/support_service.py`: `create_ticket` ← X5؛ `list_all_tickets_for_hub_admin` ← X5؛ `list_tickets` ← X5؛ `reply_hub_ticket` ← X5
- `frontend/components/domain-menu.tsx`: `DomainMenu` ← X4؛ `ShopState` ← X4؛ `shopHostLabel` ← X4؛ `shopPublicUrl` ← X4
- `frontend/components/shop-settings-form.tsx`: `ShopSettingsForm` ← X5
- `frontend/lib/site-host.ts`: `isPanelHost` ← X2؛ `panelOriginFromHost` ← X2

## قاعدهٔ مصرف توکن

1. اول هر کار: همین فایل + فقط فایل‌های «هسته» که به کار مربوط است. فایل بزرگ را با `grep -n` پیدا کن و با `sed -n 'a,bp'` فقط بازه را بخوان.
2. فایل دیگران را باز نکن؛ امضای لازم بالاست. اگر امضا کافی نبود، از صاحبش در فایل گزارشش بپرس.
3. تست: فقط ماژول خودت، مثلاً `python -m unittest app.services.<module>_test`؛ سوییت کامل فقط پیش از PR، و فقط خلاصه: `... 2>&1 | tail -5`.
4. هرگز این‌ها را نخوان: `.zcode/**`, `.cursor/**`, `backend/app/data/router_intent_vectors.json`, `voice-gateway/sales-train.jsonl`, `voice-gateway/sales-holdout.jsonl`, `frontend/package-lock.json`, `frontend/tsconfig.tsbuildinfo`, `docs/ui-audit-live/**`, `docs/festival/**`, `docs/*.patch`, `talk.md`, `sales-agent-talk.md`, `voice-agent-talk.md`, `storefront-talk.md`, `CHANGELOG.md`.
5. خروجی ابزار را کوتاه کن: `| head`، `| tail`، `git diff --stat` پیش از `git diff`.
