# backend/seed.py  (Python 3.9 friendly)
import random
from typing import Optional
from sqlmodel import Session, select

from .database import engine, init_db
from .models import (
    Customer,
    Restaurant,
    MenuItem,
    OpeningHour,
    DeliveryZip,
    Order,
    OrderItem,
    WalletAccount,
    WalletTxn,
    CustomerAddress,
    Voucher,
    VoucherRedemption,
    PaymentTxn,
    OrderEvent,
    utcnow_str,
)
from .security import hash_password
from .utils import generate_public_id

PLZS = ["10115", "10117", "10119", "10243", "10405", "10557", "10785", "10969", "12045", "13353"]

ITEMS = [
    ("Margherita", "Classic tomato & mozzarella", 890),
    ("Funghi", "Mushroom pizza", 990),
    ("Carbonara", "Pasta with bacon & egg", 1190),
    ("Curry", "Chicken curry & rice", 1090),
    ("Pad Thai", "Rice noodles, peanuts", 1190),
    ("Burger", "Beef patty, cheddar", 1090),
    ("Sushi Set", "8 pieces", 1290),
    ("Salad Bowl", "Greens & toppings", 890),
    ("Falafel Wrap", "Chickpeas & tahini", 850),
    ("Tiramisu", "Dessert", 590),
]

def upsert_wallet(session: Session, account_type: str, ref_id: Optional[int], start_cents: int):
    acc = session.exec(select(WalletAccount).where(
        WalletAccount.account_type == account_type,
        WalletAccount.ref_id == ref_id
    )).first()
    if not acc:
        acc = WalletAccount(account_type=account_type, ref_id=ref_id, balance_cents=start_cents)
        session.add(acc)
    else:
        if acc.balance_cents == 0 and start_cents > 0:
            acc.balance_cents = start_cents
    session.commit()
    return acc

def ensure_opening_hours(session: Session, rid: int):
    ohs = session.exec(select(OpeningHour).where(OpeningHour.restaurant_id == rid)).all()
    if not ohs:
        for wd in range(7):
            session.add(OpeningHour(restaurant_id=rid, weekday=wd, open_time="10:00", close_time="22:00"))
        session.commit()

def ensure_delivery_zips(session: Session, rid: int, plz: str):
    existing = session.exec(select(DeliveryZip).where(DeliveryZip.restaurant_id == rid)).all()
    if not existing:
        picks = {plz}
        while len(picks) < 2:
            picks.add(random.choice(PLZS))
        for z in picks:
            session.add(DeliveryZip(restaurant_id=rid, postal_code=z))
        session.commit()

def add_menu_if_needed(session: Session, rid: int):
    rows = session.exec(select(MenuItem).where(MenuItem.restaurant_id == rid)).all()
    if len(rows) < 10:
        for name, desc, price in ITEMS:
            session.add(MenuItem(restaurant_id=rid, name=name, description=desc, price_cents=price))
        session.commit()

def ensure_customer_address(session: Session, customer: Customer) -> CustomerAddress:
    addr = session.exec(
        select(CustomerAddress).where(
            CustomerAddress.customer_id == customer.id,
            CustomerAddress.is_default == True,  # noqa: E712
        )
    ).first()
    if addr:
        return addr

    addr = CustomerAddress(
        customer_id=customer.id,
        label="Home",
        street=customer.street,
        city=customer.city or "Berlin",
        postal_code=customer.postal_code,
        country="DE",
        phone=customer.phone,
        is_default=True,
    )
    session.add(addr)
    session.commit()
    session.refresh(addr)
    return addr


def ensure_vouchers(session: Session):
    now = utcnow_str()
    definitions = [
        ("WELCOME10", "Welcome bonus 10 €", 1000),
        ("LOYAL15", "Loyal customer credit", 1500),
        ("FREESHIP", "Free delivery credit", 500),
    ]
    for code, label, cents in definitions:
        existing = session.exec(select(Voucher).where(Voucher.code == code)).first()
        if existing:
            continue
        voucher = Voucher(
            code=code,
            label=label,
            initial_balance_cents=cents,
            balance_cents=cents,
            currency="EUR",
            created_at=now,
        )
        session.add(voucher)
    session.commit()


