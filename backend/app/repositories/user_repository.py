from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, user_id: UUID) -> User | None:
        return await self.session.get(User, user_id)

    async def get_by_phone(self, phone: str) -> User | None:
        result = await self.session.execute(select(User).where(User.phone == phone))
        return result.scalar_one_or_none()

    async def list_all(self) -> list[User]:
        result = await self.session.execute(select(User).order_by(User.created_at.desc()))
        return list(result.scalars().all())

    async def set_active(self, phone: str, *, active: bool) -> None:
        user = await self.get_by_phone(phone)
        if user is None:
            return
        user.is_active = active
        await self.session.commit()

    async def create(self, phone: str, role: str = "admin") -> User:
        user = User(phone=phone, role=role)
        self.session.add(user)
        await self.session.commit()
        await self.session.refresh(user)
        return user
