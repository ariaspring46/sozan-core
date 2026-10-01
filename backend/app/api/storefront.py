import asyncio
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator

from app.security import require_permission
from app.services import catalog_sync_service, product_image_service, storefront_service

router = APIRouter(tags=["storefront"])

PRICE_NOTES = ("", "دایرکت", "تماس بگیرید")


class ProductIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    price: int = Field(default=0, ge=0)
    stock: int = Field(default=0, ge=0)
    sku: str = Field(default="", max_length=80)
    description: str = Field(default="", max_length=400)
    discount: int = Field(default=0, ge=0, le=90)
    priceNote: str = Field(default="", max_length=40)
    category: str = Field(default="", max_length=40)
    subcategory: str = Field(default="", max_length=40)
    colors: list[str] = Field(default_factory=list)
    sizes: str = Field(default="", max_length=40)
    image: str = Field(default="", max_length=200)
    images: list[str] = Field(default_factory=list)

    @field_validator("priceNote")
    @classmethod
    def note_ok(cls, value: str) -> str:
        if value not in PRICE_NOTES:
            raise ValueError("حالت قیمت معتبر نیست")
        return value

    @field_validator("colors")
    @classmethod
    def colors_ok(cls, value: list[str]) -> list[str]:
        out: list[str] = []
        for item in value:
            text = str(item).strip()[:40]
            if text and text not in out:
                out.append(text)
            if len(out) >= 6:
                break
        return out

    @field_validator("images")
    @classmethod
    def images_ok(cls, value: list[str]) -> list[str]:
        names: list[str] = []
        for item in value:
            name = Path(str(item)).name
            if name and name not in names:
                names.append(name)
            if len(names) >= 5:
                break
        return names


class ProductPatch(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    price: int | None = Field(default=None, ge=0)
    stock: int | None = Field(default=None, ge=0)
    sku: str | None = Field(default=None, max_length=80)
    description: str | None = Field(default=None, max_length=400)
    discount: int | None = Field(default=None, ge=0, le=90)
    priceNote: str | None = Field(default=None, max_length=40)
    category: str | None = Field(default=None, max_length=40)
    subcategory: str | None = Field(default=None, max_length=40)
    colors: list[str] | None = None
    sizes: str | None = Field(default=None, max_length=40)
    image: str | None = Field(default=None, max_length=200)
    images: list[str] | None = None

    @field_validator("priceNote")
    @classmethod
    def note_ok(cls, value: str | None) -> str | None:
        if value is None:
            return value
        if value not in PRICE_NOTES:
            raise ValueError("حالت قیمت معتبر نیست")
        return value

    @field_validator("colors")
    @classmethod
    def colors_ok(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return value
        out: list[str] = []
        for item in value:
            text = str(item).strip()[:40]
            if text and text not in out:
                out.append(text)
            if len(out) >= 6:
                break
        return out

    @field_validator("images")
    @classmethod
    def images_ok(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return value
        names: list[str] = []
        for item in value:
            name = Path(str(item)).name
            if name and name not in names:
                names.append(name)
            if len(names) >= 5:
                break
        return names


class StockIn(BaseModel):
    delta: int


class SaleIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    amount: int = Field(ge=0)
    customer: str = Field(default="", max_length=200)
    channel: str = Field(default="فروشگاه", max_length=80)


def _changed_images(body: ProductIn | ProductPatch | dict) -> list[str]:
    if isinstance(body, dict):
        image = str(body.get("image") or "")
        images = body.get("images") if isinstance(body.get("images"), list) else []
    else:
        data = body.model_dump(exclude_none=True)
        image = str(data.get("image") or "")
        images = data.get("images") if isinstance(data.get("images"), list) else []
    names: list[str] = []
    for item in [image, *images]:
        name = Path(str(item or "")).name
        if name and name not in names:
            names.append(name)
    return names


async def _with_sync(result: dict, changed_images: list[str] | None = None) -> dict:
    try:
        result["sync"] = await asyncio.to_thread(
            catalog_sync_service.sync_live, changed_images=changed_images or []
        )
    except Exception as exc:
        result["sync"] = {"live": False, "error": str(exc)[:200]}
    result["categories"] = storefront_service.categories()
    result["shop"] = catalog_sync_service.shop_meta()
    return result


@router.get("/catalog")
async def list_catalog(_user=Depends(require_permission("campaigns:read"))):
    data = storefront_service.list_products()
    data["categories"] = storefront_service.categories()
    data["shop"] = catalog_sync_service.shop_meta()
    return data


@router.get("/catalog/media/{name}")
async def catalog_media(name: str, _user=Depends(require_permission("campaigns:read"))):
    safe = Path(name).name
    if safe != name:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "نام نامعتبر است")
    from app.services.channel_scan_service import scan_dir as _scan_dir, unattributed_dir as _unattributed_dir

    for root in (_scan_dir().resolve(), _unattributed_dir().resolve()):
        path = (root / safe).resolve()
        if path.parent == root and path.is_file():
            return FileResponse(path)
    raise HTTPException(status.HTTP_404_NOT_FOUND, "تصویر نیست")


@router.post("/catalog/upload")
async def upload_catalog_image(
    file: UploadFile = File(...),
    _user=Depends(require_permission("campaigns:write")),
):
    data = await file.read()
    try:
        name = product_image_service.store(data, file.content_type or "", file.filename or "photo.jpg")
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return {"image": name}


@router.post("/catalog")
async def add_catalog(body: ProductIn, _user=Depends(require_permission("campaigns:write"))):
    try:
        result = storefront_service.add_product(
            title=body.title,
            price=body.price,
            stock=body.stock,
            sku=body.sku,
            description=body.description,
            discount=body.discount,
            priceNote=body.priceNote,
            category=body.category,
            subcategory=body.subcategory,
            colors=body.colors,
            sizes=body.sizes,
            image=body.image,
            images=body.images,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return await _with_sync(result, _changed_images(body))


@router.patch("/catalog/{product_id}")
async def patch_catalog(product_id: str, body: ProductPatch, _user=Depends(require_permission("campaigns:write"))):
    try:
        result = storefront_service.update_product(product_id, body.model_dump(exclude_none=True))
    except KeyError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return await _with_sync(result, _changed_images(body))


@router.delete("/catalog/{product_id}")
async def delete_catalog(product_id: str, _user=Depends(require_permission("campaigns:write"))):
    result = storefront_service.remove_product(product_id)
    for name in result.get("removedImages") or []:
        product_image_service.remove_if_unreferenced(str(name))
    return await _with_sync(result)


@router.post("/catalog/{product_id}/stock")
async def stock_catalog(product_id: str, body: StockIn, _user=Depends(require_permission("campaigns:write"))):
    try:
        result = storefront_service.adjust_stock(product_id, body.delta)
    except KeyError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return await _with_sync(result)


@router.get("/sales")
async def list_sales(_user=Depends(require_permission("campaigns:read"))):
    return storefront_service.list_sales()


@router.post("/sales")
async def add_sale(body: SaleIn, _user=Depends(require_permission("campaigns:write"))):
    try:
        return storefront_service.add_sale(
            title=body.title,
            amount=body.amount,
            customer=body.customer,
            channel=body.channel,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