def seed_voucher_order(session: Session):
    voucher = session.exec(select(Voucher).where(Voucher.code == "WELCOME10")).first()
    if not voucher or voucher.balance_cents <= 0:
        return

    existing = session.exec(select(Order).where(Order.voucher_id == voucher.id)).first()
    if existing:
        return

    customer = session.exec(select(Customer).order_by(Customer.id)).first()
    restaurant = session.exec(select(Restaurant).order_by(Restaurant.id)).first()
    if not customer or not restaurant:
        return

    menu_item = session.exec(select(MenuItem).where(MenuItem.restaurant_id == restaurant.id)).first()
    if not menu_item:
        return

    addr = ensure_customer_address(session, customer)
    amount = min(voucher.balance_cents, menu_item.price_cents)
    platform_fee = round(menu_item.price_cents * 0.15)
    rest_payout = menu_item.price_cents - platform_fee

    order = Order(
        customer_id=customer.id,
        restaurant_id=restaurant.id,
        address_id=addr.id if addr else None,
        voucher_id=voucher.id,
        status="abgeschlossen",
        payment_status="paid",
        payment_method="voucher",
        note_for_kitchen="Sample voucher redemption",
        subtotal_cents=menu_item.price_cents,
        shipping_cents=0,
        voucher_amount_cents=amount,
        total_cents=max(menu_item.price_cents - amount, 0),
        fee_platform_cents=platform_fee,
        payout_rest_cents=rest_payout,
        created_at=utcnow_str(),
        confirmed_at=utcnow_str(),
        closed_at=utcnow_str(),
    )
    session.add(order)
    session.flush()

    session.add(
        OrderItem(
            order_id=order.id,
            menu_item_id=menu_item.id,
            name_snapshot=menu_item.name,
            price_cents_snapshot=menu_item.price_cents,
            quantity=1,
        )
    )

    voucher.balance_cents = max(voucher.balance_cents - amount, 0)
    if voucher.balance_cents <= 0:
        voucher.is_active = False
    session.add(voucher)
    session.add(
        VoucherRedemption(
            voucher_id=voucher.id,
            order_id=order.id,
            amount_cents=amount,
            redeemed_at=utcnow_str(),
        )
    )
    session.add(
        PaymentTxn(
            order_id=order.id,
            provider="voucher",
            provider_ref=voucher.code,
            amount_cents=amount,
            currency=voucher.currency,
            status="settled",
        )
    )

    session.add(OrderEvent(order_id=order.id, event="order_created"))
    session.add(OrderEvent(order_id=order.id, event="order_completed"))
    session.commit()

def charge_on_confirm(session: Session, order: Order):
    platform_fee = round(order.subtotal_cents * 0.15)
    rest_payout = order.subtotal_cents - platform_fee

    cust_acc = session.exec(select(WalletAccount).where(
        WalletAccount.account_type == "customer", WalletAccount.ref_id == order.customer_id
    )).first()
    rest_acc = session.exec(select(WalletAccount).where(
        WalletAccount.account_type == "restaurant", WalletAccount.ref_id == order.restaurant_id
    )).first()
    plat_acc = session.exec(select(WalletAccount).where(
        WalletAccount.account_type == "platform", WalletAccount.ref_id == None
    )).first()

    if not all([cust_acc, rest_acc, plat_acc]):
        raise RuntimeError("Missing wallet accounts")

    if cust_acc.balance_cents < order.subtotal_cents:
        order.status = "storniert"
        session.commit()
        return

    cust_acc.balance_cents -= order.subtotal_cents
    session.add(WalletTxn(account_id=cust_acc.id, amount_cents=-order.subtotal_cents, reason="order_charge", order_id=order.id))

    plat_acc.balance_cents += platform_fee
    session.add(WalletTxn(account_id=plat_acc.id, amount_cents=platform_fee, reason="order_fee_platform", order_id=order.id))

    rest_acc.balance_cents += rest_payout
    session.add(WalletTxn(account_id=rest_acc.id, amount_cents=rest_payout, reason="order_payout_restaurant", order_id=order.id))

    order.fee_platform_cents = platform_fee
    order.payout_rest_cents = rest_payout
    order.payment_status = "paid"
    if not order.payment_method:
        order.payment_method = "wallet"

    existing_txn = session.exec(
        select(PaymentTxn).where(
            PaymentTxn.order_id == order.id,
            PaymentTxn.provider == "wallet",
        )
    ).first()
    if not existing_txn:
        session.add(
            PaymentTxn(
                order_id=order.id,
                provider="wallet",
                provider_ref=str(cust_acc.id),
                amount_cents=order.total_cents,
                currency="EUR",
                status="settled",
            )
        )

    has_event = session.exec(
        select(OrderEvent).where(
            OrderEvent.order_id == order.id,
            OrderEvent.event == "order_paid",
        )
    ).first()
    if not has_event:
        session.add(OrderEvent(order_id=order.id, event="order_paid"))

    session.commit()

