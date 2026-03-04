# backend/models.py
from typing import Optional, List, Dict, Any
from datetime import datetime
import json
from sqlmodel import SQLModel, Field, Relationship
from sqlalchemy import Column, JSON


def utcnow_str() -> str:
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


# -------------------------
# Core entities
# -------------------------

class Customer(SQLModel, table=True):
    __tablename__ = "customer"

    id: Optional[int] = Field(default=None, primary_key=True)
    email: str
    first_name: str
    last_name: str
    street: str
    postal_code: str
    city: Optional[str] = None
    phone: Optional[str] = None
    password_hash: str
    created_at: str = Field(default_factory=utcnow_str)

    orders: List["Order"] = Relationship(back_populates="customer")

    addresses: List["CustomerAddress"] = Relationship(back_populates="customer")


class Restaurant(SQLModel, table=True):
    __tablename__ = "restaurant"

    id: Optional[int] = Field(default=None, primary_key=True)
    public_id: Optional[str] = Field(default=None, index=True)
    email: Optional[str] = Field(default=None, index=True)
    name: str
    street: str
    postal_code: str
    city: Optional[str] = None
    description: str
    image_url: Optional[str] = None

    min_order_cents: int = 0
    delivery_fee_cents: int = 0
    prep_time_min: int = 20
    is_online: bool = True
    is_approved: bool = Field(default=False, nullable=False)
    is_demo: bool = Field(default=False, nullable=False)

    busy_until: Optional[str] = None  # ISO UTC string
    created_at: str = Field(default_factory=utcnow_str)
    password_hash: str

    # JSON-ish column; on SQLite becomes TEXT
    extra: Optional[Dict[str, Any]] = Field(default=None, sa_column=Column(JSON))

    menu_items: List["MenuItem"] = Relationship(back_populates="restaurant")
    opening_hours: List["OpeningHour"] = Relationship(back_populates="restaurant")
    zips: List["DeliveryZip"] = Relationship(back_populates="restaurant")
    orders: List["Order"] = Relationship(back_populates="restaurant")


class RestaurantUpdate(SQLModel):
    name: Optional[str] = None
    email: Optional[str] = None
    street: Optional[str] = None
    city: Optional[str] = None
    postal_code: Optional[str] = None
    description: Optional[str] = None
    image_url: Optional[str] = None
    min_order_cents: Optional[int] = None
    delivery_fee_cents: Optional[int] = None
    prep_time_min: Optional[int] = None
    is_online: Optional[bool] = None
    is_approved: Optional[bool] = None
    busy_until: Optional[str] = None
    extra: Optional[Dict[str, Any]] = None


class OpeningHour(SQLModel, table=True):
    __tablename__ = "openinghour"

    id: Optional[int] = Field(default=None, primary_key=True)
    restaurant_id: int = Field(foreign_key="restaurant.id")
    weekday: int           # 0=Mon .. 6=Sun
    open_time: str         # "HH:MM"
    close_time: str        # "HH:MM"

    restaurant: Optional["Restaurant"] = Relationship(back_populates="opening_hours")


class DeliveryZip(SQLModel, table=True):
    __tablename__ = "deliveryzip"

    id: Optional[int] = Field(default=None, primary_key=True)
    restaurant_id: int = Field(foreign_key="restaurant.id")
    postal_code: str

    restaurant: Optional["Restaurant"] = Relationship(back_populates="zips")


class MenuItem(SQLModel, table=True):
    __tablename__ = "menuitem"

    id: Optional[int] = Field(default=None, primary_key=True)
    restaurant_id: int = Field(foreign_key="restaurant.id")
    name: str
    description: str
    price_cents: int
    image_url: Optional[str] = None
    extra_json: str = Field(default="{}", nullable=False)

    @property
    def extra(self) -> Dict[str, Any]:
        try:
            return json.loads(self.extra_json or "{}")
        except Exception:
            return {}

    @extra.setter
    def extra(self, val: Dict[str, Any]):
        self.extra_json = json.dumps(val or {})

    restaurant: Optional["Restaurant"] = Relationship(back_populates="menu_items")


# -------------------------
# Wallet
# -------------------------

class WalletAccount(SQLModel, table=True):
    __tablename__ = "walletaccount"

    id: Optional[int] = Field(default=None, primary_key=True)
    account_type: str  # 'customer' | 'restaurant' | 'platform'
    ref_id: Optional[int] = None
    balance_cents: int = 0

    txns: List["WalletTxn"] = Relationship(back_populates="account")


