import json
from pathlib import Path
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, User as TgUser
from sqlalchemy import select

from app.database.engine import SessionLocal
from app.database.models import Tenant, User


SUPPORTED_LANGS = {"uk"}
DEFAULT_LANG = "uk"


class I18n:
    def __init__(self) -> None:
        base_path = Path(__file__).resolve().parent.parent / "locales"
        self._translations: dict[str, dict[str, str]] = {}
        for lang in SUPPORTED_LANGS:
            file_path = base_path / f"{lang}.json"
            if file_path.exists():
                self._translations[lang] = json.loads(file_path.read_text(encoding="utf-8"))
            else:
                self._translations[lang] = {}

    def normalize_lang(self, language_code: str | None) -> str:
        if not language_code:
            return DEFAULT_LANG
        short = language_code.lower().split("-")[0]
        return short if short in SUPPORTED_LANGS else DEFAULT_LANG

    def t(self, key: str, lang: str, **kwargs: Any) -> str:
        lang_map = self._translations.get(lang, {})
        fallback_map = self._translations.get(DEFAULT_LANG, {})
        template = lang_map.get(key) or fallback_map.get(key) or key
        return template.format(**kwargs)


i18n = I18n()


async def get_tenant_id_by_bot_id(bot_id: int) -> int | None:
    async with SessionLocal() as session:
        tenant = await session.scalar(
            select(Tenant).where(Tenant.bot_token.like(f"{bot_id}:%"), Tenant.is_active.is_(True))
        )
        if tenant:
            return tenant.id
    return None


class I18nMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        from_user: TgUser | None = data.get("event_from_user")
        bot = data.get("bot")
        lang = i18n.normalize_lang(from_user.language_code if from_user else None)
        tenant_id: int | None = None

        if bot:
            tenant_id = await get_tenant_id_by_bot_id(bot.id)

        if from_user:
            async with SessionLocal() as session:
                db_user = await session.scalar(select(User).where(User.telegram_id == from_user.id))
                if db_user and db_user.language_code:
                    lang = i18n.normalize_lang(db_user.language_code)
                if db_user and db_user.tenant_id is None and tenant_id is not None:
                    db_user.tenant_id = tenant_id
                    await session.commit()

        data["lang"] = lang
        data["tenant_id"] = tenant_id
        data["i18n"] = i18n
        data["t"] = lambda key, **kwargs: i18n.t(key, lang, **kwargs)
        return await handler(event, data)
