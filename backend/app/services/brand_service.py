from pathlib import Path

from fastapi import HTTPException, status

from app.repositories.brand_repository import BrandRepository


class BrandService:
    def __init__(self, brands: BrandRepository) -> None:
        self.brands = brands

    def get(self) -> dict:
        data = self.brands.get()
        data["has_motion"] = (self.brands.brand_dir / "motion" / "logo-reel.mp4").is_file()
        return data

    def update(self, *, name: str | None, description: str | None) -> dict:
        current = self.brands.get()
        if name is not None:
            current["name"] = name
        if description is not None:
            current["description"] = description
        return self.brands.save(current)

    def save_logo(self, filename: str, data: bytes) -> dict:
        suffix = Path(filename).suffix.lower()
        if suffix not in {".png", ".jpg", ".jpeg", ".webp"}:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "لوگو باید تصویر باشد")
        if len(data) > 5 * 1024 * 1024:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "حجم لوگو زیاد است")
        self.brands.save_logo(data)
        return self.brands.get()

    def save_character(self, filename: str, data: bytes) -> dict:
        suffix = Path(filename).suffix.lower()
        if suffix not in {".png", ".jpg", ".jpeg", ".webp"}:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "تصویر کاراکتر باید تصویر باشد")
        if len(data) > 8_000_000:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "حجم تصویر زیاد است")
        self.brands.save_character(data)
        return self.brands.get()

    def logo_file(self) -> Path:
        path = self.brands.ensure_logo()
        if not path.is_file():
            raise HTTPException(status.HTTP_404_NOT_FOUND, "لوگو نیست")
        return path

    def character_file(self) -> Path:
        path = self.brands.character_path
        if not path.is_file():
            raise HTTPException(status.HTTP_404_NOT_FOUND, "کاراکتر نیست")
        return path

    def motion_file(self, name: str) -> Path:
        safe = Path(name).name
        motion = (self.brands.brand_dir / "motion").resolve()
        path = (motion / safe).resolve()
        if path.parent != motion:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "مسیر نامعتبر است")
        if not path.is_file():
            raise HTTPException(status.HTTP_404_NOT_FOUND, "موشن نیست")
        return path

    def make_logo_motion(self) -> dict:
        from app.services.logo_motion_service import LogoMotionService

        return LogoMotionService(self.brands.brand_dir).render()