class WalletTxn(SQLModel, table=True):
    __tablename__ = "wallettxn"

    id: Optional[int] = Field(default=None, primary_key=True)
    account_id: int = Field(foreign_key="walletaccount.id")
    amount_cents: int
    created_at: str = Field(default_factory=utcnow_str)
    reason: str
    order_id: Optional[int] = None

    account: Optional["WalletAccount"] = Relationship(back_populates="txns")


# -------------------------
# Addresses
# -------------------------

class CustomerAddress(SQLModel, table=True):
    __tablename__ = "customeraddress"

    id: Optional[int] = Field(default=None, primary_key=True)
    customer_id: int = Field(foreign_key="customer.id")
    label: Optional[str] = None
    street: str
    city: str
    postal_code: str
    country: str = "DE"
    phone: Optional[str] = None
    instructions: Optional[str] = None
    is_default: bool = False
    created_at: str = Field(default_factory=utcnow_str)

    customer: Optional["Customer"] = Relationship(back_populates="addresses")
    orders: List["Order"] = Relationship(back_populates="address")


# -------------------------
# Vouchers
# -------------------------

class Voucher(SQLModel, table=True):
    __tablename__ = "voucher"

    id: Optional[int] = Field(default=None, primary_key=True)
    code: str = Field(index=True, unique=True)
    label: Optional[str] = None
    currency: str = Field(default="EUR", nullable=False)
    initial_balance_cents: int = Field(nullable=False)
    balance_cents: int = Field(nullable=False)
    valid_from: Optional[str] = None
    valid_until: Optional[str] = None
    max_redemptions: Optional[int] = None
    is_active: bool = Field(default=True, nullable=False)
    created_at: datetime = Field(default_factory=datetime.utcnow)

    # Orders that have this voucher attached
    orders: List["Order"] = Relationship(
        back_populates="voucher",
        sa_relationship_kwargs={"cascade": "save-update"}  # keep orders; don't delete via voucher
    )

    # Individual redemption records
    redemptions: List["VoucherRedemption"] = Relationship(
        back_populates="voucher",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"}
    )


class VoucherRedemption(SQLModel, table=True):
    __tablename__ = "voucherredemption"

    id: Optional[int] = Field(default=None, primary_key=True)
    voucher_id: int = Field(foreign_key="voucher.id")
    order_id: int = Field(foreign_key="order.id")
    amount_cents: int = Field(default=0, nullable=False)
    redeemed_at: str = Field(default_factory=utcnow_str)

    voucher: "Voucher" = Relationship(back_populates="redemptions")
    order: "Order" = Relationship(back_populates="voucher_redemptions")


# -------------------------
# Orders
# -------------------------

class Order(SQLModel, table=True):
    __tablename__ = "order"

    id: Optional[int] = Field(default=None, primary_key=True)
    public_id: Optional[str] = Field(default=None, index=True)

    # FKs
    customer_id: Optional[int] = Field(default=None, foreign_key="customer.id")
    restaurant_id: Optional[int] = Field(default=None, foreign_key="restaurant.id")
    address_id: Optional[int] = Field(default=None, foreign_key="customeraddress.id")
    voucher_id: Optional[int] = Field(default=None, foreign_key="voucher.id")

    # amounts & statuses
    status: str = Field(default="pending")
    payment_status: str = Field(default="pending", nullable=False)
    payment_method: Optional[str] = None
    payment_reference: Optional[str] = None

    subtotal_cents: int = Field(default=0, nullable=False)
    shipping_cents: int = Field(default=0, nullable=False)
    voucher_amount_cents: int = Field(default=0, nullable=False)
    fee_platform_cents: int = Field(default=0, nullable=False)
    payout_rest_cents: int = Field(default=0, nullable=False)
    total_cents: int = Field(default=0, nullable=False)
    admin_visible: bool = Field(default=True, nullable=False)
    hidden_for_customer: bool = Field(default=False, nullable=False)
    hidden_for_restaurant: bool = Field(default=False, nullable=False)

    note_for_kitchen: Optional[str] = None
    created_at: str = Field(default_factory=utcnow_str)
    updated_at: str = Field(default_factory=utcnow_str)
    confirmed_at: Optional[str] = None
    closed_at: Optional[str] = None

    # relationships (many-to-one)
    customer: Optional["Customer"] = Relationship(back_populates="orders")
    restaurant: Optional["Restaurant"] = Relationship(back_populates="orders")
    address: Optional["CustomerAddress"] = Relationship(back_populates="orders")

    # one-to-many children
    items: List["OrderItem"] = Relationship(
        back_populates="order",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )
    payments: List["PaymentTxn"] = Relationship(
        back_populates="order",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )
    events: List["OrderEvent"] = Relationship(
        back_populates="order",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )
    notifications: List["RestaurantNotification"] = Relationship(
        back_populates="order",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )

    # voucher links
    voucher: Optional["Voucher"] = Relationship(back_populates="orders")
    voucher_redemptions: List["VoucherRedemption"] = Relationship(
        back_populates="order",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )

    @property
    def restaurant_public_id(self) -> Optional[str]:
        return self.restaurant.public_id if self.restaurant else None

    @property
    def voucher_code(self) -> Optional[str]:
        return self.voucher.code if self.voucher else None


