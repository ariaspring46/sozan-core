from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(ROOT / ".env"), extra="ignore")

    database_url: str = "postgresql+asyncpg://sozan:sozan@127.0.0.1:5432/sozan_ads"
    redis_url: str = "redis://127.0.0.1:6379/0"
    jwt_secret: str = "change-me-to-a-long-random-secret"
    jwt_expire_minutes: int = 720
    # ورود فروشنده تا این‌همه روز بعد از آخرین باز کردن پنل می‌ماند؛ پنل هر روز با /auth/refresh تمدیدش می‌کند.
    session_days: int = 60
    admin_phone: str = "09120000000"
    otp_ttl_seconds: int = 300
    otp_dev: bool = False
    otp_provider: str = ""
    otp_global_daily_cap: int = 500
    payment_sign_secret: str = ""
    lab_login_until: str = "2026-10-31"
    otp_test_until: str = ""
    otp_test_phones: str = ""
    shop_otp_daily_cap: int = 200
    sozan_sms_provider: str = "smsir"
    sozan_sms_api_key: str = ""
    sozan_sms_template: str = ""
    telegram_bot_token: str = ""  # only the owner alert bot (telegram_alert_service)
    telegram_hub_bot_token: str = ""  # shared bot offered to sellers; never the alert bot
    telegram_chat_id: str = ""
    cutout_provider: str = "openrouter"
    cutout_api_key: str = ""
    cutout_openrouter_model: str = "google/gemini-2.5-flash-image"
    cutout_queue_limit: int = 3
    melipayamak_otp_apikey: str = ""
    melipayamak_username: str = ""
    melipayamak_body_id: str = "547036"
    melipayamak_pattern_base: str = "https://api.payamak-panel.com/post/send.asmx"
    otp_fixed_accounts: str = ""
    sms_provider: str = "smsir"
    sms_ir_api_key: str = ""
    sms_ir_template_id: str = ""
    sms_ir_token_name: str = "Code"
    zarinpal_merchant_id: str = ""
    zarinpal_amount_unit: str = "rial"
    payments_enabled: bool = True
    telegram_bot_handle: str = ""
    telegram_post_target: str = ""
    plan_price_pro: int = 1_414_000
    plan_price_promax: int = 2_414_000
    plan_price_ultra: int = 3_843_000
    plan_discount_percent: int = 0
    plan_discount_percents: str = '{"pro":0,"promax":20,"ultra":30}'
    plan_discount_until: str = ""
    phone_coupon_code: str = "SOZAN30"
    phone_coupon_percent: int = 30
    phone_coupon_until: str = ""
    commission_bps: int = 200
    sms_overage_toman: int = 200
    sms_quota_free: int = 50
    sms_quota_pro: int = 500
    sms_quota_promax: int = 2000
    trusted_ip_header: str = ""
    cors_origins: str = "http://127.0.0.1:3000,http://localhost:3000"
    campaigns_dir: str = str(ROOT / "campaigns")
    fonts_dir: str = str(ROOT / "brand" / "fonts")
    audio_bed: str = str(ROOT / "brand" / "audio" / "bed.mp3")
    brand_dir: str = str(ROOT / "brand")
    state_dir: str = str(ROOT / "backend" / "data")
    site_builder_dir: str = "/home/demon/local-ai/smoke-workspace/site-builder"
    local_llm_url: str = "http://127.0.0.1:9292/v1"
    local_llm_model: str = "qwen3.8-27b"
    local_llm_token: str = "sk-local"
    chat_llm_model: str = "qwen3.8-27b"
    studio_llm_model: str = "qwen3.5-9b"
    cloud_llm_url: str = ""
    cloud_llm_model: str = "DeepSeek-V4-Pro"
    cloud_llm_token: str = Field(default="", validation_alias=AliasChoices("CLOUD_LLM_TOKEN", "OLLAMA_API_KEY"))
    cloud_llm_auth: str = "Bearer"
    cloud_llm_proxy: str = ""
    open_router_api_token: str = ""
    cloud_llm_fallback_url: str = ""
    cloud_llm_fallback_model: str = ""
    cloud_llm_fallback_token: str = ""
    cloud_llm_fallback_auth: str = "Bearer"
    studio_cloud_url: str = ""
    studio_cloud_model: str = "Gemini-3.1-Flash-Lite-Preview"
    studio_cloud_token: str = Field(default="", validation_alias=AliasChoices("STUDIO_CLOUD_TOKEN", "GEMINI_API_KEY"))
    studio_cloud_auth: str = "Bearer"
    arvan_api_key: str = ""
    arvan_zone: str = "sozan-core.ir"
    arvan_origin_ip: str = ""
    arvan_origin_port: int = 80
    # SMS, payment and Arvan calls leave from this address (app/egress.py); empty = ARVAN_ORIGIN_IP
    egress_source_ip: str = ""
    gateway_sozan_url: str = ""
    channel_proxy: str = ""
    # Second SOCKS when channel_proxy cannot connect. Foreign hosts only; Iranian APIs stay direct.
    channel_proxy_fallback: str = ""
    sozan_npm_proxy: str = ""
    public_api_url: str = "https://api.sozan-core.ir"
    panel_url: str = "https://app.sozan-core.ir"
    instagram_app_id: str = ""
    instagram_app_secret: str = ""
    instagram_redirect_uri: str = ""
    unipile_dsn: str = ""
    unipile_api_key: str = ""
    unipile_proxy: str = ""
    sendbox_base_url: str = "https://api.sendbox.chat/api/v1"
    sendbox_api_key: str = ""
    sendbox_oauth_url: str = ""
    sendbox_webhook_secret: str = ""
    # While set to a future ISO date, the old JWT-derived webhook token is accepted too (rotation window).
    sendbox_webhook_legacy_until: str = ""
    decider_enabled: bool = False
    decider_tenants: str = "09135409482"
    decider_model: str = "perplexity/pplx-decider-v1.1-27b"
    decider_url: str = "https://openrouter.ai/api/alpha/decisions"
    decider_alt_url: str = "https://openrouter.ai/api/v1/api/alpha/decisions"
    decider_min_prob: float = 0.6
    decider_min_margin: float = 0.2
    decider_pro_model: str = "deepseek/deepseek-v4-pro"

    @property
    def cors_origin_list(self) -> list[str]:
        return [x.strip() for x in self.cors_origins.split(",") if x.strip()]

    @property
    def otp_test_phone_set(self) -> frozenset[str]:
        from app.phone import normalize_phone

        out: set[str] = set()
        for part in self.otp_test_phones.split(","):
            try:
                out.add(normalize_phone(part))
            except ValueError:
                continue
        return frozenset(out)

    @property
    def otp_fixed_map(self) -> dict[str, str]:
        from app.phone import normalize_phone

        out: dict[str, str] = {}
        for part in self.otp_fixed_accounts.split(","):
            part = part.strip()
            if not part or ":" not in part:
                continue
            phone_raw, code_raw = part.split(":", 1)
            try:
                phone = normalize_phone(phone_raw)
            except ValueError:
                continue
            code = "".join(ch for ch in code_raw if ch.isdigit())
            if len(code) != 6:
                continue
            out[phone] = code
        return out

    @property
    def campaigns_path(self) -> Path:
        return Path(self.campaigns_dir).resolve()

    @property
    def fonts_path(self) -> Path:
        return Path(self.fonts_dir).resolve()

    @property
    def audio_bed_path(self) -> Path:
        return Path(self.audio_bed).resolve()

    @property
    def brand_path(self) -> Path:
        return Path(self.brand_dir).resolve()

    @property
    def state_path(self) -> Path:
        return Path(self.state_dir).resolve()

    @property
    def factory_script(self) -> Path:
        return Path(self.site_builder_dir).resolve() / "tools" / "sozan_factory_fastpath.py"


settings = Settings()
