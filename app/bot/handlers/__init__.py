from .admin import router as admin_router
from .client import router as client_router

# Теперь переменные доступны для импорта снаружи
__all__ = ["admin_router", "client_router"]
