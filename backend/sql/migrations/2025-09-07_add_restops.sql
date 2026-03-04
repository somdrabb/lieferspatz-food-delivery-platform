-- backend/sql/migrations/2025-09-17_add_restops.sql
ALTER TABLE restaurant ADD COLUMN image_url TEXT;
ALTER TABLE restaurant ADD COLUMN min_order_cents INTEGER NOT NULL DEFAULT 0;
ALTER TABLE restaurant ADD COLUMN delivery_fee_cents INTEGER NOT NULL DEFAULT 0;
ALTER TABLE restaurant ADD COLUMN prep_time_min INTEGER NOT NULL DEFAULT 20;
ALTER TABLE restaurant ADD COLUMN is_online INTEGER NOT NULL DEFAULT 1;
ALTER TABLE restaurant ADD COLUMN busy_until TEXT;
ALTER TABLE restaurant ADD COLUMN is_demo INTEGER NOT NULL DEFAULT 0;

