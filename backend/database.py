# backend/database.py
import os
from pathlib import Path
from sqlmodel import SQLModel, create_engine, Session, select
from sqlalchemy import event

DB_URL = os.getenv("DATABASE_URL")
if not DB_URL:
    DB_PATH = Path(__file__).resolve().parent.parent / "lieferspatz.db"
    DB_URL = f"sqlite:///{DB_PATH}"

connect_args = {"check_same_thread": False} if DB_URL.startswith("sqlite") else {}
engine = create_engine(DB_URL, echo=False, connect_args=connect_args)

# Ensure SQLite enforces foreign keys
if DB_URL.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def _fk_pragma(dbapi_connection, connection_record):
        try:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON;")
            cursor.close()
        except Exception:
            pass

def init_db():
    # Import models so SQLModel sees all tables before create_all
    from . import models  # noqa: F401
    SQLModel.metadata.create_all(engine)

    if engine.url.get_backend_name().startswith("sqlite"):
        with engine.begin() as conn:
            # restaurant tweaks
            cols = [row[1] for row in conn.exec_driver_sql("PRAGMA table_info(restaurant);").fetchall()]
            if "extra" not in cols:
                conn.exec_driver_sql("ALTER TABLE restaurant ADD COLUMN extra TEXT;")
            if "city" not in cols:
                conn.exec_driver_sql("ALTER TABLE restaurant ADD COLUMN city TEXT;")
            if "public_id" not in cols:
                conn.exec_driver_sql("ALTER TABLE restaurant ADD COLUMN public_id TEXT;")
            if "email" not in cols:
                conn.exec_driver_sql("ALTER TABLE restaurant ADD COLUMN email TEXT;")
            if "is_approved" not in cols:
                conn.exec_driver_sql("ALTER TABLE restaurant ADD COLUMN is_approved INTEGER NOT NULL DEFAULT 0;")
                conn.exec_driver_sql("UPDATE restaurant SET is_approved = 1 WHERE is_approved = 0;")
            conn.exec_driver_sql("CREATE UNIQUE INDEX IF NOT EXISTS idx_restaurant_public_id ON restaurant(public_id);")
            conn.exec_driver_sql(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_restaurant_email_unique "
                "ON restaurant(email) WHERE email IS NOT NULL;"
            )

            # menuitem tweaks
            cols = [row[1] for row in conn.exec_driver_sql("PRAGMA table_info(menuitem);").fetchall()]
            if "extra_json" not in cols:
                conn.exec_driver_sql("ALTER TABLE menuitem ADD COLUMN extra_json TEXT;")

            # customer tweaks
            cols = [row[1] for row in conn.exec_driver_sql("PRAGMA table_info(customer);").fetchall()]
            if "city" not in cols:
                conn.exec_driver_sql("ALTER TABLE customer ADD COLUMN city TEXT;")
            if "phone" not in cols:
                conn.exec_driver_sql("ALTER TABLE customer ADD COLUMN phone TEXT;")

            # order items
            cols = [row[1] for row in conn.exec_driver_sql("PRAGMA table_info(orderitem);").fetchall()]
            if "restaurant_id" not in cols:
                conn.exec_driver_sql(
                    "ALTER TABLE orderitem ADD COLUMN restaurant_id INTEGER REFERENCES restaurant(id);"
                )

            # order columns
            cols = [row[1] for row in conn.exec_driver_sql("PRAGMA table_info('order');").fetchall()]
            if "address_id" not in cols:
                conn.exec_driver_sql(
                    "ALTER TABLE 'order' ADD COLUMN address_id INTEGER REFERENCES customeraddress(id);"
                )
            if "voucher_id" not in cols:
                conn.exec_driver_sql(
                    "ALTER TABLE 'order' ADD COLUMN voucher_id INTEGER REFERENCES voucher(id);"
                )
            if "payment_status" not in cols:
                conn.exec_driver_sql(
                    "ALTER TABLE 'order' ADD COLUMN payment_status TEXT NOT NULL DEFAULT 'pending';"
                )
            if "payment_method" not in cols:
                conn.exec_driver_sql("ALTER TABLE 'order' ADD COLUMN payment_method TEXT;")
            if "payment_reference" not in cols:
                conn.exec_driver_sql("ALTER TABLE 'order' ADD COLUMN payment_reference TEXT;")
            if "shipping_cents" not in cols:
                conn.exec_driver_sql(
                    "ALTER TABLE 'order' ADD COLUMN shipping_cents INTEGER NOT NULL DEFAULT 0;"
                )
            if "voucher_amount_cents" not in cols:
                conn.exec_driver_sql(
                    "ALTER TABLE 'order' ADD COLUMN voucher_amount_cents INTEGER NOT NULL DEFAULT 0;"
                )
            if "admin_visible" not in cols:
                conn.exec_driver_sql(
                    "ALTER TABLE 'order' ADD COLUMN admin_visible INTEGER NOT NULL DEFAULT 1;"
                )
            if "hidden_for_customer" not in cols:
                conn.exec_driver_sql(
                    "ALTER TABLE 'order' ADD COLUMN hidden_for_customer INTEGER NOT NULL DEFAULT 0;"
                )
            if "hidden_for_restaurant" not in cols:
                conn.exec_driver_sql(
                    "ALTER TABLE 'order' ADD COLUMN hidden_for_restaurant INTEGER NOT NULL DEFAULT 0;"
                )
            if "updated_at" not in cols:
                conn.exec_driver_sql(
                    "ALTER TABLE 'order' ADD COLUMN updated_at TEXT NOT NULL DEFAULT '1970-01-01T00:00:00Z';"
                )
                conn.exec_driver_sql(
                    "UPDATE 'order' SET updated_at = created_at WHERE updated_at = '1970-01-01T00:00:00Z';"
                )
            if "public_id" not in cols:
                conn.exec_driver_sql("ALTER TABLE 'order' ADD COLUMN public_id TEXT;")
            conn.exec_driver_sql("CREATE UNIQUE INDEX IF NOT EXISTS idx_order_public_id ON 'order'(public_id);")

            # voucher columns
            cols = [row[1] for row in conn.exec_driver_sql("PRAGMA table_info(voucher);").fetchall()]
            if "label" not in cols:
                conn.exec_driver_sql("ALTER TABLE voucher ADD COLUMN label TEXT;")
            if "valid_from" not in cols:
                conn.exec_driver_sql("ALTER TABLE voucher ADD COLUMN valid_from TEXT;")
            if "valid_until" not in cols:
                conn.exec_driver_sql("ALTER TABLE voucher ADD COLUMN valid_until TEXT;")
            if "max_redemptions" not in cols:
                conn.exec_driver_sql("ALTER TABLE voucher ADD COLUMN max_redemptions INTEGER;")
            if "is_active" not in cols:
                conn.exec_driver_sql("ALTER TABLE voucher ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1;")

            # voucher redemptions columns
            cols = [row[1] for row in conn.exec_driver_sql("PRAGMA table_info(voucherredemption);").fetchall()]
            if "amount_cents" not in cols:
                conn.exec_driver_sql(
                    "ALTER TABLE voucherredemption ADD COLUMN amount_cents INTEGER NOT NULL DEFAULT 0;"
                )
            if "redeemed_at" not in cols:
                conn.exec_driver_sql(
                    "ALTER TABLE voucherredemption ADD COLUMN redeemed_at TEXT NOT NULL DEFAULT '1970-01-01T00:00:00Z';"
                )

            # deleted restaurant table
            conn.exec_driver_sql(
                """
                CREATE TABLE IF NOT EXISTS deletedrestaurant (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    original_restaurant_id INTEGER,
                    restaurant_public_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    deleted_at TEXT NOT NULL,
                    reason TEXT,
                    deleted_by TEXT,
                    extra_json TEXT NOT NULL DEFAULT '{}'
                );
                """
            )
            cols = [row[1] for row in conn.exec_driver_sql("PRAGMA table_info(deletedrestaurant);").fetchall()]
            if "reason" not in cols:
                conn.exec_driver_sql("ALTER TABLE deletedrestaurant ADD COLUMN reason TEXT;")
            if "deleted_by" not in cols:
                conn.exec_driver_sql("ALTER TABLE deletedrestaurant ADD COLUMN deleted_by TEXT;")
            conn.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS idx_deletedrestaurant_public_id ON deletedrestaurant(restaurant_public_id);"
            )

            # deleted order table
            conn.exec_driver_sql(
                """
                CREATE TABLE IF NOT EXISTS deletedorder (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_id INTEGER,
                    order_public_id TEXT,
                    restaurant_id INTEGER,
                    restaurant_public_id TEXT,
                    customer_id INTEGER,
                    deleted_at TEXT NOT NULL,
                    deleted_by TEXT,
                    reason TEXT,
                    details_json TEXT NOT NULL DEFAULT '{}'
                );
                """
            )
            conn.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS idx_deletedorder_public_id ON deletedorder(order_public_id);"
            )

            # gdpr request table
            conn.exec_driver_sql(
                """
                CREATE TABLE IF NOT EXISTS gdprrequest (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    requester_type TEXT NOT NULL,
                    requester_id INTEGER,
                    requester_email TEXT,
                    request_type TEXT NOT NULL DEFAULT 'export',
                    status TEXT NOT NULL DEFAULT 'open',
                    details TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    processed_at TEXT,
                    processed_by TEXT,
                    resolution_notes TEXT
                );
                """
            )
            conn.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS idx_gdprrequest_status ON gdprrequest(status);"
            )

    with Session(engine) as session:
        _ensure_public_ids(session)

def get_session():
    with Session(engine) as session:
        yield session


def _ensure_public_ids(session: Session) -> None:
    from .models import Order, Restaurant
    from .utils import generate_public_id

    updated = False

    orders = session.exec(select(Order).where(Order.public_id.is_(None))).all()
    for order in orders:
        order.public_id = generate_public_id(session, Order, "public_id", prefix="ORD")
        updated = True

    restaurants = session.exec(select(Restaurant).where(Restaurant.public_id.is_(None))).all()
    for restaurant in restaurants:
        restaurant.public_id = generate_public_id(session, Restaurant, "public_id", prefix="RST")
        updated = True

    if updated:
        session.commit()
