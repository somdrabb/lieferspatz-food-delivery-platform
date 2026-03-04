-- 2025-09-17_add_public_ids.sql
-- Introduce public identifiers for orders and restaurants
-- and keep a lightweight audit trail for deleted restaurants.

ALTER TABLE "order" ADD COLUMN IF NOT EXISTS public_id TEXT;
ALTER TABLE restaurant ADD COLUMN IF NOT EXISTS public_id TEXT;

CREATE TABLE IF NOT EXISTS deletedrestaurant (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    original_restaurant_id INTEGER,
    restaurant_public_id TEXT NOT NULL,
    name TEXT NOT NULL,
    deleted_at TEXT NOT NULL,
    extra_json TEXT NOT NULL DEFAULT '{}'
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_order_public_id ON "order"(public_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_restaurant_public_id ON restaurant(public_id);
CREATE INDEX IF NOT EXISTS idx_deletedrestaurant_public_id ON deletedrestaurant(restaurant_public_id);
