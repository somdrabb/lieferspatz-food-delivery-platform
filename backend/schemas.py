from typing import List, Optional, Dict, Any
from pydantic import BaseModel
from sqlmodel import SQLModel
from datetime import datetime
from typing import Literal

# ---------- Auth / create payloads ----------

class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"

class LoginReq(BaseModel):
    email_or_name: str
    password: str

class CustomerCreate(BaseModel):
    email: str
    first_name: str
    last_name: str
    street: str
    postal_code: str
    password: str
    city: Optional[str] = None
    phone: Optional[str] = None


class CustomerUpdate(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    street: Optional[str] = None
    postal_code: Optional[str] = None
    city: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None


class CustomerOut(BaseModel):
    id: int
    email: str
    first_name: str
    last_name: str
    street: str
    postal_code: str
    city: Optional[str] = None
    phone: Optional[str] = None

    class Config:
        orm_mode = True

class RestaurantCreate(BaseModel):
    name: str
    email: str
    password: str


class RestaurantRegistrationResponse(BaseModel):
    status: Literal["pending"]
    message: str

class RestaurantPasswordReset(BaseModel):
    name: str
    new_password: str
    secret: Optional[str] = None


class CustomerAddressCreate(BaseModel):
    label: Optional[str] = None
    street: str
    city: str
    postal_code: str
    country: str = "DE"
    phone: Optional[str] = None
    instructions: Optional[str] = None
    is_default: bool = False


class CustomerAddressOut(CustomerAddressCreate):
    id: int
    created_at: str


class AdminOpeningHourIn(BaseModel):
    weekday: int
    open_time: str
    close_time: str


class AdminRestaurantCreate(BaseModel):
    name: str
    email: Optional[str] = None
    street: str
    postal_code: str
    description: str
    password: str
    image_url: Optional[str] = None
    city: Optional[str] = None
    min_order_cents: Optional[int] = 0
    delivery_fee_cents: Optional[int] = 0
    prep_time_min: Optional[int] = 20
    is_online: Optional[bool] = True
    is_approved: Optional[bool] = True
    is_demo: Optional[bool] = False
    busy_until: Optional[str] = None
    extra: Optional[Dict[str, Any]] = None
    delivery_zips: Optional[List[str]] = None
    opening_hours: Optional[List[AdminOpeningHourIn]] = None


class AdminRestaurantUpdate(BaseModel):
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
    is_demo: Optional[bool] = None
    busy_until: Optional[str] = None
    extra: Optional[Dict[str, Any]] = None
    password: Optional[str] = None
    delivery_zips: Optional[List[str]] = None
    opening_hours: Optional[List[AdminOpeningHourIn]] = None


class VoucherCreate(BaseModel):
    code: str
    label: Optional[str] = None
    initial_balance_cents: int
    valid_from: Optional[str] = None
    valid_until: Optional[str] = None
    max_redemptions: Optional[int] = None
    is_active: bool = True


class VoucherUpdate(BaseModel):
    label: Optional[str] = None
    balance_cents: Optional[int] = None
    valid_from: Optional[str] = None
    valid_until: Optional[str] = None
    max_redemptions: Optional[int] = None
    is_active: Optional[bool] = None


class VoucherOut(BaseModel):
    id: int
    code: str
    label: Optional[str]
    initial_balance_cents: int
    balance_cents: int
    currency: str
    valid_from: Optional[str]
    valid_until: Optional[str]
    max_redemptions: Optional[int]
    is_active: bool
    created_at: str


class VoucherRedeemRequest(BaseModel):
    code: str
    amount_cents: Optional[int] = None


class CartItemCreate(BaseModel):
    menu_item_id: int
    quantity: int


class CheckoutAddress(BaseModel):
    street: str
    city: str
    postal_code: str
    country: str = "DE"
    label: Optional[str] = None
    phone: Optional[str] = None
    instructions: Optional[str] = None
    save_address: bool = False


class CheckoutPayment(BaseModel):
    method: Literal[
        "card",
        "cash",
        "voucher",
        "wallet",
        "klarna",
        "visa",
        "mastercard",
        "apple_pay",
        "google_pay",
    ] = "card"
    voucher_code: Optional[str] = None


class OrderCheckout(BaseModel):
    restaurant_id: int
    address: CheckoutAddress
    items: List[CartItemCreate]
    payment: CheckoutPayment
    note_for_kitchen: Optional[str] = None


class CartItemPreview(BaseModel):
    menu_item_id: int
    name: str
    price_cents: int
    quantity: int
    line_total_cents: int


class CheckoutBreakdown(BaseModel):
    subtotal_cents: int
    shipping_cents: int
    voucher_amount_cents: int
    total_cents: int
    wallet_charge_cents: int
    payment_due_cents: int


class CheckoutPreviewOut(BaseModel):
    restaurant_id: int
    restaurant_name: str
    items: List[CartItemPreview]
    breakdown: CheckoutBreakdown


class CheckoutResultOut(CheckoutPreviewOut):
    order_id: int
    order_status: str
    payment_status: str


class VoucherRedeemOut(BaseModel):
    voucher_id: int
    code: str
    label: Optional[str]
    applied_amount_cents: int
    available_balance_cents: int
    remaining_balance_cents: int
    currency: str
    valid_from: Optional[str] = None
    valid_until: Optional[str] = None


class OrderSummaryItem(BaseModel):
    id: int
    name: str
    quantity: int
    price_cents: int


class OrderSummaryOut(BaseModel):
    id: int
    public_id: Optional[str] = None
    restaurant_id: int
    restaurant_public_id: Optional[str] = None
    customer_id: int
    status: str
    payment_status: str
    subtotal_cents: int
    shipping_cents: int
    voucher_amount_cents: int
    total_cents: int
    created_at: str
    voucher_code: Optional[str] = None
    items: List[OrderSummaryItem]

class CartItem(BaseModel):
    menu_item_id: int
    quantity: int

class OrderCreate(BaseModel):
    restaurant_id: int
    items: List[CartItem]
    note_for_kitchen: Optional[str] = None


# ---------- Safe response models (hide password_hash) ----------

class RestaurantOut(BaseModel):
    id: int
    public_id: Optional[str] = None
    email: Optional[str] = None
    name: str
    street: str
    postal_code: str
    city: Optional[str] = None
    description: str
    image_url: Optional[str] = None
    created_at: str

    # NEW fields visible to clients
    min_order_cents: int
    delivery_fee_cents: int
    prep_time_min: int
    is_online: bool
    is_approved: bool
    busy_until: Optional[datetime] = None
    extra: Optional[Dict[str, Any]] = None

    class Config:
        orm_mode = True
##new added 

class RestaurantUpdate(BaseModel):
    # what owners can change
    email: Optional[str] = None
    description: Optional[str] = None
    image_url: Optional[str] = None
    min_order_cents: Optional[int] = None
    delivery_fee_cents: Optional[int] = None
    prep_time_min: Optional[int] = None
    is_online: Optional[bool] = None
    busy_until: Optional[datetime] = None  # ISO string accepted
    is_approved: Optional[bool] = None

class MenuItemBase(BaseModel):
    name: str
    description: Optional[str] = None
    price_cents: int
    image_url: Optional[str] = None
    extra: Optional[Dict[str, Any]] = None   # optional structured metadata

class MenuItemCreate(MenuItemBase):
    pass

class MenuItemUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    price_cents: Optional[int] = None
    image_url: Optional[str] = None
    extra: Optional[Dict[str, Any]] = None

class MenuItemOut(BaseModel):
    id: int
    restaurant_id: int
    name: str
    description: Optional[str] = None
    price_cents: int
    image_url: Optional[str] = None
    extra: Optional[Dict[str, Any]] = None

    class Config:
        orm_mode = True


class OpeningHourOut(BaseModel):
    id: int
    restaurant_id: int
    weekday: int           # 0=Mon .. 6=Sun
    open_time: str         # "HH:MM"
    close_time: str        # "HH:MM"


class OpeningHourCreate(BaseModel):
    weekday: int
    open_time: str
    close_time: str

class DeliveryZipOut(BaseModel):
    id: int
    restaurant_id: int
    postal_code: str


class DeliveryZipCreate(BaseModel):
    postal_code: str

class RestaurantDetailOut(BaseModel):
    restaurant: RestaurantOut
    menu: List[MenuItemOut]
    opening_hours: List[OpeningHourOut]
    delivery_zips: List[DeliveryZipOut]


# ---------- Update payloads for PATCH ----------

class OpeningHourUpdate(BaseModel):
    weekday: Optional[int] = None
    open_time: Optional[str] = None
    close_time: Optional[str] = None

class DeliveryZipUpdate(BaseModel):
    postal_code: str

# ---------- Added New  ----------
class OrderItemSnapshotOut(SQLModel):
    menu_item_id: int
    name_snapshot: str
    price_cents_snapshot: int
    quantity: int

class CustomerSlimOut(SQLModel):
    id: int
    first_name: str
    last_name: str
    street: Optional[str] = None
    postal_code: str
    city: Optional[str] = None
    phone: Optional[str] = None

class OrderOut(SQLModel):
    id: int
    public_id: Optional[str] = None
    customer_id: int
    restaurant_id: int
    restaurant_public_id: Optional[str] = None
    status: str
    payment_status: str
    payment_method: Optional[str] = None
    payment_reference: Optional[str] = None
    address_id: Optional[int] = None
    voucher_id: Optional[int] = None
    voucher_code: Optional[str] = None
    note_for_kitchen: Optional[str] = ""
    subtotal_cents: int
    shipping_cents: int
    voucher_amount_cents: int
    total_cents: int
    fee_platform_cents: int
    payout_rest_cents: int
    created_at: str
    updated_at: str
    confirmed_at: Optional[str] = None
    closed_at: Optional[str] = None

class OrderDetailOut(SQLModel):
    order: OrderOut
    items: List[OrderItemSnapshotOut]
    customer: CustomerSlimOut
    address: Optional[CustomerAddressOut] = None
