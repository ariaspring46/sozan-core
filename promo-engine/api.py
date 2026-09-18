"""API مینیمال موتور تبلیغاتی سوزان.

اجرای:
    uvicorn api:app --port 8020 --reload
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from config import settings
from engine.generate import generate, list_campaigns, status
from engine.persona import avatar_path, load_persona

app = FastAPI(title="Sozan Promo Engine", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class GenerateIn(BaseModel):
    pillar: str | None = Field(default=None, description="shop | gateway | panel")
    mood: str | None = Field(default=None, description="قالب/حال کپشن")


@app.get("/health")
async def health() -> dict:
    return {"ok": True}


@app.get("/persona")
async def get_persona() -> dict:
    return load_persona()


@app.get("/avatar")
async def get_avatar() -> FileResponse:
    path = avatar_path()
    if not path.is_file():
        raise HTTPException(404, "avatar نیست")
    return FileResponse(path, media_type="image/png")


@app.get("/character")
async def get_character() -> FileResponse:
    from engine.persona import character_path

    path = character_path()
    if not path.is_file():
        raise HTTPException(404, "تصویر کاراکتر نیست")
    return FileResponse(path, media_type="image/png")


@app.get("/status")
async def get_status() -> dict:
    return status()


@app.get("/campaigns")
async def get_campaigns() -> list[dict]:
    return list_campaigns()


@app.post("/generate")
async def post_generate(body: GenerateIn) -> dict:
    result = await generate(pillar=body.pillar, mood=body.mood)
    if not result.get("ok"):
        raise HTTPException(400, result.get("error") or "تولید ناموفق")
    return result


@app.get("/output/{slug}/{filename}")
async def get_output(slug: str, filename: str) -> FileResponse:
    safe_slug = Path(slug).name
    safe_name = Path(filename).name
    base = settings.output_path
    path = (base / safe_slug / safe_name).resolve()
    if base not in path.parents and path != base:
        raise HTTPException(400, "مسیر نامعتبر است")
    if not path.is_file():
        raise HTTPException(404, "فایل نیست")
    media = "image/png" if path.suffix.lower() == ".png" else None
    if path.suffix.lower() == ".mp4":
        media = "video/mp4"
    if path.suffix.lower() == ".md":
        media = "text/markdown; charset=utf-8"
    if path.suffix.lower() == ".zip":
        media = "application/zip"
    return FileResponse(path, media_type=media)


@app.get("/output/{slug}/out/{filename}")
async def get_output_out(slug: str, filename: str) -> FileResponse:
    return await get_output(f"{slug}/out", filename)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=settings.api_port)