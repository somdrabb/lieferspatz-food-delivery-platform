ALTER TABLE "order"
    ADD COLUMN admin_visible INTEGER NOT NULL DEFAULT 1;

ALTER TABLE "order"
    ADD COLUMN hidden_for_customer INTEGER NOT NULL DEFAULT 0;

ALTER TABLE "order"
    ADD COLUMN hidden_for_restaurant INTEGER NOT NULL DEFAULT 0;