class OrderItem(SQLModel, table=True):
    __tablename__ = "orderitem"

    id: Optional[int] = Field(default=None, primary_key=True)
    order_id: int = Field(foreign_key="order.id")
    restaurant_id: int = Field(foreign_key="restaurant.id")
    menu_item_id: int = Field(foreign_key="menuitem.id")

    name_snapshot: str
    price_cents_snapshot: int
    quantity: int = 1

    order: "Order" = Relationship(back_populates="items")


# -------------------------
# Logs, payments, notifications
# -------------------------

class AuditLog(SQLModel, table=True):
    __tablename__ = "auditlog"

    id: Optional[int] = Field(default=None, primary_key=True)
    created_at: str = Field(default_factory=utcnow_str)
    actor_type: str  # 'customer' | 'restaurant' | 'system' | 'platform'
    actor_id: Optional[int] = None
    event: str       # e.g. 'login', 'logout', 'order_created', ...
    details_json: str = Field(default="{}", nullable=False)
    ip: Optional[str] = None


class PaymentTxn(SQLModel, table=True):
    __tablename__ = "paymenttxn"

    id: Optional[int] = Field(default=None, primary_key=True)
    order_id: int = Field(foreign_key="order.id")
    provider: str
    provider_ref: Optional[str] = None
    amount_cents: int = Field(default=0, nullable=False)
    currency: str = Field(default="EUR")
    status: str = Field(default="pending")
    meta_json: str = Field(default="{}", nullable=False)
    created_at: str = Field(default_factory=utcnow_str)
    updated_at: str = Field(default_factory=utcnow_str)

    order: "Order" = Relationship(back_populates="payments")


class OrderEvent(SQLModel, table=True):
    __tablename__ = "orderevent"

    id: Optional[int] = Field(default=None, primary_key=True)
    order_id: int = Field(foreign_key="order.id")
    event: str
    payload_json: str = Field(default="{}", nullable=False)
    created_at: str = Field(default_factory=utcnow_str)

    order: "Order" = Relationship(back_populates="events")


class RestaurantNotification(SQLModel, table=True):
    __tablename__ = "restaurantnotification"

    id: Optional[int] = Field(default=None, primary_key=True)
    restaurant_id: int = Field(foreign_key="restaurant.id")
    order_id: int = Field(foreign_key="order.id")
    type: str
    created_at: str = Field(default_factory=utcnow_str)
    is_read: int = 0

    restaurant: Optional["Restaurant"] = Relationship()
    order: "Order" = Relationship(back_populates="notifications")


class DeletedRestaurant(SQLModel, table=True):
    __tablename__ = "deletedrestaurant"

    id: Optional[int] = Field(default=None, primary_key=True)
    original_restaurant_id: Optional[int] = None
    restaurant_public_id: str = Field(index=True)
    name: str
    deleted_at: str = Field(default_factory=utcnow_str)
    reason: Optional[str] = None
    deleted_by: Optional[str] = None
    extra_json: str = Field(default="{}", nullable=False)


class DeletedOrder(SQLModel, table=True):
    __tablename__ = "deletedorder"

    id: Optional[int] = Field(default=None, primary_key=True)
    order_id: Optional[int] = None
    order_public_id: Optional[str] = Field(default=None, index=True)
    restaurant_id: Optional[int] = None
    restaurant_public_id: Optional[str] = None
    customer_id: Optional[int] = None
    deleted_at: str = Field(default_factory=utcnow_str)
    deleted_by: Optional[str] = None
    reason: Optional[str] = None
    details_json: str = Field(default="{}", nullable=False)


class GdprRequest(SQLModel, table=True):
    __tablename__ = "gdprrequest"

    id: Optional[int] = Field(default=None, primary_key=True)
    requester_type: str  # 'customer' | 'restaurant' | 'platform'
    requester_id: Optional[int] = None
    requester_email: Optional[str] = None
    request_type: str = Field(default="export")  # 'export' | 'deletion'
    status: str = Field(default="open")  # 'open' | 'in_progress' | 'completed' | 'rejected'
    details: Optional[str] = None
    created_at: str = Field(default_factory=utcnow_str)
    updated_at: str = Field(default_factory=utcnow_str)
    processed_at: Optional[str] = None
    processed_by: Optional[str] = None
    resolution_notes: Optional[str] = None
