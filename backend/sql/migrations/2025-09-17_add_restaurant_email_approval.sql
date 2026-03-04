-- backend/sql/migrations/2025-09-17_add_restaurant_email_approval.sql
ALTER TABLE restaurant ADD COLUMN email TEXT;
ALTER TABLE restaurant ADD COLUMN is_approved INTEGER NOT NULL DEFAULT 0;

UPDATE restaurant SET is_approved = 1 WHERE is_approved = 0;

CREATE UNIQUE INDEX IF NOT EXISTS idx_restaurant_email_unique
ON restaurant(email)
WHERE email IS NOT NULL;
