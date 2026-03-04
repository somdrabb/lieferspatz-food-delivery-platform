# backend/main.py
from __future__ import annotations

from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette import status

from .database import init_db, engine
from .routers_auth import router as auth_router
from .routers_restaurants import router as restaurants_router
from .routers_orders import router as orders_router
from .routers_wallets import router as wallets_router
from .ws import router as ws_router
from .routers_paper_addons import router as paper_router
from .routers_discovery import router as discovery_router
from .routers_logs import router as logs_router
from .routers_customers import router as customers_router
from .routers_admin import router as admin_router
from .routers_vouchers import router as vouchers_router
from .routers_orders_admin import router as admin_orders_router
from .routers_checkout import router as checkout_router


app = FastAPI(title="Lieferspatz API")


# ---------------------------
# CORS (front-end at 5500)
# ---------------------------
ALLOWED_ORIGINS = [
    "http://127.0.0.1:5500",
    "http://localhost:5500",
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],     # GET, POST, PATCH, DELETE, OPTIONS …
    allow_headers=["*"],     # allow any custom header (incl. X-Admin-Token)
    expose_headers=["*"],    # let the browser read any response headers
)


# ---------------------------
# Tiny cache-busting header
# ---------------------------
@app.middleware("http")
async def add_no_store_cache_header(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


# ---------------------------
# DB bootstrap + light migrations
# ---------------------------
@app.on_event("startup")
def on_startup():
    init_db()

    # Helpful indices (ignore if already exist)
    with engine.begin() as conn:
        try:
            conn.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS idx_menuitem_restaurant_id ON menuitem(restaurant_id);"
            )
            conn.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS idx_openinghour_restaurant_id ON openinghour(restaurant_id);"
            )
            conn.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS idx_deliveryzip_restaurant_id ON deliveryzip(restaurant_id);"
            )
            conn.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS idx_order_restaurant_id ON 'order'(restaurant_id);"
            )
            conn.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS idx_orderitem_order_id ON orderitem(order_id);"
            )
            conn.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS idx_walletaccount_type_ref ON walletaccount(account_type, ref_id);"
            )
        except Exception:
            # dev only; best-effort
            pass


# ---------------------------
# Health check
# ---------------------------
@app.get("/api/health")
def health():
    return {"ok": True, "service": "lieferspatz-api"}


# ---------------------------
# Consistent error bodies
# ---------------------------
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "detail": "Invalid request data.",
            "msg": str(exc.errors()[:1])[:200],
        },
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    message = exc.detail if isinstance(exc.detail, str) else "Request failed."
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": message, "msg": message},
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    # Don’t leak stack traces to clients; server logs have details.
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Server error. Check logs.", "msg": str(exc)[:200]},
    )


# ---------------------------
# Routers
# ---------------------------
app.include_router(auth_router)
app.include_router(restaurants_router)
app.include_router(customers_router)
app.include_router(orders_router)
app.include_router(wallets_router)
app.include_router(ws_router)
app.include_router(paper_router)
app.include_router(discovery_router)
app.include_router(logs_router)
app.include_router(admin_router)
app.include_router(vouchers_router)
app.include_router(admin_orders_router)
app.include_router(checkout_router)
