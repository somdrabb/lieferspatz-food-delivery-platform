BEGIN TRANSACTION;

CREATE TABLE IF NOT EXISTS customeraddress (
    id INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES customer(id),
    label TEXT,
    street TEXT NOT NULL,
    city TEXT NOT NULL,
    postal_code TEXT NOT NULL,
    country TEXT NOT NULL DEFAULT 'DE',
    phone TEXT,
    instructions TEXT,
    is_default INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_customeraddress_customer_id ON customeraddress(customer_id);

CREATE TABLE IF NOT EXISTS voucher (
    id INTEGER PRIMARY KEY,
    code TEXT NOT NULL UNIQUE,
    label TEXT,
    initial_balance_cents INTEGER NOT NULL DEFAULT 0,
    balance_cents INTEGER NOT NULL DEFAULT 0,
    currency TEXT NOT NULL DEFAULT 'EUR',
    valid_from TEXT,
    valid_until TEXT,
    max_redemptions INTEGER,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_voucher_code ON voucher(code);

CREATE TABLE IF NOT EXISTS voucherredemption (
    id INTEGER PRIMARY KEY,
    voucher_id INTEGER NOT NULL REFERENCES voucher(id),
    order_id INTEGER NOT NULL REFERENCES "order"(id),
    amount_cents INTEGER NOT NULL DEFAULT 0,
    redeemed_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_voucherredemption_voucher ON voucherredemption(voucher_id);
CREATE INDEX IF NOT EXISTS idx_voucherredemption_order ON voucherredemption(order_id);

CREATE TABLE IF NOT EXISTS paymenttxn (
    id INTEGER PRIMARY KEY,
    order_id INTEGER NOT NULL REFERENCES "order"(id),
    provider TEXT NOT NULL,
    provider_ref TEXT,
    amount_cents INTEGER NOT NULL DEFAULT 0,
    currency TEXT NOT NULL DEFAULT 'EUR',
    status TEXT NOT NULL DEFAULT 'pending',
    meta_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_paymenttxn_order ON paymenttxn(order_id);
CREATE INDEX IF NOT EXISTS idx_paymenttxn_provider_ref ON paymenttxn(provider_ref);

CREATE TABLE IF NOT EXISTS orderevent (
    id INTEGER PRIMARY KEY,
    order_id INTEGER NOT NULL REFERENCES "order"(id),
    event TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_orderevent_order ON orderevent(order_id);

ALTER TABLE "order" ADD COLUMN address_id INTEGER REFERENCES customeraddress(id);
ALTER TABLE "order" ADD COLUMN voucher_id INTEGER REFERENCES voucher(id);
ALTER TABLE "order" ADD COLUMN payment_status TEXT NOT NULL DEFAULT 'pending';
ALTER TABLE "order" ADD COLUMN payment_method TEXT;
ALTER TABLE "order" ADD COLUMN payment_reference TEXT;
ALTER TABLE "order" ADD COLUMN shipping_cents INTEGER NOT NULL DEFAULT 0;
ALTER TABLE "order" ADD COLUMN voucher_amount_cents INTEGER NOT NULL DEFAULT 0;
ALTER TABLE "order" ADD COLUMN updated_at TEXT NOT NULL DEFAULT '1970-01-01T00:00:00Z';
ALTER TABLE voucher ADD COLUMN currency TEXT NOT NULL DEFAULT 'EUR';
ALTER TABLE voucher ADD COLUMN balance_cents INTEGER NOT NULL DEFAULT 0;


UPDATE "order" SET updated_at = created_at WHERE updated_at = '1970-01-01T00:00:00Z';

COMMIT;
