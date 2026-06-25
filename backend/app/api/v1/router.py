from fastapi import APIRouter
from app.api.v1.endpoints import (
    auth, accounts, subscriptions, clients,
    attendance, items, sales, lockers, reports, admin_setup
)

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(accounts.router)
api_router.include_router(subscriptions.router)
api_router.include_router(clients.router)
api_router.include_router(attendance.router)
api_router.include_router(items.router)
api_router.include_router(sales.router)
api_router.include_router(lockers.router)
api_router.include_router(reports.router)
api_router.include_router(admin_setup.router)