def seed():
    init_db()

    with Session(engine) as session:
        upsert_wallet(session, "platform", None, 0)

        demo_customers = [
            ("alice@example.com", "Alice", "A", "Teichstr. 1", "10115", "alice"),
            ("bob@example.com", "Bob", "B", "Waldweg 2", "10117", "bob"),
            ("carol@example.com", "Carol", "C", "Hafenstr. 3", "10119", "carol"),
            ("you@example.com", "You", "Test", "Some St 1", "10115", "test123"),
            ("dave@example.com", "Dave", "D", "Uferweg 4", "10243", "dave"),
        ]
        for email, fn, ln, street, plz, pw in demo_customers:
            c = session.exec(select(Customer).where(Customer.email == email)).first()
            if not c:
                c = Customer(email=email, first_name=fn, last_name=ln, street=street, postal_code=plz, password_hash=hash_password(pw))
                session.add(c); session.commit()
            upsert_wallet(session, "customer", c.id, 10000)

        names = [
            "Pasta Palace", "Curry Corner", "Burger Barn", "Sushi Spot", "Falafel Friends",
            "Waffle Works", "Taco Town", "Pho Place", "Salad Studio", "Pizza Piazza"
        ]
        for i, name in enumerate(names):
            plz = PLZS[i % len(PLZS)]
            r = session.exec(select(Restaurant).where(Restaurant.name == name)).first()
            if not r:
                r = Restaurant(
                    name=name, street=f"Food St {i+1}", postal_code=plz,
                    description=f"Tasty {name}", password_hash=hash_password(name.split()[0].lower()),
                    image_url=None,
                    email=f"{name.lower().replace(' ', '')}@demo.local",
                    is_approved=True,
                    is_online=True,
                    public_id=generate_public_id(session, Restaurant, "public_id", prefix="RST"),
                )
                session.add(r); session.commit()
            else:
                updated = False
                if not r.email:
                    r.email = f"{name.lower().replace(' ', '')}@demo.local"
                    updated = True
                if not r.is_approved:
                    r.is_approved = True
                    updated = True
                if not r.public_id:
                    r.public_id = generate_public_id(session, Restaurant, "public_id", prefix="RST")
                    updated = True
                if updated:
                    session.add(r); session.commit()
            if not r.is_online:
                r.is_online = True
                session.add(r); session.commit()
            upsert_wallet(session, "restaurant", r.id, 0)
            ensure_opening_hours(session, r.id)
            ensure_delivery_zips(session, r.id, r.postal_code)
            add_menu_if_needed(session, r.id)

        ensure_vouchers(session)

        customers = session.exec(select(Customer)).all()
        for cust in customers:
            ensure_customer_address(session, cust)
            rids = session.exec(
                select(Restaurant.id).where(
                    Restaurant.id.in_(select(DeliveryZip.restaurant_id).where(DeliveryZip.postal_code == cust.postal_code))
                )
            ).all()
            if not rids:
                continue

            # two completed orders per customer
            for _ in range(2):
                rid = random.choice(rids)
                items = session.exec(select(MenuItem).where(MenuItem.restaurant_id == rid)).all()
                if len(items) < 2:
                    continue
                chosen = items[:3] if len(items) >= 3 else items

                # 1) add order WITHOUT committing, just flush to get id
                order = Order(
                    customer_id=cust.id,
                    restaurant_id=rid,
                    status="in_bearbeitung",
                    note_for_kitchen=None,
                    created_at=utcnow_str(),
                    subtotal_cents=0,   # temp to satisfy NOT NULL
                    total_cents=0,
                    fee_platform_cents=0,   # <-- add this
                    payout_rest_cents=0 
                )
                session.add(order)
                session.flush()  # gives order.id without committing

                # 2) add items & compute subtotal
                subtotal = 0
                for it in chosen:
                    qty = random.choice([1, 1, 2])
                    session.add(OrderItem(
                        order_id=order.id,
                        menu_item_id=it.id,
                        name_snapshot=it.name,
                        price_cents_snapshot=it.price_cents,  # <-- correct column
                        quantity=qty
                    ))
                    subtotal += it.price_cents * qty

                # 3) fill totals, then commit
                order.subtotal_cents = subtotal
                order.total_cents = subtotal
                session.commit()

                if not session.exec(select(OrderEvent).where(OrderEvent.order_id == order.id, OrderEvent.event == "order_created")).first():
                    session.add(OrderEvent(order_id=order.id, event="order_created"))
                    session.commit()

                # 4) charge & finish
                order.status = "in_zubereitung"
                order.confirmed_at = utcnow_str()
                session.commit()
                charge_on_confirm(session, order)

                order.status = "abgeschlossen"
                order.closed_at = utcnow_str()
                session.commit()
                if not session.exec(select(OrderEvent).where(OrderEvent.order_id == order.id, OrderEvent.event == "order_completed")).first():
                    session.add(OrderEvent(order_id=order.id, event="order_completed"))
                    session.commit()

        seed_voucher_order(session)

    print("Seed complete with >=10 restaurants (>=10 items each) and >=5 customers with >=2 completed orders/person.")

if __name__ == "__main__":
    seed()
