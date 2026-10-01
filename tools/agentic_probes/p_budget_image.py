# Is cloud image generation gated by the AI budget cap like text is?
import tempfile
from unittest.mock import patch
from app.config import settings
from app.state_store import tenant_scope
from app.services import ai_budget_service as ab, image_provider_service as ip

cloud_calls = []
def fake_chain(prompt, size, model, raw, **kw):
    cloud_calls.append(model); return {"png": b"x" * 4096, "model": model, "provider": "openrouter", "cost": 0.04, "charged": True, "failed": False}

with patch.object(settings, "state_dir", tempfile.mkdtemp()), tenant_scope("09120001111"), \
     patch("app.services.plan_service.current_plan_id", return_value="free"), patch.object(ip, "_cloud_chain", fake_chain), \
     patch.object(ip, "emit_later"), patch.object(ip, "_ask_subject", lambda png, s: (True, 0.001)):
    ab.record_cost(surface="studio", usd=5.0)                          # far above any plan's daily cap
    print("text cloud blocked for studio:", ab.cloud_blocked(surface="studio"), "| image:", ab.cloud_blocked(surface="image"))
    for _ in range(3):
        ip.generate_image("a silver necklace on marble", plan="free", subject="گردنبند")
    print("cloud image calls made while over the cap:", len(cloud_calls))
