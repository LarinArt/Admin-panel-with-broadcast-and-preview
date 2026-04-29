"""Скрипт для обновления схемы базы данных с новыми полями для биллинга"""
import asyncio
import sys
from app.database.engine import init_models

if __name__ == "__main__":
    print("Обновление схемы базы данных...")
    asyncio.run(init_models())
    print("Схема базы данных обновлена успешно!")