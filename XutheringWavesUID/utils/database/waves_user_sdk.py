"""launcher SDK 登录的扩展信息表。

只承载与 launcher 路径强相关、原 ``WavesUser`` 表不便承载的字段（区服字符串、
账号用户名）。其余共享字段（cookie / bat / did 等）依然落在 ``WavesUser`` 中。
"""

from typing import Any, Dict, Optional, Type, TypeVar

from sqlmodel import Field, col, select
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from gsuid_core.utils.database.base_models import BaseModel, with_session

T_WavesUserSdk = TypeVar("T_WavesUserSdk", bound="WavesUserSdk")


class WavesUserSdk(BaseModel, table=True):
    """launcher SDK 登录扩展表。"""

    __tablename__ = "WavesUserSdk"
    __table_args__: Dict[str, Any] = {"extend_existing": True}

    uid: str = Field(default="", title="鸣潮UID", index=True)
    region: str = Field(default="", title="区服")
    bat_expires_at: Optional[int] = Field(default=None, title="bat过期时戳(秒)")
    created_time: Optional[int] = Field(default=None, title="创建时间")
    updated_time: Optional[int] = Field(default=None, title="更新时间")

    @classmethod
    @with_session
    async def select_record(
        cls: Type[T_WavesUserSdk],
        session: AsyncSession,
        user_id: str,
        bot_id: str,
        uid: str,
    ) -> Optional[T_WavesUserSdk]:
        sql = select(cls).where(
            cls.user_id == user_id,
            cls.bot_id == bot_id,
            cls.uid == uid,
        )
        result = await session.execute(sql)
        return result.scalars().first()

    @classmethod
    @with_session
    async def get_region(
        cls: Type[T_WavesUserSdk],
        session: AsyncSession,
        user_id: str,
        bot_id: str,
        uid: str,
    ) -> str:
        sql = select(cls.region).where(
            cls.user_id == user_id,
            cls.bot_id == bot_id,
            cls.uid == uid,
        )
        result = await session.execute(sql)
        row = result.first()
        return str(row[0]) if row and row[0] else ""

    @classmethod
    async def upsert(
        cls: Type[T_WavesUserSdk],
        user_id: str,
        bot_id: str,
        uid: str,
        region: str,
    ) -> bool:
        """新增或更新一条记录，返回 ``True`` 表示是新增（用于触发首次绑定的副作用）。"""
        import time

        existed = await cls.select_record(user_id, bot_id, uid)
        now = int(time.time())
        if existed:
            await cls._update(user_id, bot_id, uid, region, now)
            return False

        await cls._insert(user_id, bot_id, uid, region, now)
        return True

    @classmethod
    @with_session
    async def _update(
        cls: Type[T_WavesUserSdk],
        session: AsyncSession,
        user_id: str,
        bot_id: str,
        uid: str,
        region: str,
        now: int,
    ) -> None:
        sql = (
            update(cls)
            .where(
                col(cls.user_id) == user_id,
                col(cls.bot_id) == bot_id,
                col(cls.uid) == uid,
            )
            .values(region=region, updated_time=now)
        )
        await session.execute(sql)

    @classmethod
    @with_session
    async def _insert(
        cls: Type[T_WavesUserSdk],
        session: AsyncSession,
        user_id: str,
        bot_id: str,
        uid: str,
        region: str,
        now: int,
    ) -> None:
        session.add(
            cls(
                user_id=user_id,
                bot_id=bot_id,
                uid=uid,
                region=region,
                created_time=now,
                updated_time=now,
            )
        )

    @classmethod
    @with_session
    async def update_bat_expires_at(
        cls: Type[T_WavesUserSdk],
        session: AsyncSession,
        user_id: str,
        bot_id: str,
        uid: str,
        expires_at: Optional[int],
    ) -> None:
        """access_token 续登后写入新的过期时戳, None 表示清除。"""
        sql = (
            update(cls)
            .where(
                col(cls.user_id) == user_id,
                col(cls.bot_id) == bot_id,
                col(cls.uid) == uid,
            )
            .values(bat_expires_at=expires_at)
        )
        await session.execute(sql)

    @classmethod
    @with_session
    async def delete_record(
        cls: Type[T_WavesUserSdk],
        session: AsyncSession,
        user_id: str,
        bot_id: str,
        uid: str,
    ) -> int:
        from sqlalchemy import delete as sql_delete

        sql = sql_delete(cls).where(
            col(cls.user_id) == user_id,
            col(cls.bot_id) == bot_id,
            col(cls.uid) == uid,
        )
        result = await session.execute(sql)
        return result.rowcount or 0
