from fastapi import APIRouter

from app.api.v1.endpoints import auth, accounts, clients, attendance, items, sales, reports

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(accounts.router)
api_router.include_router(clients.router)
api_router.include_router(attendance.router)
api_router.include_router(items.router)
api_router.include_router(sales.router)
api_router.include_router(reports.router)
